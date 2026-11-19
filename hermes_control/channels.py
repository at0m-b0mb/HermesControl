"""
Messaging channels — what is connected, and how you prove it.

A channel has three separate states that look alike from the outside and
fail for different reasons, so this module keeps them apart.

**Configured** means the credentials are in ``.env``. It is the easiest
thing to check and the least informative: a token can be present and wrong.

**Allowed** means an allowlist names someone. Hermes's gateway denies by
default, so a correctly configured channel with an empty allowlist connects,
receives your message, and silently ignores it — the single most confusing
failure here, because every visible sign says it is working.

**Deliverable** is the only one that is evidence. ``hermes send --list``
asks the gateway which targets it can actually reach, using the credentials
it really loaded. A channel that appears there is connected; one that does
not, whatever ``.env`` says, is not. Sending a test message through it is
the end of the proof, and that is a thing the user does, not something
inferred.

Signal is listed because ``hermes send`` accepts Signal targets, but this
Hermes exposes no ``signal`` setup command, so the page says so rather than
offering a step that does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json

#: Platforms this Hermes serves, with the keys that enable each one.
#:
#: ``key`` is Hermes's own vocabulary — the name it uses in
#: ``platform_toolsets``, in ``send -t``, and in the status line — so that
#: what this page reports can be matched against what Hermes reports.


@dataclass(frozen=True)
class Channel:
    name: str
    key: str
    #: Every secret that must be present. All of them, not any of them:
    #: Slack needs two tokens and reports a bewildering error with one.
    secrets: tuple[str, ...]
    allow_key: str
    setup: str
    how: str
    #: True when there is nothing to paste — the credential is obtained by
    #: pairing a device, so a secrets check can never say it is ready.
    paired: bool = False


CHANNELS: tuple[Channel, ...] = (
    Channel("Telegram", "telegram", ("TELEGRAM_BOT_TOKEN",),
            "TELEGRAM_ALLOWED_USERS", "",
            "Message @BotFather, /newbot, paste the token below."),
    Channel("Discord", "discord", ("DISCORD_BOT_TOKEN",),
            "DISCORD_ALLOWED_USERS", "",
            "Create an application, enable the Message Content intent, "
            "paste the bot token."),
    Channel("Slack", "slack", ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"),
            "SLACK_ALLOWED_USERS", "slack manifest",
            "Both tokens are needed: xoxb- for the bot, xapp- for socket "
            "mode. One alone fails with an unhelpful error."),
    Channel("WhatsApp", "whatsapp", (), "WHATSAPP_ALLOWED_USERS", "whatsapp",
            "Pairing, not a token: Hermes shows a QR code that you scan "
            "from WhatsApp on your phone under Linked devices.",
            paired=True),
    Channel("WhatsApp Business", "whatsapp_cloud", (),
            "WHATSAPP_ALLOWED_USERS", "whatsapp-cloud",
            "The Meta Cloud API, for a business number rather than your "
            "own phone.", paired=True),
    Channel("Microsoft Teams", "teams",
            ("TEAMS_CLIENT_ID", "TEAMS_CLIENT_SECRET", "TEAMS_TENANT_ID"),
            "TEAMS_ALLOWED_USERS", "",
            "An Azure AD app registration: client id, secret and tenant."),
    Channel("Google Chat", "google_chat",
            ("GOOGLE_CHAT_PROJECT_ID", "GOOGLE_CHAT_SUBSCRIPTION_NAME",
             "GOOGLE_CHAT_SERVICE_ACCOUNT_JSON"),
            "GOOGLE_CHAT_ALLOWED_USERS", "",
            "A GCP service account plus a Pub/Sub subscription."),
    Channel("Signal", "signal", (), "", "",
            "hermes send delivers to Signal targets, but this version "
            "exposes no signal setup command — pair it through signal-cli "
            "outside this app."),
)

#: Hermes's gateway denies anyone not on a channel's allowlist. This key
#: turns that off for every channel at once, which is almost never what
#: someone means, so the page names it rather than leaving it to be found.
ALLOW_ALL_KEY = "GATEWAY_ALLOW_ALL_USERS"


@dataclass
class ChannelState:
    channel: Channel
    configured: bool
    missing: tuple[str, ...]
    allowed: str
    deliverable: bool
    targets: tuple[str, ...] = ()
    #: "live" once the gateway can reach it, down through the stages.
    state: str = "off"
    headline: str = ""
    detail: str = ""


@dataclass
class Survey:
    states: list[ChannelState] = field(default_factory=list)
    #: Whether the target listing could be read at all. Without it every
    #: verdict here is a guess from .env, and the page must say so instead
    #: of showing a confident "not connected" that it cannot stand behind.
    listed: bool = False
    error: str = ""
    allow_all: bool = False

    @property
    def live(self) -> list[ChannelState]:
        return [s for s in self.states if s.deliverable]


def parse_targets(payload: str) -> dict[str, list[str]]:
    """Read ``hermes send --list --json``.

    Shape: ``{"platforms": {"telegram": [...], ...}}``. An empty mapping is
    a real answer — nothing is connected — and is not an error.
    """
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return {}
    # A list parses as valid JSON and has no .get, so the obvious
    # dict-shaped read crashes on it rather than returning nothing.
    if not isinstance(data, dict):
        return {}
    platforms = data.get("platforms")
    if not isinstance(platforms, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, value in platforms.items():
        if isinstance(value, list):
            out[key] = [str(v) for v in value]
        elif isinstance(value, dict):
            # Some versions nest named targets rather than listing them.
            out[key] = [str(v) for v in value.keys()]
        else:
            out[key] = []
    return out


def judge(channel: Channel, env: dict[str, str],
          targets: dict[str, list[str]], listed: bool,
          allow_all: bool) -> ChannelState:
    """Decide one channel's state, and say what to do about it."""
    missing = tuple(k for k in channel.secrets if not env.get(k, "").strip())
    configured = bool(channel.secrets) and not missing
    allowed = env.get(channel.allow_key, "").strip() if channel.allow_key else ""
    found = targets.get(channel.key, [])
    deliverable = channel.key in targets

    state = ChannelState(channel, configured, missing, allowed,
                         deliverable, tuple(found))

    if deliverable:
        # Reachable, but a message from anyone unlisted is dropped without
        # a word — which looks exactly like the bot being broken.
        if not allowed and not allow_all and channel.allow_key:
            state.state = "blocked"
            state.headline = "Connected, but nobody is allowed to use it."
            state.detail = (
                f"The gateway can reach {channel.name}, and will ignore every "
                f"message, silently, until {channel.allow_key} names someone. "
                f"Put your own account id there.")
        else:
            state.state = "live"
            state.headline = "Connected."
            state.detail = (
                f"The gateway lists "
                f"{', '.join(found) if found else 'this platform'} as a "
                f"delivery target. Send a test message to prove it end to end.")
        return state

    if not listed:
        state.state = "unknown"
        state.headline = "Could not ask the gateway."
        state.detail = ("Whether this channel is connected cannot be told "
                        "from .env alone, and the target listing failed.")
        return state

    if channel.paired:
        state.state = "off"
        state.headline = "Not paired."
        state.detail = channel.how
        return state

    if not channel.secrets:
        state.state = "off"
        state.headline = "Not set up here."
        state.detail = channel.how
        return state

    if missing:
        state.state = "off"
        state.headline = (f"Missing {', '.join(missing)}."
                          if len(missing) < len(channel.secrets)
                          else "Not configured.")
        state.detail = channel.how
        return state

    # Everything .env needs is present and the gateway still cannot reach
    # it. That is a credential that does not work, or a gateway that has
    # not been restarted since it was written — and those are worth
    # separating, because one of them is a thirty-second fix.
    state.state = "broken"
    state.headline = "Configured, but the gateway cannot reach it."
    state.detail = (
        f"{', '.join(channel.secrets)} are set, yet {channel.name} is not a "
        f"delivery target. Either the gateway has not been restarted since "
        f"they were written, or the credentials are wrong. Restart it first.")
    return state


def survey(env: dict[str, str], listing: str, listed: bool,
           error: str = "") -> Survey:
    """Judge every channel at once."""
    targets = parse_targets(listing) if listed else {}
    allow_all = env.get(ALLOW_ALL_KEY, "").strip().lower() in ("1", "true", "yes")
    out = Survey(listed=listed, error=error, allow_all=allow_all)
    out.states = [judge(c, env, targets, listed, allow_all) for c in CHANNELS]
    return out
