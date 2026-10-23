"""
Talking to Ollama directly: what is installed, what can be fetched, progress.

Hermes reaches Ollama through its OpenAI-compatible endpoint, which is the
right interface for inference and the wrong one for everything else — it
cannot pull a model, delete one, or say what is resident in memory. Those live
on Ollama's native API, so this module speaks that.

One thing it deliberately does not do is pretend to browse the registry.
Ollama exposes no search or library endpoint (``/api/library`` and
``/api/search`` both 404), so an in-app "browse all models" would have to be
screen-scraped and would rot. Instead there is a short curated list of models
worth suggesting *for this purpose*, and a field that pulls any name the
registry accepts — including a Hugging Face GGUF via ``hf.co/user/repo:quant``.

The published context windows in that list are labelled as published, not
measured, and the app re-reads the real window from ``/api/show`` the moment a
model lands. That matters because the published figure is exactly the number
people get wrong about, and a wrong one here would recreate the problem this
app exists to solve.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass

import httpx

DEFAULT_HOST = "http://localhost:11434"


@dataclass(frozen=True)
class Suggestion:
    """A model worth offering, and why."""

    name: str
    published_context: int
    size_hint: str
    note: str

    @property
    def clears_floor(self) -> bool:
        from .providers import MIN_CONTEXT_WINDOW
        return self.published_context >= MIN_CONTEXT_WINDOW


#: Models worth suggesting for Hermes specifically. The selection criterion is
#: the one that actually disqualifies most candidates: a context window at or
#: above Hermes's 64,000-token floor. Figures are the publishers' own and are
#: re-measured from /api/show once a model is on disk.
SUGGESTED: tuple[Suggestion, ...] = (
    Suggestion("llama3.2:1b", 131_072, "~1.3 GB",
               "The smallest thing that works. Measured, not published: it "
               "really does serve a 131,072-token window. Good for a first "
               "run or a slow machine."),
    Suggestion("llama3.1:8b", 131_072, "~4.9 GB",
               "The safe default. Clears the floor, runs on modest hardware, "
               "and supports tool calling."),
    Suggestion("llama3.1:70b", 131_072, "~40 GB",
               "The same family with far more capability, if the machine can "
               "hold it."),
    Suggestion("mistral-nemo:12b", 128_000, "~7 GB",
               "A strong mid-size option with a large window."),
    Suggestion("command-r:35b", 131_072, "~20 GB",
               "Built for retrieval and tool use."),
    Suggestion("gemma3:12b", 128_000, "~8 GB",
               "Google's open model, long context."),
    Suggestion("qwen3:30b-a3b", 262_144, "~18 GB",
               "Mixture-of-experts: large window, only a few billion "
               "parameters active per token."),
)

#: Popular models with no tool-calling support. They chat perfectly well and
#: cannot be agents: Hermes sends a tool list on every request, so the turn is
#: refused with HTTP 400 before a token is produced. This list was learned the
#: hard way — deepseek-r1 was suggested here until it was tried.
KNOWN_NO_TOOLS: tuple[str, ...] = (
    "deepseek-r1", "deepcoder", "openthinker", "marco-o1", "qwq",
)

#: Popular models that do NOT clear the floor. Shown so the choice is informed
#: rather than discovered an hour later.
KNOWN_TOO_SMALL: tuple[tuple[str, int], ...] = (
    ("qwen2.5", 32_768),
    ("phi4", 16_384),
    ("mistral:7b", 32_768),
    ("codellama", 16_384),
)


@dataclass
class PullProgress:
    """One line of a pull, normalised."""

    status: str
    completed: int = 0
    total: int = 0
    digest: str = ""
    error: str = ""

    @property
    def fraction(self) -> float:
        if self.total <= 0:
            return 0.0
        return min(self.completed / self.total, 1.0)

    @property
    def done(self) -> bool:
        return self.status in ("success", "done")


class Ollama:
    """The native Ollama API, for the things the OpenAI shape cannot do."""

    def __init__(self, host: str = DEFAULT_HOST):
        self.host = host.rstrip("/")

    # --- queries -----------------------------------------------------------

    def version(self) -> str | None:
        try:
            response = httpx.get(f"{self.host}/api/version", timeout=4)
            response.raise_for_status()
            return str(response.json().get("version") or "")
        except Exception:
            return None

    @property
    def reachable(self) -> bool:
        return self.version() is not None

    def installed(self) -> list[str]:
        try:
            response = httpx.get(f"{self.host}/api/tags", timeout=6)
            response.raise_for_status()
            return [m.get("name") or m.get("model") or ""
                    for m in (response.json().get("models") or [])]
        except Exception:
            return []

    def resident(self) -> list[str]:
        """Models currently loaded in memory — what a turn will be fast on."""
        try:
            response = httpx.get(f"{self.host}/api/ps", timeout=4)
            response.raise_for_status()
            return [m.get("name") or m.get("model") or ""
                    for m in (response.json().get("models") or [])]
        except Exception:
            return []

    def context_window(self, name: str) -> int:
        """The model's real trained window, read back from Ollama."""
        try:
            response = httpx.post(f"{self.host}/api/show",
                                  json={"model": name}, timeout=10)
            response.raise_for_status()
            info = response.json().get("model_info") or {}
        except Exception:
            return 0
        for key, value in info.items():
            if key.endswith(".context_length") and isinstance(value, int):
                return value
        return 0

    # --- mutations ---------------------------------------------------------

    def pull(self, name: str, timeout: float = 3600.0) -> Iterator[PullProgress]:
        """Download a model, yielding progress as Ollama reports it.

        Ollama streams newline-delimited JSON. Layers are reported
        individually, so ``completed``/``total`` are per-layer rather than for
        the whole download — the UI shows the current layer and counts the
        layers rather than inventing a single percentage that would jump
        backwards.
        """
        try:
            with httpx.stream("POST", f"{self.host}/api/pull",
                              json={"model": name, "stream": True},
                              timeout=httpx.Timeout(timeout, connect=10.0)) as response:
                if response.status_code != 200:
                    body = response.read().decode("utf-8", "replace")[:300]
                    yield PullProgress("failed", error=f"HTTP {response.status_code}: {body}")
                    return
                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if payload.get("error"):
                        yield PullProgress("failed", error=str(payload["error"]))
                        return
                    yield PullProgress(
                        status=str(payload.get("status") or ""),
                        completed=int(payload.get("completed") or 0),
                        total=int(payload.get("total") or 0),
                        digest=str(payload.get("digest") or ""),
                    )
        except Exception as exc:
            yield PullProgress("failed", error=f"{type(exc).__name__}: {exc}")

    def delete(self, name: str) -> tuple[bool, str]:
        try:
            response = httpx.request("DELETE", f"{self.host}/api/delete",
                                     json={"model": name}, timeout=30)
            if response.status_code in (200, 204):
                return True, ""
            return False, f"HTTP {response.status_code}: {response.text[:200]}"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"


def install_hint() -> str:
    """How to get Ollama itself, per platform."""
    from . import platforms
    if platforms.IS_MAC:
        return "brew install ollama  (or download from ollama.com)"
    if platforms.IS_WINDOWS:
        return "winget install Ollama.Ollama  (or download from ollama.com)"
    return "curl -fsSL https://ollama.com/install.sh | sh"
