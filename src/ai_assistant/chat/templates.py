"""Şablonlar: bir kez tarif et, sonra tek satırla çalıştır.

Yedi adımı her hafta yeniden tıklamak, haftalık bir raporu haftalık bir angaryaya
çevirir. Tamamlanmış bir sipariş bir adla saklanır:

    haftalık SLA raporu olarak kaydet
    haftalık SLA raporu çalıştır
    şablonlar
    haftalık SLA raporu şablonunu sil

Şablon KULLANICIYA aittir (aynı kanalda iki kişinin "haftalık rapor"u farklıdır)
ve :mod:`ai_assistant.chat.store` üzerinden diske yazılır — yani bir sonraki
cron sürecinde de oradadır.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .menu import normalize
from .spec import ReportSpec
from .store import ChatStore

#: Bir kullanıcı en çok bu kadar şablon tutabilir.
MAX_TEMPLATES = 25

KIND_SAVE = "kaydet"
KIND_RUN = "calistir"
KIND_LIST = "listele"
KIND_DELETE = "sil"

#: "… olarak kaydet" / "şablon kaydet: …"
_SAVE_RES = (
    re.compile(r"^(?P<name>.+?)\s+(?:olarak|adıyla|adiyla|diye)\s+kaydet$"),
    re.compile(r"^şablon(?:u|)\s+kaydet\s*[:\-]?\s*(?P<name>.+)$"),
    re.compile(r"^sablon(?:u|)\s+kaydet\s*[:\-]?\s*(?P<name>.+)$"),
)

#: "… çalıştır" / "şablon çalıştır …"
_RUN_RES = (
    re.compile(r"^şablon(?:u|)\s+çalıştır\s*[:\-]?\s*(?P<name>.+)$"),
    re.compile(r"^sablon(?:u|)\s+calistir\s*[:\-]?\s*(?P<name>.+)$"),
    re.compile(r"^(?P<name>.+?)\s+şablonunu\s+(?:çalıştır|calistir|aç|ac)$"),
    re.compile(r"^(?P<name>.+?)\s+(?:çalıştır|calistir)$"),
)

#: "… şablonunu sil" / "şablon sil …"
_DELETE_RES = (
    re.compile(r"^şablon(?:u|)\s+sil\s*[:\-]?\s*(?P<name>.+)$"),
    re.compile(r"^sablon(?:u|)\s+sil\s*[:\-]?\s*(?P<name>.+)$"),
    re.compile(r"^(?P<name>.+?)\s+şablonunu\s+sil$"),
    re.compile(r"^(?P<name>.+?)\s+sablonunu\s+sil$"),
)

_LIST_WORDS = {
    "şablonlar",
    "sablonlar",
    "şablonlarım",
    "sablonlarim",
    "şablon listesi",
    "sablon listesi",
    "şablonları listele",
    "sablonlari listele",
    "kayıtlı raporlar",
    "kayitli raporlar",
}


@dataclass
class Command:
    """Ayrıştırılmış şablon komutu."""

    kind: str
    name: str = ""


def parse_command(text: str) -> Optional[Command]:
    """Mesajı bir şablon komutuna çevirir; komut değilse ``None``."""
    body = normalize(text)
    if not body:
        return None
    if body in _LIST_WORDS:
        return Command(KIND_LIST)
    for pattern in _DELETE_RES:
        match = pattern.match(body)
        if match:
            return Command(KIND_DELETE, _clean(match.group("name")))
    for pattern in _SAVE_RES:
        match = pattern.match(body)
        if match:
            return Command(KIND_SAVE, _clean(match.group("name")))
    for pattern in _RUN_RES:
        match = pattern.match(body)
        if match:
            return Command(KIND_RUN, _clean(match.group("name")))
    return None


def _clean(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip(" \"'“”·.,:;")).strip()


def _key(name: str) -> str:
    """Arama anahtarı: büyük/küçük harf ve fazladan boşluk fark etmez."""
    return normalize(name)


@dataclass
class Template:
    """Adlandırılmış bir rapor tarifi."""

    name: str
    spec: ReportSpec = field(default_factory=ReportSpec)
    created_at: str = ""
    used_at: str = ""
    uses: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "spec": self.spec.as_dict(),
            "created_at": self.created_at,
            "used_at": self.used_at,
            "uses": self.uses,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Template":
        payload = data if isinstance(data, dict) else {}
        return cls(
            name=str(payload.get("name") or ""),
            spec=ReportSpec.from_dict(payload.get("spec")),
            created_at=str(payload.get("created_at") or ""),
            used_at=str(payload.get("used_at") or ""),
            uses=int(payload.get("uses") or 0),
        )

    def line(self) -> str:
        """Liste görünümündeki tek satır."""
        tail = f" · {self.uses} kez çalıştırıldı" if self.uses else ""
        return f"*{self.name}* — {self.spec.one_line()}{tail}"


class TemplateStore:
    """Bir kullanıcının şablonları üzerinde ince katman."""

    def __init__(self, store: ChatStore, user: str):
        self.store = store
        self.user = user

    def _bucket(self) -> Dict[str, Any]:
        return self.store.user_templates(self.user)

    def list(self) -> List[Template]:
        items = [Template.from_dict(v) for v in self._bucket().values()]
        return sorted(items, key=lambda t: _key(t.name))

    def get(self, name: str) -> Optional[Template]:
        payload = self._bucket().get(_key(name))
        return Template.from_dict(payload) if payload else None

    def save(
        self, name: str, spec: ReportSpec, now: Optional[datetime] = None
    ) -> Template:
        """Şablonu yazar (aynı ad varsa ÜZERİNE yazar) ve diske işler."""
        moment = (now or datetime.now()).isoformat(timespec="seconds")
        existing = self.get(name)
        template = Template(
            name=name,
            spec=spec.copy(),
            created_at=existing.created_at if existing else moment,
            used_at=existing.used_at if existing else "",
            uses=existing.uses if existing else 0,
        )
        self._bucket()[_key(name)] = template.as_dict()
        self._trim()
        self.store.save()
        return template

    def delete(self, name: str) -> bool:
        removed = self._bucket().pop(_key(name), None) is not None
        if removed:
            self.store.save()
        return removed

    def touch(self, name: str, now: Optional[datetime] = None) -> Optional[Template]:
        """Çalıştırma sayacını artırır."""
        template = self.get(name)
        if template is None:
            return None
        template.uses += 1
        template.used_at = (now or datetime.now()).isoformat(timespec="seconds")
        self._bucket()[_key(name)] = template.as_dict()
        self.store.save()
        return template

    def _trim(self) -> None:
        """Sınırı aşan EN ESKİ şablonları atar; liste menü olmaktan çıkmasın."""
        bucket = self._bucket()
        if len(bucket) <= MAX_TEMPLATES:
            return
        ordered = sorted(
            bucket.items(),
            key=lambda item: str((item[1] or {}).get("created_at") or ""),
        )
        for key, _ in ordered[: len(bucket) - MAX_TEMPLATES]:
            bucket.pop(key, None)


@dataclass
class Result:
    """Bir şablon komutunun sonucu."""

    messages: List[str] = field(default_factory=list)
    #: Doluysa bu tarif ÇALIŞTIRILACAK.
    spec: Optional[ReportSpec] = None
    #: Komut tanındı mı? (``False`` ise çağıran normal akışa devam eder.)
    handled: bool = False


def handle(
    text: str,
    store: ChatStore,
    user: str,
    current: Optional[ReportSpec] = None,
    now: Optional[datetime] = None,
) -> Result:
    """Bir şablon komutunu çalıştırır.

    ``current`` kaydedilecek tarif: onay ekranındaki sipariş, o yoksa
    kullanıcının EN SON tamamladığı rapor. İkisi de yoksa kayıt yapılamaz ve
    kullanıcıya nedeni söylenir.
    """
    command = parse_command(text)
    if command is None:
        return Result()

    templates = TemplateStore(store, user)

    if command.kind == KIND_LIST:
        items = templates.list()
        if not items:
            return Result(
                handled=True,
                messages=[
                    "Kayıtlı şablon yok. Bir raporu tamamladıktan sonra "
                    "`<ad> olarak kaydet` yazarak saklayabilirsiniz."
                ],
            )
        body = "\n".join(f"• {t.line()}" for t in items)
        return Result(
            handled=True,
            messages=[
                f"*Kayıtlı şablonlar ({len(items)})*\n{body}\n"
                "_Çalıştırmak için: `<ad> çalıştır`_"
            ],
        )

    if command.kind == KIND_SAVE:
        if not command.name:
            return Result(
                handled=True, messages=["Şablona bir ad verin: `<ad> olarak kaydet`."]
            )
        source = current or _last_spec(store, user)
        if source is None or not source.has_source():
            return Result(
                handled=True,
                messages=[
                    "Kaydedilecek bir rapor tarifi yok. Önce bir rapor "
                    "tamamlayın, sonra `<ad> olarak kaydet` yazın."
                ],
            )
        template = templates.save(command.name, source, now=now)
        return Result(
            handled=True,
            messages=[
                f"*{template.name}* şablon olarak kaydedildi.\n"
                f"{template.spec.one_line()}\n"
                f"_Çalıştırmak için: `{template.name} çalıştır`_"
            ],
        )

    if command.kind == KIND_DELETE:
        if templates.delete(command.name):
            return Result(handled=True, messages=[f"*{command.name}* şablonu silindi."])
        return Result(handled=True, messages=[_not_found(command.name, templates)])

    if command.kind == KIND_RUN:
        template = templates.get(command.name)
        if template is None:
            # Tanınmayan bir "… çalıştır" cümlesi şablon komutu OLMAYABİLİR;
            # kullanıcı serbest bir istek yazmış olabilir. Şablon listesi boşsa
            # komutu sahiplenmeyip normal akışa bırakıyoruz.
            if not templates.list():
                return Result()
            return Result(handled=True, messages=[_not_found(command.name, templates)])
        templates.touch(command.name, now=now)
        return Result(handled=True, spec=template.spec.copy(), messages=[])

    return Result()


def _last_spec(store: ChatStore, user: str) -> Optional[ReportSpec]:
    payload = store.last_spec(user)
    if not payload:
        return None
    spec = ReportSpec.from_dict(payload)
    return spec if spec.has_source() else None


def _not_found(name: str, templates: TemplateStore) -> str:
    known = templates.list()
    listing = ", ".join(f"*{t.name}*" for t in known[:8])
    tail = f" Kayıtlı şablonlar: {listing}." if listing else ""
    return f"*{name}* diye bir şablon yok.{tail}"


__all__ = [
    "Command",
    "KIND_DELETE",
    "KIND_LIST",
    "KIND_RUN",
    "KIND_SAVE",
    "MAX_TEMPLATES",
    "Result",
    "Template",
    "TemplateStore",
    "handle",
    "parse_command",
]
