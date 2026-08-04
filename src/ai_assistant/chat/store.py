"""Sohbet durumunun DİSK kopyası — cron yoklamasının hafızası.

BU MODÜLÜN VAR OLMA SEBEBİ: her cron yoklaması yeni bir süreçtir. Kullanıcı
"1" yazdığında ona menüyü gösteren süreç çoktan ölmüştür. Bellekte tutulan bir
oturum, bir sonraki yoklamada yok olur ve kullanıcı her mesajında birinci adıma
düşer. Bu yüzden ÜÇ şey diske yazılır:

* ``cursor`` — kanal başına en son işlenen mesajın ``ts``si. İmleç olmadan aynı
  mesaj her yoklamada yeniden işlenir (ve kullanıcıya aynı menü tekrar tekrar
  gider).
* ``sessions`` — kullanıcı başına açık sipariş: hangi adımdayız, o ana kadar ne
  seçildi, menüde hangi seçenekler vardı.
* ``templates`` — isimle kaydedilmiş rapor tarifleri.

Dosya yolu ``CHAT_STATE_FILE`` ile değiştirilir; varsayılan
``.assistant_state/chat_state.json``. Runner'ın diski atıldığı için bu dosya
her yoklamanın sonunda depoya COMMİT EDİLEREK kalıcılaştırılır (bkz.
``.github/workflows/chat-poller.yml``, "Sohbet durumunu kalıcılaştır" adımı ve
``.gitignore`` içindeki ``!.assistant_state/chat_state.json`` istisnası).
Commit edilmezse imleç her koşuda boş görünür, EN SON insan mesajı yeniden
işlenir ve kullanıcı sonsuza kadar birinci adımda kalır.

Hiçbir işlem istisna fırlatmaz: okunamayan/bozuk dosya BOŞ durum sayılır, çünkü
sohbeti çökertmektense baştan başlatmak daha iyidir.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

STATE_FILE_ENV = "CHAT_STATE_FILE"
DEFAULT_STATE_FILE = ".assistant_state/chat_state.json"

STATE_VERSION = 1

#: Bir oturum bu kadar dakika dokunulmadan kalırsa terk edilmiş sayılır ve
#: kullanıcı yeniden birinci adımdan başlar. Yarım kalmış bir siparişin ertesi
#: gün "5" yazınca canlanması kafa karıştırıcı olurdu.
SESSION_TTL_ENV = "CHAT_SESSION_TTL_MINUTES"
DEFAULT_SESSION_TTL_MINUTES = 120


def state_file_path() -> str:
    return (os.getenv(STATE_FILE_ENV) or "").strip() or DEFAULT_STATE_FILE


def session_ttl_minutes() -> int:
    raw = (os.getenv(SESSION_TTL_ENV) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_SESSION_TTL_MINUTES
    return value if value > 0 else DEFAULT_SESSION_TTL_MINUTES


def session_key(channel: str, user: str) -> str:
    """Oturum kimliği: aynı kanalda iki kişi birbirinin siparişini görmez."""
    return f"{channel}:{user}"


class ChatStore:
    """``chat_state.json`` üzerindeki ince katman. Asla istisna atmaz.

    Kurulduğu anda dosyayı okur — yani YENİ BİR SÜREÇ, önceki yoklamanın
    bıraktığı yerden devam eder. Her değişiklikten sonra :meth:`save` çağrılır;
    süreç bir sonraki satırda ölse bile durum diskte durur.
    """

    def __init__(self, path: str = ""):
        self.path = path or state_file_path()
        self.cursors: Dict[str, str] = {}
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.templates: Dict[str, Dict[str, Any]] = {}
        #: Son kullanılan veri kaynağı (kullanıcı başına) — "son kaynağı kullan".
        self.last_sources: Dict[str, Dict[str, Any]] = {}
        #: Son TAMAMLANAN rapor tarifi — "… olarak kaydet" bunu şablona çevirir.
        self.last_specs: Dict[str, Dict[str, Any]] = {}
        self.load()

    # --- disk ---------------------------------------------------------------

    def load(self) -> None:
        """Diskteki durumu okur. Dosya yoksa ya da bozuksa boş durumla devam."""
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return
        except Exception as exc:
            logger.warning("sohbet durumu okunamadı (%s): %s", self.path, exc)
            return
        if not isinstance(data, dict):
            return
        self.cursors = {
            str(k): str(v) for k, v in (data.get("cursors") or {}).items() if str(v)
        }
        self.sessions = {
            str(k): v for k, v in (data.get("sessions") or {}).items() if isinstance(v, dict)
        }
        self.templates = {
            str(k): v for k, v in (data.get("templates") or {}).items() if isinstance(v, dict)
        }
        self.last_sources = {
            str(k): v
            for k, v in (data.get("last_sources") or {}).items()
            if isinstance(v, dict)
        }
        self.last_specs = {
            str(k): v
            for k, v in (data.get("last_specs") or {}).items()
            if isinstance(v, dict)
        }

    def save(self) -> bool:
        """Durumu ATOMİK olarak yazar.

        Geçici dosyaya yazıp ``os.replace`` ile yerine koyar: yarım yazılmış bir
        JSON, bir sonraki yoklamanın imleci kaybetmesi demektir ve o da her
        mesajın ikinci kez işlenmesi demektir.
        """
        payload = {
            "state_version": STATE_VERSION,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "cursors": dict(self.cursors),
            "sessions": dict(self.sessions),
            "templates": dict(self.templates),
            "last_sources": dict(self.last_sources),
            "last_specs": dict(self.last_specs),
        }
        try:
            directory = os.path.dirname(os.path.abspath(self.path))
            if directory:
                os.makedirs(directory, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=directory or ".",
                prefix=".chat_state-",
                suffix=".tmp",
                delete=False,
            )
            try:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            finally:
                handle.close()
            os.replace(handle.name, self.path)
            return True
        except Exception as exc:
            logger.warning("sohbet durumu yazılamadı (%s): %s", self.path, exc)
            return False

    # --- imleç --------------------------------------------------------------

    def cursor(self, channel: str) -> str:
        """Bu kanalda en son işlenen mesajın ``ts``si ("" = hiç okunmadı)."""
        return self.cursors.get(channel, "")

    def set_cursor(self, channel: str, ts: str) -> None:
        """İmleci İLERİ taşır. Geriye asla gitmez.

        Slack ``conversations.history`` sonuçlarını yeniden eskiye sıralar; bir
        toplu işlemede imleç yanlışlıkla en eski mesaja çekilirse aradaki her
        mesaj bir kez daha işlenir. Bu yüzden karşılaştırma açık: ``ts`` bir
        ondalık sayı olarak büyüdüyse yazılır.
        """
        current = self.cursors.get(channel, "")
        if _ts_value(ts) > _ts_value(current):
            self.cursors[channel] = str(ts)

    # --- oturumlar ----------------------------------------------------------

    def get_session(self, channel: str, user: str) -> Optional[Dict[str, Any]]:
        return self.sessions.get(session_key(channel, user))

    def put_session(self, channel: str, user: str, data: Dict[str, Any]) -> None:
        self.sessions[session_key(channel, user)] = data

    def drop_session(self, channel: str, user: str) -> bool:
        return self.sessions.pop(session_key(channel, user), None) is not None

    def prune_sessions(self, now: Optional[datetime] = None) -> List[str]:
        """Süresi dolmuş oturumları atar; atılanların anahtarlarını döner."""
        moment = now or datetime.now()
        ttl = session_ttl_minutes()
        dropped: List[str] = []
        for key, payload in list(self.sessions.items()):
            touched = _parse_time(payload.get("updated_at"))
            if touched is None:
                continue
            if (moment - touched).total_seconds() > ttl * 60:
                self.sessions.pop(key, None)
                dropped.append(key)
        return dropped

    # --- şablonlar ----------------------------------------------------------

    def user_templates(self, user: str) -> Dict[str, Any]:
        return self.templates.setdefault(user, {})

    # --- son kaynak ---------------------------------------------------------

    def last_source(self, user: str) -> Dict[str, Any]:
        return self.last_sources.get(user) or {}

    def remember_source(self, user: str, payload: Dict[str, Any]) -> None:
        if payload:
            self.last_sources[user] = dict(payload)

    # --- son tamamlanan tarif -----------------------------------------------

    def last_spec(self, user: str) -> Dict[str, Any]:
        return self.last_specs.get(user) or {}

    def remember_spec(self, user: str, payload: Dict[str, Any]) -> None:
        if payload:
            self.last_specs[user] = dict(payload)


def _ts_value(ts: str) -> float:
    """Slack ``ts``sinin sayısal karşılığı; çözülemezse ``-1``."""
    try:
        return float(str(ts or "") or -1)
    except ValueError:
        return -1.0


def _parse_time(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


__all__ = [
    "ChatStore",
    "DEFAULT_SESSION_TTL_MINUTES",
    "DEFAULT_STATE_FILE",
    "SESSION_TTL_ENV",
    "STATE_FILE_ENV",
    "STATE_VERSION",
    "session_key",
    "session_ttl_minutes",
    "state_file_path",
]
