"""LinkedIn REST istemcisi — GERÇEK istek, ya da açıkça ``skipped``.

NEDEN VAR
---------
``advisors/linkedin_coach.py`` bir erişim jetonu OKUYORDU
(``LINKEDIN_ACCESS_TOKEN``) ama onu hiçbir HTTP isteğine koymuyordu:
``publish_post()`` yerel bir JSON dosyasına "yayınlandı" yazıp ``True``
dönüyor, ``track_engagement()`` uydurma takipçi/gösterim sayıları üretiyordu.
Yani kullanıcı "paylaşıldı" cümlesini okurken LinkedIn'de hiçbir şey olmuyordu.
Bu modül o boşluğu kapatır ve bir kuralı mutlaklaştırır:

    **SAHTE BAŞARI YOK.** Jeton yoksa istek yapılmaz, "başarılı" denmez;
    ``skipped`` döner ve nedeni Türkçe yazılır.

TASARIM
-------
* :mod:`ai_assistant.integrations.llm` ile aynı httpx kalıbı: ortak
  ``_common.http_get`` / ``http_post``, ortak zaman aşımı, yanıt gövdesinden
  kısa bir teşhis parçası. Yeni bir HTTP katmanı yoktur.
* Her fonksiyon bir :class:`ApiResult` döner — ``ok`` / ``skipped`` /
  ``failed``. İstisna fırlatmaz; günlük koşuyu düşürmek bir paylaşımdan daha
  pahalıdır.
* Jeton hiçbir kayda (log, hata metni) sızmaz: yanıt gövdeleri
  :func:`_redact` süzgecinden geçer.

GÜNLÜK PAYLAŞIM SINIRI
----------------------
``LINKEDIN_MAX_DAILY_POSTS`` (varsayılan **1**). LinkedIn agresif otomasyonu
hesap kısıtlamasıyla cezalandırır; günde tek, gerçekten iyi bir paylaşım
işe alımcı gözünde üç vasat paylaşımdan değerlidir. Sayaç
``.assistant_state/linkedin_quota.json`` içinde tutulur — yeni bir depolama
katmanı açılmaz, danışmanın zaten kullandığı dizindir.

ONAY
----
Bu modül onay BİLMEZ ve onay SORMAZ; sadece "gönder" der. Onay kapısı
``advisors/linkedin_coach.py`` içindedir ve :func:`post_share` yalnızca
onaylanmış bir taslak için çağrılır. Ayrım bilinçli: taşıma katmanı politika
taşımaz, ama politika katmanı taşımayı atlayamaz.

Yapılandırma (ortam değişkenleri):
    LINKEDIN_ACCESS_TOKEN     OAuth erişim jetonu (``w_member_social`` ve
                              ``r_liteprofile`` kapsamları gerekir).
    LINKEDIN_AUTHOR_URN       Paylaşımın sahibi (``urn:li:person:...``).
                              Verilmezse ``/v2/me`` ile bir kez öğrenilir.
    LINKEDIN_MAX_DAILY_POSTS  Günlük paylaşım tavanı (varsayılan 1).
    LINKEDIN_API_BASE         Uç nokta kökü (test/staging için).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import setting
from . import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED
from ._common import http_get, http_post

logger = logging.getLogger(__name__)

ENV_ACCESS_TOKEN = "LINKEDIN_ACCESS_TOKEN"
ENV_AUTHOR_URN = "LINKEDIN_AUTHOR_URN"
ENV_MAX_DAILY_POSTS = "LINKEDIN_MAX_DAILY_POSTS"
ENV_API_BASE = "LINKEDIN_API_BASE"

DEFAULT_API_BASE = "https://api.linkedin.com"

#: Günde en fazla kaç paylaşım. Bir. Bilinçli olarak bir.
DEFAULT_MAX_DAILY_POSTS = 1

#: Jeton yokken verilen TEK cevap. Testler bu cümleyi arar.
SKIP_NO_TOKEN = (
    "LinkedIn token yok, atlandı. Gerçek paylaşım/okuma için "
    f"{ENV_ACCESS_TOKEN} tanımlanmalı."
)

#: Günlük tavan dolduğunda verilen cevap.
SKIP_QUOTA = "Günlük LinkedIn paylaşım sınırı doldu, atlandı."

STATE_DIR = Path(".assistant_state")
QUOTA_FILE = STATE_DIR / "linkedin_quota.json"

#: LinkedIn sürüm başlığı; sürümsüz istekler uç noktaya göre reddedilebiliyor.
LINKEDIN_VERSION = "202405"


@dataclass
class ApiResult:
    """Bir LinkedIn çağrısının sonucu — istisna değil, taşınabilir bir cevap."""

    status: str
    detail: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    @property
    def skipped(self) -> bool:
        return self.status == STATUS_SKIPPED

    def as_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "detail": self.detail, "data": dict(self.data)}


def _ok(detail: str = "", data: Optional[Dict[str, Any]] = None) -> ApiResult:
    return ApiResult(STATUS_OK, detail, dict(data or {}))


def _skipped(detail: str) -> ApiResult:
    return ApiResult(STATUS_SKIPPED, detail)


def _failed(detail: str) -> ApiResult:
    return ApiResult(STATUS_FAILED, detail)


# --- yapılandırma ------------------------------------------------------------


def access_token() -> str:
    """Erişim jetonu; tanımsızsa boş dize."""
    return (setting(ENV_ACCESS_TOKEN) or "").strip()


def is_configured() -> bool:
    """Gerçek bir istek yapılabilir mi?"""
    return bool(access_token())


def api_base() -> str:
    return (setting(ENV_API_BASE) or DEFAULT_API_BASE).rstrip("/")


def max_daily_posts() -> int:
    """Günlük paylaşım tavanı; hatalı değer varsayılana düşer."""
    raw = (setting(ENV_MAX_DAILY_POSTS) or "").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_DAILY_POSTS
    return max(0, value)


def _redact(text: str) -> str:
    """Jetonu metinden siler — hata gövdesi loga da Slack'e de gidebilir."""
    token = access_token()
    if token and token in text:
        text = text.replace(token, "***")
    return text


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token()}",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": LINKEDIN_VERSION,
        "Content-Type": "application/json",
    }


# --- günlük kota -------------------------------------------------------------


def _load_quota() -> Dict[str, Any]:
    try:
        if QUOTA_FILE.exists():
            with open(QUOTA_FILE, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, dict):
                    return data
    except Exception as exc:  # pragma: no cover - bozuk dosya sayacı sıfırlar
        logger.warning("LinkedIn kota dosyası okunamadı: %s", exc)
    return {}


def _save_quota(data: Dict[str, Any]) -> None:
    try:
        STATE_DIR.mkdir(exist_ok=True)
        with open(QUOTA_FILE, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
    except Exception as exc:  # pragma: no cover - yazamamak paylaşımı bozmaz
        logger.warning("LinkedIn kota dosyası yazılamadı: %s", exc)


def posts_today(today: str = "") -> int:
    """Bugün KAÇ paylaşım GERÇEKTEN gönderildi."""
    stamp = today or date.today().isoformat()
    data = _load_quota()
    if data.get("date") != stamp:
        return 0
    try:
        return int(data.get("count", 0))
    except (TypeError, ValueError):
        return 0


def remaining_posts_today(today: str = "") -> int:
    """Bugün kaç paylaşım hakkı kaldı."""
    return max(0, max_daily_posts() - posts_today(today))


def record_post(today: str = "") -> int:
    """Gönderilen bir paylaşımı sayaca işler ve yeni sayıyı döner."""
    stamp = today or date.today().isoformat()
    count = posts_today(stamp) + 1
    _save_quota({"date": stamp, "count": count})
    return count


def reset_quota() -> None:
    """Sayacı sıfırlar (test ve elle müdahale için)."""
    _save_quota({})


# --- uç noktalar -------------------------------------------------------------


def get_profile() -> ApiResult:
    """``GET /v2/me`` — profil kimliği ve adı.

    Jeton yoksa ağa ÇIKILMAZ; ``skipped`` döner.
    """
    if not is_configured():
        logger.info("LinkedIn token yok, profil okuma atlandı")
        return _skipped(SKIP_NO_TOKEN)

    url = f"{api_base()}/v2/me"
    try:
        response = http_get(url, headers=_headers())
    except Exception as exc:
        return _failed(f"LinkedIn profiline ulaşılamadı: {_redact(str(exc))}")

    if not response.is_success:
        snippet = _redact(response.text.strip().replace("\n", " ")[:160])
        return _failed(f"LinkedIn HTTP {response.status_code}: {snippet}")

    try:
        payload = response.json()
    except Exception:
        payload = {}
    return _ok("profil okundu", payload if isinstance(payload, dict) else {})


def author_urn() -> str:
    """Paylaşımın sahibi olan URN.

    Önce ``LINKEDIN_AUTHOR_URN``; yoksa ``/v2/me`` çağrılıp ``id`` alanından
    kurulur. Hiçbiri olmazsa boş dize — çağıran bunu ``skipped``a çevirir.
    """
    configured = (setting(ENV_AUTHOR_URN) or "").strip()
    if configured:
        return configured
    profile = get_profile()
    if not profile.ok:
        return ""
    person_id = str(profile.data.get("id") or "").strip()
    return f"urn:li:person:{person_id}" if person_id else ""


def post_share(text: str, urn: str = "") -> ApiResult:
    """``POST /v2/ugcPosts`` — metni LinkedIn'de paylaşır.

    ÜÇ KAPI, sırayla: metin boş olamaz, jeton olmadan istek yapılmaz, günlük
    tavan aşılamaz. Hiçbiri sağlanmazsa ``skipped`` döner ve **hiçbir HTTP
    isteği yapılmaz** — çağıran "paylaşıldı" diyemez.

    Onay kontrolü BURADA DEĞİL: bu fonksiyona gelen bir metin, çağıran
    tarafından zaten onaylanmış sayılır (bkz. ``advisors.linkedin_coach``).
    """
    body = (text or "").strip()
    if not body:
        return _skipped("Paylaşılacak metin boş, atlandı.")

    if not is_configured():
        logger.info("LinkedIn token yok, paylaşım atlandı")
        return _skipped(SKIP_NO_TOKEN)

    if remaining_posts_today() <= 0:
        logger.info("LinkedIn günlük paylaşım sınırı doldu (%s)", max_daily_posts())
        return _skipped(
            f"{SKIP_QUOTA} Tavan: {max_daily_posts()}/gün "
            f"({ENV_MAX_DAILY_POSTS} ile değiştirilebilir)."
        )

    owner = (urn or "").strip() or author_urn()
    if not owner:
        return _skipped(
            f"Paylaşımın sahibi belirlenemedi: {ENV_AUTHOR_URN} tanımlayın ya "
            f"da jetona /v2/me okuma izni verin. Paylaşım yapılmadı."
        )

    payload = {
        "author": owner,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": body},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }

    try:
        response = http_post(f"{api_base()}/v2/ugcPosts", headers=_headers(), json=payload)
    except Exception as exc:
        return _failed(f"LinkedIn paylaşımı gönderilemedi: {_redact(str(exc))}")

    if not response.is_success:
        snippet = _redact(response.text.strip().replace("\n", " ")[:160])
        return _failed(f"LinkedIn HTTP {response.status_code}: {snippet}")

    post_id = response.headers.get("x-restli-id", "")
    if not post_id:
        try:
            post_id = str(response.json().get("id") or "")
        except Exception:
            post_id = ""

    record_post()
    return _ok("paylaşıldı", {"post_urn": post_id})


def get_engagement(post_urn: str) -> ApiResult:
    """``GET /v2/socialActions/{urn}`` — bir paylaşımın beğeni/yorum sayısı.

    Uydurma metrik ÜRETMEZ: jeton yoksa ``skipped``, istek başarısızsa
    ``failed``. "0 etkileşim" ile "bilmiyorum" birbirine karıştırılamaz.
    """
    urn = (post_urn or "").strip()
    if not urn:
        return _skipped("Paylaşım kimliği (URN) verilmedi, atlandı.")
    if not is_configured():
        logger.info("LinkedIn token yok, etkileşim okuma atlandı")
        return _skipped(SKIP_NO_TOKEN)

    try:
        response = http_get(f"{api_base()}/v2/socialActions/{urn}", headers=_headers())
    except Exception as exc:
        return _failed(f"LinkedIn etkileşimi okunamadı: {_redact(str(exc))}")

    if not response.is_success:
        snippet = _redact(response.text.strip().replace("\n", " ")[:160])
        return _failed(f"LinkedIn HTTP {response.status_code}: {snippet}")

    try:
        payload = response.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    likes = ((payload.get("likesSummary") or {}).get("totalLikes")) or 0
    comments = ((payload.get("commentsSummary") or {}).get("totalFirstLevelComments")) or 0
    return _ok(
        "etkileşim okundu",
        {
            "post_urn": urn,
            "likes": int(likes),
            "comments": int(comments),
            "raw": payload,
        },
    )


__all__ = [
    "ApiResult",
    "DEFAULT_API_BASE",
    "DEFAULT_MAX_DAILY_POSTS",
    "ENV_ACCESS_TOKEN",
    "ENV_AUTHOR_URN",
    "ENV_MAX_DAILY_POSTS",
    "QUOTA_FILE",
    "SKIP_NO_TOKEN",
    "SKIP_QUOTA",
    "access_token",
    "api_base",
    "author_urn",
    "get_engagement",
    "get_profile",
    "is_configured",
    "max_daily_posts",
    "post_share",
    "posts_today",
    "record_post",
    "remaining_posts_today",
    "reset_quota",
]
