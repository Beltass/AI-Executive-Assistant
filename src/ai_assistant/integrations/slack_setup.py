"""Slack workspace provisioning — create the main channel and the sub-channels.

The delivery layout this project expects is ONE main channel plus ONE channel
per advisor:

* ``SLACK_MAIN_CHANNEL`` receives the daily digest — one line per advisor with
  its headline and the links;
* ``SLACK_CHANNEL_<ADVISOR_KEY>`` receives that advisor's own section in full.

Creating thirteen channels by hand, copying thirteen channel ids out of the
Slack UI and pasting them into ``.env`` without a typo is exactly the kind of task
that should not be done by hand. This module does it::

    # 1. See what WOULD happen (default — nothing is created):
    python -m ai_assistant.integrations.slack_setup

    # 2. Actually create the channels:
    python -m ai_assistant.integrations.slack_setup --apply

    # 3. Create them and write the ids straight into .env:
    python -m ai_assistant.integrations.slack_setup --apply --write-env

It is IDEMPOTENT: a channel that already exists (by name, or already pinned in
``.env`` by id) is reused, never duplicated, so re-running is safe and is in
fact the intended way to add a channel for a newly added advisor.

REQUIRED BOT TOKEN SCOPES
-------------------------

``SLACK_BOT_TOKEN`` (``xoxb-…``) needs, under *OAuth & Permissions → Bot Token
Scopes*:

* ``channels:read``  — find the public channels that already exist
* ``channels:manage`` — create public channels, set purpose/topic
  (this is the scope Slack's UI describes as managing conversations)
* ``channels:join``  — add the bot itself to a channel it did not create
* ``chat:write``     — post the daily messages (used by the notifier, not here)
* ``groups:read`` + ``groups:write`` — ONLY if you keep the private channels
  (the six advisors that handle personal or operational data default to
  private; pass ``--all-public`` to opt out)

After adding scopes you must REINSTALL the app to the workspace, or the token
keeps its old permissions. When a call fails for a missing scope this script
prints the exact scope Slack asked for.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ._common import http_post
from .channel_config import ADVISOR_KEYS, MAIN_CHANNEL_ENV, advisor_channel_env

BOT_TOKEN_ENV = "SLACK_BOT_TOKEN"
API_BASE = "https://slack.com/api/"

#: Default env file the ``--write-env`` flag updates.
DEFAULT_ENV_FILE = ".env"

#: Slack rejects channel names longer than this.
MAX_CHANNEL_NAME = 80
#: Slack truncates purposes/topics past this.
MAX_PURPOSE = 250


@dataclass(frozen=True)
class ChannelSpec:
    """One channel this project wants to exist."""

    #: Environment variable that carries the resulting channel id.
    env_key: str
    #: Slack channel name (lowercase, no spaces — Slack's own rules).
    name: str
    #: Human label used in the CLI output.
    label: str
    #: Channel purpose, in Turkish: what this room is for.
    purpose: str
    #: Channel topic, in Turkish: the one-line remit.
    topic: str
    #: Private by default? True for the advisors that handle personal data.
    private: bool = False
    #: The advisor key, or "" for the main channel.
    advisor_key: str = ""


#: The fourteen channels: one main room plus one per advisor of the roster.
#:
#: The seven advisors that read the user's own mail, calendar, backlog,
#: operation data, coaching notes and the system's own internals default to
#: PRIVATE channels — the same content the
#: dashboard refuses to publish (see
#: ``ai_assistant.reports.PRIVATE_ADVISOR_KEYS``).
MAIN_CHANNEL = ChannelSpec(
    env_key=MAIN_CHANNEL_ENV,
    name="ai-asistan-genel",
    label="Ana kanal — günlük özet",
    purpose=(
        "AI Yönetici Asistanı'nın ana kanalı. Her çalıştırmada günlük özet "
        "buraya düşer: her danışman için tek satır başlık, panodaki tam rapora "
        "ve danışmanın kendi kanalına bağlantı."
    ),
    topic="🗓️ Günlük brifing özeti · tam bölümler alt kanallarda",
)

ADVISOR_CHANNELS: Tuple[ChannelSpec, ...] = (
    ChannelSpec(
        env_key=advisor_channel_env("weather"),
        name="ai-hava-durumu",
        label="Hava Durumu Meteoroloğu",
        purpose=(
            "Hava Durumu Meteoroloğu ajanının kanalı. Günün hava tahmini, "
            "giyim ve yol önerileri."
        ),
        topic="🌤️ Günlük hava tahmini ve güne hazırlık",
        advisor_key="weather",
    ),
    ChannelSpec(
        env_key=advisor_channel_env("morning_operations"),
        name="ai-sabah-operasyon",
        label="Sabah İşletme Brifingi",
        purpose=(
            "Sabah İşletme Brifingi ajanının kanalı. Günün açılışı: öncelikler, "
            "takvim yoğunluğu ve operasyonel hatırlatmalar."
        ),
        topic="📋 Güne başlarken: öncelikler ve operasyon notları",
        advisor_key="morning_operations",
    ),
    ChannelSpec(
        env_key=advisor_channel_env("communications_calendar"),
        name="ai-iletisim-takvim",
        label="İletişim & Takvim Danışmanı",
        purpose=(
            "İletişim & Takvim Danışmanı ajanının kanalı. Gelen kutusu ve "
            "takvim analizi. KİŞİSEL VERİ içerir; panoya yazılmaz, yalnızca "
            "bu kanalda durur."
        ),
        topic="📬 Gelen kutusu + takvim · 🔒 kişisel",
        private=True,
        advisor_key="communications_calendar",
    ),
    ChannelSpec(
        env_key=advisor_channel_env("career_development"),
        name="ai-kariyer-gelisim",
        label="Kariyer Gelişimi",
        purpose=(
            "Kariyer Gelişimi ajanının kanalı. İK gündemi, iş ilanları, "
            "İngilizce pratiği ve ücretsiz sertifika fırsatları."
        ),
        topic="💼 Kariyer · ilanlar · dil · sertifika",
        advisor_key="career_development",
    ),
    ChannelSpec(
        env_key=advisor_channel_env("market_intelligence"),
        name="ai-pazar-istihbarat",
        label="Pazar İstihbaratı",
        purpose=(
            "Pazar İstihbaratı ajanının kanalı. Sektör haberleri, yapay zeka "
            "gündemi, müşteri deneyimi araştırmaları ve bankacılık projeleri."
        ),
        topic="📊 Sektör · YZ gündemi · CX · bankacılık",
        advisor_key="market_intelligence",
    ),
    ChannelSpec(
        env_key=advisor_channel_env("data_analyst"),
        name="ai-veri-analisti",
        label="Veri Analisti",
        purpose=(
            "Veri Analisti ajanının kanalı. Operasyon verisini okur, "
            "göstergeleri etkiye göre sıralar ve ne anlama geldiğini yorumlar. "
            "KURUM VERİSİ içerir; panoya yazılmaz."
        ),
        topic="🔬 Operasyon verisi · göstergeler ve yorum · 🔒 kişisel",
        private=True,
        advisor_key="data_analyst",
    ),
    ChannelSpec(
        env_key=advisor_channel_env("ai_innovation"),
        name="ai-yapayzeka-inovasyon",
        label="Yapay Zeka & İnovasyon",
        purpose=(
            "Yapay Zeka & İnovasyon ajanının kanalı. Yapay zekada ustalaşma "
            "planı ve kişisel iş listesine göre üretilen fikirler. KİŞİSEL "
            "VERİ içerir; panoya yazılmaz."
        ),
        topic="🧠 YZ ustalaşma + inovasyon fikirleri · 🔒 kişisel",
        private=True,
        advisor_key="ai_innovation",
    ),
    ChannelSpec(
        env_key=advisor_channel_env("kids_development"),
        name="ai-cocuk-gelisim",
        label="Çocuk Gelişimi Danışmanı",
        purpose=(
            "Çocuk Gelişimi Danışmanı ajanının kanalı. Çocuklarla günlük "
            "etkinlik, gelişim ve birlikte vakit geçirme önerileri."
        ),
        topic="👨‍👩‍👧 Çocuklarla bugün ne yapılır",
        advisor_key="kids_development",
    ),
    ChannelSpec(
        env_key=advisor_channel_env("anka_bridge"),
        name="ai-anka-koprusu",
        label="Anka Köprüsü",
        purpose=(
            "Anka Köprüsü ajanının kanalı. Anka tarafındaki gelişmelerin "
            "günlük köprü özeti."
        ),
        topic="🕊️ Anka köprüsü günlük not",
        advisor_key="anka_bridge",
    ),
    ChannelSpec(
        env_key=advisor_channel_env("executive_coaching"),
        name="ai-yonetici-koclugu",
        label="Yönetici Koçu",
        purpose=(
            "Yönetici Koçu ajanının kanalı. Liderlik gelişimi ve hesap "
            "verebilirlik takibi: bugünün görevi, seri ve geri bildirim. "
            "KİŞİSEL VERİ içerir; panoya yazılmaz."
        ),
        topic="🧭 Liderlik gelişimi + hesap verebilirlik · 🔒 kişisel",
        private=True,
        advisor_key="executive_coaching",
    ),
    ChannelSpec(
        env_key=advisor_channel_env("work_analyst"),
        name="ai-is-analisti",
        label="İş Analisti Danışmanı",
        purpose=(
            "İş Analisti Danışmanı ajanının kanalı. Diğer ajanların çıktısını "
            "birleştirip iş yükü ve odak analizi çıkarır. KİŞİSEL VERİ içerir; "
            "panoya yazılmaz."
        ),
        topic="📈 İş yükü ve odak analizi · 🔒 kişisel",
        private=True,
        advisor_key="work_analyst",
    ),
    ChannelSpec(
        env_key=advisor_channel_env("operations_director"),
        name="ai-operasyon-direktoru",
        label="Operasyon Direktörü",
        purpose=(
            "Operasyon Direktörü ajanının kanalı. Günün tüm bulgularını "
            "sentezleyip öncelik sırasına dizilmiş karar listesi çıkarır: "
            "kadro, SLA riski, bekleyen iş ve bugün karar bekleyenler. "
            "KİŞİSEL VERİ içerir; panoya yazılmaz."
        ),
        topic="🚦 Günün kararları · sahip, son tarih, sonuç · 🔒 kişisel",
        private=True,
        advisor_key="operations_director",
    ),
    ChannelSpec(
        env_key=advisor_channel_env("sre_watchdog"),
        name="ai-teknik-gozetim",
        label="Teknik Gözetim (7/24 SRE)",
        purpose=(
            "7/24 teknik nöbetçinin kanalı. Çalıştırma tazeliği, model kotası, "
            "Slack teslimi, besleme erişimi ve durum kaydı kontrol edilir. "
            "SİSTEM İÇ BİLGİSİ içerir; panoya yazılmaz."
        ),
        topic="🛡️ Sistem sağlığı · bulgu + çözüm · 🔒 kişisel",
        private=True,
        advisor_key="sre_watchdog",
    ),
)


def covered_advisor_keys() -> Tuple[str, ...]:
    """Advisor keys this script provisions a channel for, in roster order.

    Must equal :data:`ai_assistant.integrations.channel_config.ADVISOR_KEYS` —
    a roster addition with no channel spec would quietly leave that advisor
    posting into the main channel forever. ``tests/test_slack_setup.py`` pins it.
    """
    return tuple(spec.advisor_key for spec in ADVISOR_CHANNELS)


#: Fail loudly at import time rather than silently under-provisioning.
assert covered_advisor_keys() == tuple(ADVISOR_KEYS), (
    "slack_setup.ADVISOR_CHANNELS is out of sync with channel_config.ADVISOR_KEYS"
)


def all_specs(prefix: str = "", all_public: bool = False) -> List[ChannelSpec]:
    """Every channel this project wants, main first.

    Args:
        prefix: Replaces the default ``ai-`` name prefix, e.g. ``asistan-``.
        all_public: Create the four personal-data channels as public too.
    """
    specs = [MAIN_CHANNEL, *ADVISOR_CHANNELS]
    out: List[ChannelSpec] = []
    for spec in specs:
        name = spec.name
        if prefix:
            name = prefix + spec.name[len("ai-") :] if spec.name.startswith("ai-") else prefix + spec.name
        out.append(
            ChannelSpec(
                env_key=spec.env_key,
                name=normalize_channel_name(name),
                label=spec.label,
                purpose=spec.purpose[:MAX_PURPOSE],
                topic=spec.topic[:MAX_PURPOSE],
                private=False if all_public else spec.private,
                advisor_key=spec.advisor_key,
            )
        )
    return out


_NAME_ALLOWED = re.compile(r"[^a-z0-9_-]+")
_TR_MAP = str.maketrans(
    {"ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
     "ç": "c", "Ç": "c", "ö": "o", "Ö": "o", "ü": "u", "Ü": "u"}
)


def normalize_channel_name(name: str) -> str:
    """Bend a name into something Slack will accept.

    Lowercase, ASCII-folded Turkish letters, only ``a-z0-9_-``, ≤80 chars.
    """
    folded = str(name or "").translate(_TR_MAP).lower().strip()
    folded = _NAME_ALLOWED.sub("-", folded).strip("-")
    return folded[:MAX_CHANNEL_NAME] or "ai-kanal"


# --- the Slack API seam -----------------------------------------------------


class SlackApiError(Exception):
    """A Slack ``ok: false`` response, with the Turkish explanation attached."""

    def __init__(self, method: str, code: str, explanation: str, raw: Optional[dict] = None):
        super().__init__(f"{method}: {code}")
        self.method = method
        self.code = code
        self.explanation = explanation
        self.raw = raw or {}


#: Slack error code -> what the user should actually DO about it, in Turkish.
_ERROR_HELP = {
    "invalid_auth": (
        "SLACK_BOT_TOKEN geçersiz. Slack uygulamanızın 'Bot User OAuth Token' "
        "değerini (xoxb- ile başlar) kopyalayıp .env dosyasına yazın."
    ),
    "not_authed": "SLACK_BOT_TOKEN tanımlı değil.",
    "account_inactive": "Bu token'a ait uygulama devre dışı bırakılmış.",
    "token_revoked": "Token iptal edilmiş; uygulamayı çalışma alanına yeniden kurun.",
    "ratelimited": "Slack hız sınırı. Birkaç saniye bekleyip tekrar çalıştırın.",
    "restricted_action": (
        "Çalışma alanı yöneticisi kanal oluşturmayı uygulamalara kapatmış. "
        "Kanalları elle açıp id'lerini .env'e yazabilirsiniz."
    ),
    "name_taken": "Bu isimde bir kanal zaten var (script onu yeniden kullanır).",
    "invalid_name_specials": "Kanal adında Slack'in kabul etmediği karakterler var.",
    "is_archived": "Kanal arşivlenmiş; Slack'te arşivden çıkarın.",
    "already_in_channel": "Bot zaten kanalda.",
    "method_not_supported_for_channel_type": (
        "Bot özel bir kanala kendi kendine katılamaz — kanalı Slack'te açıp "
        "'/invite @<bot>' yazın."
    ),
    "cant_invite_self": "Bot kendini davet edemez; 'conversations.join' kullanılır.",
}

#: Which scope each API method needs, so a ``missing_scope`` is actionable.
_METHOD_SCOPES = {
    "conversations.list": "channels:read (özel kanallar için ayrıca groups:read)",
    "conversations.create": "channels:manage (özel kanal için groups:write)",
    "conversations.setPurpose": "channels:manage (özel kanal için groups:write)",
    "conversations.setTopic": "channels:manage (özel kanal için groups:write)",
    "conversations.join": "channels:join",
    "auth.test": "—",
}


def explain(method: str, payload: dict) -> str:
    """Turn a Slack error payload into one actionable Turkish sentence."""
    code = str(payload.get("error") or "unknown")
    if code == "missing_scope":
        needed = payload.get("needed") or _METHOD_SCOPES.get(method, "?")
        provided = payload.get("provided") or "—"
        return (
            f"Token'da eksik yetki: '{needed}'. Slack uygulamanızda "
            f"OAuth & Permissions > Bot Token Scopes altına ekleyip uygulamayı "
            f"çalışma alanına YENİDEN KURUN. (Mevcut yetkiler: {provided})"
        )
    if code in _ERROR_HELP:
        return _ERROR_HELP[code]
    hint = _METHOD_SCOPES.get(method)
    if hint and hint != "—":
        return f"Slack '{code}' döndü. Bu çağrı '{hint}' yetkisini ister."
    return f"Slack '{code}' döndü."


class SlackApi:
    """Thin Slack Web API client. The single network seam of this module.

    Every request goes through :meth:`call`, so a test replaces exactly one
    method and the whole script runs offline.
    """

    def __init__(self, token: str):
        self.token = token

    def call(self, method: str, payload: Optional[dict] = None) -> dict:
        """POST one Web API method. Raises :class:`SlackApiError` on ``ok: false``."""
        resp = http_post(
            API_BASE + method,
            headers={"Authorization": f"Bearer {self.token}"},
            json=dict(payload or {}),
        )
        try:
            data = resp.json()
        except Exception:
            raise SlackApiError(
                method,
                f"http_{resp.status_code}",
                f"Slack JSON olmayan yanıt verdi (HTTP {resp.status_code}).",
            )
        if not data.get("ok"):
            raise SlackApiError(method, str(data.get("error") or "unknown"),
                                explain(method, data), data)
        return data


# --- provisioning -----------------------------------------------------------


@dataclass
class ChannelOutcome:
    """What happened to ONE channel in this run."""

    spec: ChannelSpec
    channel_id: str = ""
    #: One of ``created``, ``exists``, ``would-create``, ``would-reuse``, ``failed``.
    action: str = ""
    detail: str = ""
    notes: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.action != "failed"


@dataclass
class SetupResult:
    """Everything one invocation produced."""

    outcomes: List[ChannelOutcome] = field(default_factory=list)
    dry_run: bool = True
    error: str = ""

    @property
    def env_lines(self) -> List[str]:
        """The ready-to-paste ``KEY=C…`` lines, in roster order."""
        return [
            f"{o.spec.env_key}={o.channel_id}" for o in self.outcomes if o.channel_id
        ]

    @property
    def created(self) -> int:
        return sum(1 for o in self.outcomes if o.action == "created")

    @property
    def reused(self) -> int:
        return sum(1 for o in self.outcomes if o.action == "exists")

    @property
    def failed(self) -> List[ChannelOutcome]:
        return [o for o in self.outcomes if o.action == "failed"]


def list_existing_channels(api: SlackApi, include_private: bool = True) -> Dict[str, str]:
    """Every channel the bot can see, as ``name -> id``. Follows pagination.

    A missing ``groups:read`` scope costs the private half of the listing and
    nothing else: the public channels are still returned, with a note.
    """
    found: Dict[str, str] = {}
    types = "public_channel,private_channel" if include_private else "public_channel"
    cursor = ""
    for _ in range(50):  # hard stop; 50 * 200 channels is plenty
        payload = {"limit": 200, "exclude_archived": True, "types": types}
        if cursor:
            payload["cursor"] = cursor
        data = api.call("conversations.list", payload)
        for channel in data.get("channels") or []:
            name = str(channel.get("name") or "")
            cid = str(channel.get("id") or "")
            if name and cid:
                found.setdefault(name, cid)
        cursor = str((data.get("response_metadata") or {}).get("next_cursor") or "")
        if not cursor:
            break
    return found


def _ensure_membership(api: SlackApi, outcome: ChannelOutcome) -> None:
    """Put the bot in the channel. Never fatal — a note is enough."""
    try:
        api.call("conversations.join", {"channel": outcome.channel_id})
    except SlackApiError as exc:
        if exc.code == "already_in_channel":
            return
        outcome.notes.append(f"bot kanala eklenemedi ({exc.code}): {exc.explanation}")


def _describe(api: SlackApi, outcome: ChannelOutcome) -> None:
    """Set purpose + topic. Never fatal — a note is enough."""
    for method, key, value in (
        ("conversations.setPurpose", "purpose", outcome.spec.purpose),
        ("conversations.setTopic", "topic", outcome.spec.topic),
    ):
        try:
            api.call(method, {"channel": outcome.channel_id, key: value})
        except SlackApiError as exc:
            outcome.notes.append(f"{key} ayarlanamadı ({exc.code}): {exc.explanation}")


def provision_channel(
    api: SlackApi,
    spec: ChannelSpec,
    existing: Dict[str, str],
    pinned_id: str = "",
    apply: bool = False,
) -> ChannelOutcome:
    """Create-or-find ONE channel. Idempotent by name and by pinned id.

    Args:
        pinned_id: The id already in the environment for this key. When set,
            the channel is taken as given — nothing is created, nothing is
            renamed. This is what makes a re-run after a manual rename safe.
    """
    outcome = ChannelOutcome(spec=spec)

    if pinned_id:
        outcome.channel_id = pinned_id
        outcome.action = "exists" if apply else "would-reuse"
        outcome.detail = f"{spec.env_key} zaten tanımlı"
        return outcome

    known = existing.get(spec.name)
    if known:
        outcome.channel_id = known
        outcome.action = "exists" if apply else "would-reuse"
        outcome.detail = f"#{spec.name} zaten var"
        if apply:
            _ensure_membership(api, outcome)
            _describe(api, outcome)
        return outcome

    if not apply:
        outcome.action = "would-create"
        outcome.detail = f"#{spec.name} oluşturulacak" + (" (özel)" if spec.private else "")
        return outcome

    try:
        data = api.call(
            "conversations.create", {"name": spec.name, "is_private": spec.private}
        )
        outcome.channel_id = str((data.get("channel") or {}).get("id") or "")
        outcome.action = "created"
        outcome.detail = f"#{spec.name} oluşturuldu" + (" (özel)" if spec.private else "")
    except SlackApiError as exc:
        if exc.code == "name_taken":
            # Someone (or an earlier run) created it between the listing and
            # now, or it is private and we cannot see it. Look again.
            refreshed = {}
            try:
                refreshed = list_existing_channels(api)
            except SlackApiError:
                pass
            cid = refreshed.get(spec.name, "")
            if cid:
                outcome.channel_id = cid
                outcome.action = "exists"
                outcome.detail = f"#{spec.name} zaten var"
            else:
                outcome.action = "failed"
                outcome.detail = (
                    f"#{spec.name} adı kullanımda ama bot göremiyor — "
                    "kanal özel olabilir; botu kanala davet edip id'yi elle yazın."
                )
                return outcome
        else:
            outcome.action = "failed"
            outcome.detail = f"{exc.code} — {exc.explanation}"
            return outcome

    _ensure_membership(api, outcome)
    _describe(api, outcome)
    return outcome


def provision(
    api: SlackApi,
    specs: Optional[List[ChannelSpec]] = None,
    apply: bool = False,
    env: Optional[dict] = None,
) -> SetupResult:
    """Create-or-find every channel. Returns what happened, never raises.

    ``env`` defaults to :data:`os.environ` and is read ONLY to notice ids that
    are already configured, which is the first half of the idempotency: an id
    already in ``.env`` is never re-created.
    """
    specs = specs if specs is not None else all_specs()
    environment = os.environ if env is None else env
    result = SetupResult(dry_run=not apply)

    try:
        existing = list_existing_channels(api)
    except SlackApiError as exc:
        if exc.code == "missing_scope":
            result.error = exc.explanation
            return result
        # A private-listing problem must not stop the public half.
        try:
            existing = list_existing_channels(api, include_private=False)
        except SlackApiError as inner:
            result.error = inner.explanation
            return result

    for spec in specs:
        pinned = str(environment.get(spec.env_key) or "").strip()
        try:
            outcome = provision_channel(api, spec, existing, pinned_id=pinned, apply=apply)
        except SlackApiError as exc:  # pragma: no cover - provision_channel catches
            outcome = ChannelOutcome(spec=spec, action="failed", detail=exc.explanation)
        except Exception as exc:  # pragma: no cover - defensive only
            outcome = ChannelOutcome(spec=spec, action="failed", detail=str(exc))
        result.outcomes.append(outcome)
        if outcome.channel_id:
            existing.setdefault(spec.name, outcome.channel_id)

    return result


# --- .env writing -----------------------------------------------------------


def render_env_block(result: SetupResult) -> str:
    """The ready-to-paste block, with a header comment."""
    lines = [
        "# --- AI Yönetici Asistanı Slack kanalları "
        "(slack_setup tarafından üretildi) ---",
        *result.env_lines,
    ]
    return "\n".join(lines) + "\n"


def write_env_file(result: SetupResult, path: str = DEFAULT_ENV_FILE) -> List[str]:
    """Write the ids into ``path``, updating keys in place. Returns changed keys.

    Idempotent: an existing ``KEY=`` line is REPLACED, not duplicated, and a
    line that already holds the same id is left untouched.
    """
    values = {
        o.spec.env_key: o.channel_id for o in result.outcomes if o.channel_id
    }
    if not values:
        return []

    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        lines = []

    changed: List[str] = []
    seen = set()
    out: List[str] = []
    for line in lines:
        match = re.match(r"^\s*([A-Z0-9_]+)\s*=", line)
        key = match.group(1) if match else ""
        if key in values:
            seen.add(key)
            new_line = f"{key}={values[key]}"
            if new_line != line:
                changed.append(key)
            out.append(new_line)
        else:
            out.append(line)

    missing = [k for k in values if k not in seen]
    if missing:
        if out and out[-1].strip():
            out.append("")
        out.append("# --- AI Yönetici Asistanı Slack kanalları ---")
        for key in values:
            if key in missing:
                out.append(f"{key}={values[key]}")
                changed.append(key)

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out).rstrip("\n") + "\n")
    return changed


# --- CLI --------------------------------------------------------------------

_ACTION_LABEL = {
    "created": "✅ oluşturuldu",
    "exists": "↩️  mevcut",
    "would-create": "➕ oluşturulacak",
    "would-reuse": "↩️  mevcut (kullanılacak)",
    "failed": "❌ başarısız",
}


def _print_result(result: SetupResult) -> None:
    """Print the run in Turkish: what happened, then the paste-ready block."""
    print()
    print("Kanal durumu")
    print("-" * 68)
    for outcome in result.outcomes:
        label = _ACTION_LABEL.get(outcome.action, outcome.action)
        marker = "🔒" if outcome.spec.private else "  "
        print(f"{marker} #{outcome.spec.name:<26} {label:<26} {outcome.detail}")
        for note in outcome.notes:
            print(f"     ⚠️  {note}")
    print("-" * 68)

    if result.dry_run:
        print(
            "\nPROVA MODU — hiçbir şey oluşturulmadı. "
            "Gerçekten oluşturmak için:\n"
            "  python -m ai_assistant.integrations.slack_setup --apply\n"
        )
    else:
        print(
            f"\n{result.created} kanal oluşturuldu, {result.reused} kanal "
            f"yeniden kullanıldı."
        )

    if result.env_lines:
        print("\n.env dosyanıza yapıştırın:\n")
        print(render_env_block(result))

    if result.failed:
        print("Başarısız olanlar:")
        for outcome in result.failed:
            print(f"  ❌ #{outcome.spec.name}: {outcome.detail}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ai_assistant.integrations.slack_setup",
        description=(
            "AI Yönetici Asistanı için Slack kanallarını kurar: bir ana kanal "
            "ve her danışman için birer alt kanal. Varsayılan olarak PROVA "
            "modunda çalışır, hiçbir şey oluşturmaz."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Kanalları gerçekten oluştur (varsayılan: yalnızca prova).",
    )
    parser.add_argument(
        "--write-env",
        action="store_true",
        help="Kanal id'lerini doğrudan .env dosyasına yaz (--apply gerektirir).",
    )
    parser.add_argument(
        "--env-file",
        default=DEFAULT_ENV_FILE,
        help=f"Yazılacak env dosyası (varsayılan: {DEFAULT_ENV_FILE}).",
    )
    parser.add_argument(
        "--prefix",
        default="",
        help="Kanal adlarındaki 'ai-' önekini değiştir (örn. --prefix asistan-).",
    )
    parser.add_argument(
        "--all-public",
        action="store_true",
        help=(
            "Kişisel veri taşıyan dört kanalı da herkese açık oluştur "
            "(varsayılan: özel)."
        ),
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint. Returns the process exit code."""
    args = build_parser().parse_args(argv)

    token = (os.getenv(BOT_TOKEN_ENV) or "").strip()
    if not token:
        print(
            f"❌ {BOT_TOKEN_ENV} tanımlı değil.\n\n"
            "   Slack uygulamanızda OAuth & Permissions sayfasından 'Bot User "
            "OAuth Token' (xoxb- ile başlar) değerini kopyalayın ve .env "
            f"dosyasına {BOT_TOKEN_ENV}=xoxb-... olarak yazın.\n"
            "   Gerekli yetkiler: channels:read, channels:manage, "
            "channels:join, chat:write (özel kanallar için ayrıca groups:read, "
            "groups:write).",
            file=sys.stderr,
        )
        return 2

    if args.write_env and not args.apply:
        print(
            "❌ --write-env yalnızca --apply ile birlikte kullanılır: prova "
            "modunda yazılacak gerçek kanal id'si yok.",
            file=sys.stderr,
        )
        return 2

    api = SlackApi(token)
    specs = all_specs(prefix=args.prefix, all_public=args.all_public)

    print(
        f"AI Yönetici Asistanı — Slack kanal kurulumu "
        f"({'UYGULAMA' if args.apply else 'PROVA'} modu)"
    )
    print(f"{len(specs)} kanal: 1 ana kanal + {len(specs) - 1} danışman kanalı")

    try:
        whoami = api.call("auth.test")
        print(
            f"Bağlanıldı: {whoami.get('team', '?')} çalışma alanı, "
            f"bot @{whoami.get('user', '?')}"
        )
    except SlackApiError as exc:
        print(f"\n❌ Slack'e bağlanılamadı ({exc.code}).\n   {exc.explanation}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"\n❌ Slack'e bağlanılamadı: {exc}", file=sys.stderr)
        return 1

    result = provision(api, specs, apply=args.apply)
    if result.error:
        print(f"\n❌ {result.error}", file=sys.stderr)
        return 1

    _print_result(result)

    if args.write_env:
        try:
            changed = write_env_file(result, args.env_file)
        except OSError as exc:
            print(f"\n❌ {args.env_file} yazılamadı: {exc}", file=sys.stderr)
            return 1
        if changed:
            print(f"✍️  {args.env_file} güncellendi: {', '.join(changed)}")
        else:
            print(f"✍️  {args.env_file} zaten güncel.")

    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
