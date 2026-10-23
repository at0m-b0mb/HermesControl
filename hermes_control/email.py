"""
The email gateway: letting people write to the agent and get a reply.

Hermes ships a built-in email platform (``plugins/platforms/email``) that
polls an IMAP mailbox and answers over SMTP. It is configured entirely through
``EMAIL_*`` environment variables, which ``hermes config set`` routes into
``.env`` because they are UPPER_SNAKE — so the password never lands in
``config.yaml``.

Two things make this worth a module rather than a form.

The first is that almost nobody can use their ordinary password any more.
Gmail, Outlook and iCloud all require an **app password** when a client signs
in with a password at all, and the error they return for the account password
is an unhelpful generic authentication failure. Saying so before the attempt
saves a long and confusing detour.

The second is that "it does not work" has several very different causes — DNS,
a blocked port, TLS, a wrong password, IMAP disabled on the account — and they
are distinguishable if you test in stages instead of all at once. That is what
:func:`check` does, and it reports the first stage that failed rather than one
flat failure.
"""

from __future__ import annotations

import imaplib
import smtplib
import socket
import ssl
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Provider:
    """Host settings for a mail provider, so nobody has to look them up."""

    label: str
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    note: str = ""

    @property
    def needs_app_password(self) -> bool:
        return bool(self.note)


PROVIDERS: tuple[Provider, ...] = (
    Provider("Gmail", "imap.gmail.com", 993, "smtp.gmail.com", 587,
             "Google refuses ordinary passwords. Turn on 2-Step Verification, "
             "then create an App Password and use that here."),
    Provider("Outlook / Microsoft 365", "outlook.office365.com", 993,
             "smtp.office365.com", 587,
             "Microsoft requires an app password once 2FA is on, and many "
             "work tenants disable password sign-in for IMAP entirely."),
    Provider("iCloud", "imap.mail.me.com", 993, "smtp.mail.me.com", 587,
             "Apple requires an app-specific password generated at "
             "appleid.apple.com."),
    Provider("Yahoo", "imap.mail.yahoo.com", 993, "smtp.mail.yahoo.com", 587,
             "Yahoo requires a generated app password."),
    Provider("Fastmail", "imap.fastmail.com", 993, "smtp.fastmail.com", 587,
             "Fastmail requires an app password scoped to mail."),
    Provider("Custom", "", 993, "", 587),
)

#: The variables the plugin reads. Only the first three are required.
REQUIRED = ("EMAIL_ADDRESS", "EMAIL_PASSWORD", "EMAIL_SMTP_HOST")
OPTIONAL = ("EMAIL_SMTP_PORT", "EMAIL_IMAP_HOST", "EMAIL_IMAP_PORT",
            "EMAIL_ALLOWED_USERS", "EMAIL_HOME_ADDRESS")
SECRET = ("EMAIL_PASSWORD",)


def provider_for(label: str) -> Provider | None:
    for provider in PROVIDERS:
        if provider.label == label:
            return provider
    return None


def guess_provider(address: str) -> Provider | None:
    """Pick host settings from the address, so the form fills itself."""
    domain = address.partition("@")[2].lower().strip()
    if not domain:
        return None
    table = {
        "gmail.com": "Gmail", "googlemail.com": "Gmail",
        "outlook.com": "Outlook / Microsoft 365",
        "hotmail.com": "Outlook / Microsoft 365",
        "live.com": "Outlook / Microsoft 365",
        "icloud.com": "iCloud", "me.com": "iCloud", "mac.com": "iCloud",
        "yahoo.com": "Yahoo", "fastmail.com": "Fastmail",
    }
    return provider_for(table.get(domain, ""))


@dataclass
class Stage:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class CheckResult:
    """The outcome of testing a mailbox, stage by stage."""

    stages: list[Stage] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.stages) and all(s.ok for s in self.stages)

    @property
    def first_failure(self) -> Stage | None:
        return next((s for s in self.stages if not s.ok), None)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.stages.append(Stage(name, ok, detail))


def _reachable(host: str, port: int, timeout: float = 8.0) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, ""
    except socket.gaierror as exc:
        return False, f"the name {host} does not resolve ({exc})"
    except TimeoutError:
        return False, (f"no answer from {host}:{port} within {timeout:.0f}s — "
                       f"the port may be blocked by a firewall")
    except OSError as exc:
        return False, f"{host}:{port} refused the connection ({exc})"


def check(address: str, password: str, imap_host: str, imap_port: int,
          smtp_host: str, smtp_port: int) -> CheckResult:
    """Test a mailbox in stages, so a failure says which part failed.

    The password is used here and nowhere else: it is never logged, never put
    in an error string, and never written anywhere but ``.env`` through
    Hermes's own config command.
    """
    result = CheckResult()

    if imap_host:
        ok, detail = _reachable(imap_host, imap_port)
        result.add(f"Reach {imap_host}:{imap_port}", ok, detail)
        if ok:
            try:
                context = ssl.create_default_context()
                with imaplib.IMAP4_SSL(imap_host, imap_port,
                                       ssl_context=context, timeout=15) as imap:
                    result.add("IMAP TLS", True)
                    try:
                        imap.login(address, password)
                        result.add("IMAP sign-in", True)
                        status, _ = imap.select("INBOX", readonly=True)
                        result.add("Open INBOX", status == "OK",
                                   "" if status == "OK" else
                                   "signed in, but the INBOX could not be opened")
                    except imaplib.IMAP4.error as exc:
                        result.add("IMAP sign-in", False, _auth_hint(str(exc)))
            except ssl.SSLError as exc:
                result.add("IMAP TLS", False, f"TLS failed: {exc}")
            except (OSError, imaplib.IMAP4.error) as exc:
                result.add("IMAP TLS", False, str(exc))

    if smtp_host:
        ok, detail = _reachable(smtp_host, smtp_port)
        result.add(f"Reach {smtp_host}:{smtp_port}", ok, detail)
        if ok:
            try:
                if smtp_port == 465:
                    server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)
                else:
                    server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
                with server:
                    server.ehlo()
                    if smtp_port != 465:
                        server.starttls(context=ssl.create_default_context())
                        server.ehlo()
                    result.add("SMTP TLS", True)
                    try:
                        server.login(address, password)
                        result.add("SMTP sign-in", True)
                    except smtplib.SMTPAuthenticationError as exc:
                        result.add("SMTP sign-in", False,
                                   _auth_hint(exc.smtp_error.decode("utf-8", "replace")
                                              if isinstance(exc.smtp_error, bytes)
                                              else str(exc.smtp_error)))
            except (OSError, smtplib.SMTPException, ssl.SSLError) as exc:
                result.add("SMTP TLS", False, str(exc))

    if not result.stages:
        result.add("Configuration", False,
                   "No IMAP or SMTP host was given, so there was nothing to test.")
    return result


def _auth_hint(message: str) -> str:
    """Turn a provider's generic refusal into the thing that is usually wrong."""
    lowered = message.lower()
    if "application-specific" in lowered or "app password" in lowered:
        return "the server wants an app password, not the account password"
    if "invalid credentials" in lowered or "authenticationfailed" in lowered \
            or "username and password not accepted" in lowered:
        return ("sign-in refused. With Gmail, Outlook, iCloud or Yahoo this "
                "almost always means an app password is needed rather than "
                "the account password")
    if "disabled" in lowered or "not enabled" in lowered:
        return "the account has IMAP/SMTP access switched off"
    return message.strip()[:200] or "sign-in refused"
