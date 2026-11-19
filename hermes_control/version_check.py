"""
Is this app itself current?

Deliberately tiny, deliberately quiet, and deliberately not fatal. This
is the only thing in the app that talks to a server which is not the
user's own machine, so it asks one unauthenticated public endpoint for
one tag name, sends nothing about the user or the install, and treats
every failure as "could not tell" rather than as "up to date".

That last distinction is the whole point. A check that fails closed —
reporting current because it could not reach the network — is worse
than no check, because it answers a question it did not actually ask.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

#: The releases endpoint for this project. No token, no parameters, and
#: nothing identifying in the request beyond a generic client name.
RELEASES_URL = ("https://api.github.com/repos/at0m-b0mb/HermesControl"
                "/releases/latest")
USER_AGENT = "HermesControl-update-check"


def latest_release(timeout: float = 6.0,
                   url: str = RELEASES_URL) -> tuple[str, str]:
    """Return ``(tag, error)``. One of them is always empty."""
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json",
                      "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        return "", str(exc)
    tag = payload.get("tag_name") if isinstance(payload, dict) else None
    if not isinstance(tag, str) or not tag.strip():
        return "", "the release list had no tag name in it"
    return tag.strip().lstrip("vV"), ""
