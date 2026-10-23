"""
Where the model comes from.

Hermes is model-agnostic: roughly two dozen named cloud providers, plus any
OpenAI-compatible server through ``provider: custom``. The names and their
required credentials are documented in the annotated config, and the catalogue
below mirrors it so the UI can say "this one needs OPENROUTER_API_KEY and you
have not set it" instead of letting a turn fail with a stack trace.

The local half is probed live rather than configured, because a local server
either answers on its port or it does not, and asking is both faster and more
honest than remembering.

One hard constraint shapes this whole module: Hermes refuses any model whose
context window is under 64,000 tokens. Ollama serves 32,768 by default, so the
single most likely first-run failure on a local setup is a model that looks
fine and is rejected. :func:`context_verdict` is what lets the UI say so
before the user spends a minute waiting for the error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

MIN_CONTEXT_WINDOW = 64_000


@dataclass(frozen=True)
class CloudProvider:
    """A named provider Hermes knows how to talk to."""

    key: str
    label: str
    credential: str = ""
    note: str = ""
    base_url: str = ""
    oauth: bool = False

    @property
    def needs_key(self) -> bool:
        return bool(self.credential) and not self.oauth


#: Mirrors the provider list in Hermes's annotated config.yaml.
CLOUD: tuple[CloudProvider, ...] = (
    CloudProvider("auto", "Auto-detect", "",
                  "Picks a provider from whatever credentials exist."),
    CloudProvider("openrouter", "OpenRouter", "OPENROUTER_API_KEY",
                  "One key, most models. The usual starting point.",
                  "https://openrouter.ai/api/v1"),
    CloudProvider("nous", "Nous Portal", "", "Sign in with OAuth: hermes auth add nous.",
                  oauth=True),
    CloudProvider("nous-api", "Nous Portal (API key)", "NOUS_API_KEY"),
    CloudProvider("anthropic", "Anthropic", "ANTHROPIC_API_KEY",
                  "Claude models, direct."),
    CloudProvider("openai-codex", "OpenAI Codex", "", "Signed in with hermes auth.",
                  oauth=True),
    CloudProvider("copilot", "GitHub Copilot", "GITHUB_TOKEN"),
    CloudProvider("gemini", "Google AI Studio", "GEMINI_API_KEY"),
    CloudProvider("zai", "z.ai / Zhipu GLM", "GLM_API_KEY"),
    CloudProvider("kimi-coding", "Kimi / Moonshot", "KIMI_API_KEY"),
    CloudProvider("minimax", "MiniMax", "MINIMAX_API_KEY"),
    CloudProvider("minimax-cn", "MiniMax China", "MINIMAX_CN_API_KEY"),
    CloudProvider("huggingface", "Hugging Face", "HF_TOKEN"),
    CloudProvider("nvidia", "NVIDIA NIM", "NVIDIA_API_KEY"),
    CloudProvider("xiaomi", "Xiaomi MiMo", "XIAOMI_API_KEY"),
    CloudProvider("arcee", "Arcee AI", "ARCEEAI_API_KEY"),
    CloudProvider("ollama-cloud", "Ollama Cloud", "OLLAMA_API_KEY"),
    CloudProvider("deepinfra", "DeepInfra", "DEEPINFRA_API_KEY"),
    CloudProvider("kilocode", "KiloCode", "KILOCODE_API_KEY"),
    CloudProvider("ai-gateway", "Vercel AI Gateway", "AI_GATEWAY_API_KEY"),
    CloudProvider("azure-foundry", "Microsoft Foundry", "",
                  "API key or Entra ID; set base_url to your resource."),
    CloudProvider("custom", "Custom endpoint", "",
                  "Any OpenAI-compatible server. Set base_url."),
)

CLOUD_BY_KEY = {p.key: p for p in CLOUD}


@dataclass
class LocalModel:
    """A model a local server is offering."""

    name: str
    server: str                  # "Ollama" | "LM Studio"
    context: int = 0             # window in tokens, 0 when unknown
    size_bytes: int = 0
    family: str = ""
    detail: str = ""
    capabilities: tuple[str, ...] = ()   # as Ollama reports them

    @property
    def supports_tools(self) -> bool | None:
        """Can the model be given tools? ``None`` when the server won't say.

        This is the second hard requirement and it is easy to miss, because a
        model without it answers ordinary chat perfectly well. Hermes is an
        agent: it sends a tool list on every request, so a model that cannot
        accept one fails the turn immediately with HTTP 400 and never produces
        a token. ``deepseek-r1`` is the popular example.
        """
        if not self.capabilities:
            return None
        return "tools" in self.capabilities

    @property
    def size_label(self) -> str:
        if not self.size_bytes:
            return ""
        return f"{self.size_bytes / 1_000_000_000:.1f} GB"


@dataclass
class LocalServer:
    """A local inference server, as found on this machine right now."""

    name: str
    provider_key: str            # what to put in model.provider
    base_url: str                # what to put in model.base_url
    reachable: bool = False
    models: list[LocalModel] = field(default_factory=list)
    error: str = ""


def _get(url: str, timeout: float = 2.5) -> Any:
    try:
        response = httpx.get(url, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def probe_ollama(host: str = "http://localhost:11434") -> LocalServer:
    """Ask Ollama what it has, and how big a window each model really offers.

    The window matters more than anything else here: ``/api/show`` reports the
    model's trained context length, which is the ceiling on what Ollama can
    serve regardless of what ``num_ctx`` asks for.
    """
    server = LocalServer("Ollama", "ollama", f"{host}/v1")
    tags = _get(f"{host}/api/tags")
    if tags is None:
        server.error = f"nothing answering on {host}"
        return server
    server.reachable = True
    for entry in (tags.get("models") or []):
        name = entry.get("name") or entry.get("model") or ""
        if not name:
            continue
        details = entry.get("details") or {}
        model = LocalModel(
            name=name, server="Ollama",
            size_bytes=int(entry.get("size") or 0),
            family=str(details.get("family") or ""),
        )
        info = _get(f"{host}/api/show?name={name}", timeout=4.0)
        if info is None:
            try:
                response = httpx.post(f"{host}/api/show", json={"name": name},
                                      timeout=6.0)
                info = response.json() if response.status_code == 200 else None
            except Exception:
                info = None
        if isinstance(info, dict):
            caps = info.get("capabilities")
            if isinstance(caps, list):
                model.capabilities = tuple(str(c) for c in caps)
            model_info = info.get("model_info") or {}
            for key, value in model_info.items():
                if key.endswith(".context_length") and isinstance(value, int):
                    model.context = value
                    break
            if not model.context:
                params = str(info.get("parameters") or "")
                for line in params.splitlines():
                    if line.strip().startswith("num_ctx"):
                        try:
                            model.context = int(line.split()[-1])
                        except ValueError:
                            pass
        server.models.append(model)
    server.models.sort(key=lambda m: (-m.context, m.name))
    return server


def probe_lmstudio(host: str = "http://127.0.0.1:1234") -> LocalServer:
    """LM Studio is first-class in Hermes and speaks the OpenAI shape."""
    server = LocalServer("LM Studio", "lmstudio", f"{host}/v1")
    data = _get(f"{host}/v1/models")
    if data is None:
        server.error = f"nothing answering on {host}"
        return server
    server.reachable = True
    for entry in (data.get("data") or []):
        name = entry.get("id") or ""
        if name:
            server.models.append(LocalModel(name=name, server="LM Studio"))
    return server


def probe_local() -> list[LocalServer]:
    return [probe_ollama(), probe_lmstudio()]


@dataclass
class Verdict:
    """Whether a model can actually be used, and what to do if not."""

    ok: bool
    state: str              # "ok" | "warn" | "error"
    headline: str
    detail: str = ""
    fix: str = ""           # a config key to set, when there is one
    fix_value: Any = None


def context_verdict(model: LocalModel | None, configured_num_ctx: Any = None) -> Verdict:
    """Judge a local model against Hermes's 64K floor.

    Three outcomes worth distinguishing. A model whose trained window is under
    the floor cannot be used at all and no setting rescues it. A model with
    headroom works, but only once Hermes is told to ask for more than Ollama's
    32,768-token default. And a model whose window we could not read is a
    maybe, which is said plainly rather than guessed at.
    """
    if model is None:
        return Verdict(False, "warn", "No model selected.")

    # Tool support first: a model without it fails instantly and absolutely,
    # whereas a small window at least fails with an explanation. Checking the
    # window first would report the lesser problem.
    if model.supports_tools is False:
        return Verdict(
            False, "error", "Cannot use tools.",
            f"{model.name} has no tool-calling support, and Hermes sends a "
            f"tool list on every request — the turn is refused with HTTP 400 "
            f"before a single token is produced. The model may chat perfectly "
            f"well elsewhere; it cannot be an agent. Reasoning-only models "
            f"such as deepseek-r1 are the common case.")

    if model.server != "Ollama":
        return Verdict(True, "ok", "Served by LM Studio.",
                       "Hermes reads the window from the server.")

    if not model.context:
        return Verdict(True, "warn", "Context window unknown.",
                       "Ollama did not report this model's window. If a turn is "
                       f"refused, set model.ollama_num_ctx to at least "
                       f"{MIN_CONTEXT_WINDOW:,}.")

    if model.context < MIN_CONTEXT_WINDOW:
        return Verdict(
            False, "error",
            f"Window too small: {model.context:,} tokens.",
            f"Hermes requires at least {MIN_CONTEXT_WINDOW:,} and refuses to "
            f"start otherwise. This model cannot be stretched past what it was "
            f"trained for, so pick a model with a larger window.")

    try:
        asked = int(configured_num_ctx) if configured_num_ctx else 0
    except (TypeError, ValueError):
        asked = 0

    if asked >= MIN_CONTEXT_WINDOW:
        unknown = " Tool support unknown." if model.supports_tools is None else ""
        return Verdict(True, "ok",
                       f"Window {model.context:,}, asking for {asked:,}.",
                       "Ready to use." + unknown)

    return Verdict(
        False, "warn",
        f"Window {model.context:,}, but Ollama will serve its default.",
        f"Ollama defaults to 32,768 tokens, under the {MIN_CONTEXT_WINDOW:,} "
        f"Hermes requires. Set model.ollama_num_ctx so Hermes asks for the "
        f"larger window this model supports.",
        fix="model.ollama_num_ctx",
        fix_value=min(model.context, 131_072))


def is_local(provider_key: str) -> bool:
    return provider_key in ("ollama", "lmstudio", "vllm", "llamacpp", "custom")
