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
from pathlib import Path
from typing import Any
import functools
import os
import subprocess

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
    capabilities: tuple[str, ...] = ()   # as the server reports them
    #: LM Studio loads a model at a chosen context length that is usually far
    #: below what it supports. The *loaded* value is what the server will
    #: actually serve, so it is what Hermes's floor must be judged against —
    #: a model advertising 262,144 and loaded at 8,192 is refused.
    loaded_context: int = 0
    vision: bool = False
    loaded: bool = True

    @property
    def effective_context(self) -> int:
        """The window the server will actually serve, not the one advertised."""
        return self.loaded_context or self.context

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
        # Ollama says "tools"; LM Studio says "tool_use".
        return any(c in ("tools", "tool_use") for c in self.capabilities)

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

    @property
    def is_ollama(self) -> bool:
        return self.name == "Ollama"


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
    # provider is "custom", not "ollama". Hermes accepts "ollama" as an alias
    # at run time -- status resolves it to custom and inference works -- but
    # `hermes doctor` validates the raw config value against its canonical
    # list and reports "model.provider 'ollama' is unknown" as a problem the
    # user then goes hunting for. Nothing is lost by writing the canonical
    # value: ollama_num_ctx is read straight from model config and is not
    # gated on the provider, and Ollama itself is detected from base_url
    # (agent/model_metadata.py::_is_ollama_server).
    server = LocalServer("Ollama", "custom", f"{host}/v1")
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


#: LM Studio ships a CLI alongside the app and does not put it on PATH.
LMS_CLI = Path.home() / ".lmstudio" / "bin" / "lms"


def lms_available() -> bool:
    """Whether LM Studio's own CLI is on this machine."""
    return LMS_CLI.is_file() and os.access(LMS_CLI, os.X_OK)


#: What to ask LM Studio for when reloading. Deliberately the floor and not
#: the model's maximum: a window the machine cannot hold reports a clean
#: load and then kills the server, and the floor is the smallest value that
#: makes the model usable at all. Someone who wants more can set it in LM
#: Studio, where the memory cost is shown before committing to it.
RELOAD_CONTEXT = MIN_CONTEXT_WINDOW


def lms_server_start(timeout: int = 90) -> tuple[bool, str]:
    """Start LM Studio's local server.

    Worth having a button for because the server stops more often than
    anything else here: quitting the app stops it, and it does not come
    back when the app is reopened. Until now the Models page could only
    report "nothing answering on this port" and leave the user to find
    the CLI — a diagnosis without the one-line fix beside it.

    Starting the server does not load a model; that is a separate step,
    which is why the caller usually follows with :func:`lms_reload`.
    """
    if not lms_available():
        return False, (f"LM Studio's CLI is not at {LMS_CLI}. Open LM "
                       f"Studio once to install it, then start its server "
                       f"from the app's Developer tab.")
    try:
        done = subprocess.run([str(LMS_CLI), "server", "start"],
                              capture_output=True, text=True,
                              timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip().splitlines()
        return False, (detail[-1] if detail else
                       f"lms server start exited {done.returncode}.")
    # Confirm rather than trust: the command can succeed while the port
    # is still coming up, and a page that says "started" over a server
    # that is not answering yet is the same lie as before.
    server = probe_lmstudio()
    if not server.reachable:
        return False, ("The server reported that it started, but nothing "
                       "is answering on the port yet. Rescan in a moment.")
    loaded = [m for m in server.models if m.loaded]
    return True, ("LM Studio is answering. "
                  + (f"{loaded[0].name} is loaded at "
                     f"{loaded[0].effective_context:,} tokens."
                     if loaded else
                     "No model is loaded yet — use a model below."))


def lms_reload(model: str, context: int = RELOAD_CONTEXT,
               timeout: int = 300) -> tuple[bool, str]:
    """Reload a model in LM Studio at a context length Hermes will accept.

    This exists because the single most common LM Studio failure is not a
    missing model or an unreachable server: it is a model loaded at the
    app's default context length, far below both what the model supports
    and what Hermes requires. The server reports it as present and healthy,
    Hermes refuses every turn, and nothing in either interface connects the
    two. The fix is a reload, which is a loading setting rather than a
    property of the model — so it can be done from here.

    The existing instance is unloaded first. Two copies of a large model
    will not fit in memory, and ``lms load`` on an already-loaded model
    adds a second instance rather than replacing the first.
    """
    if not lms_available():
        return False, (f"LM Studio's CLI is not at {LMS_CLI}. Open LM Studio "
                       f"once to install it, or reload the model in the app.")
    run = functools.partial(subprocess.run, capture_output=True, text=True,
                            timeout=timeout)
    # Unload everything, not just this model. On a 24 GB machine a 14 GB
    # model that LM Studio loaded on demand leaves no room for the one
    # actually configured, and the load fails with "insufficient system
    # resources" — which reads as the small model being too big. An
    # unload failure is not fatal: there may be nothing loaded.
    run([str(LMS_CLI), "unload", "--all"], check=False)
    # No --ttl at all, deliberately.
    #
    # The hourly self-break is real but it belongs to LM Studio's
    # *just-in-time* loading: a model it loads on demand gets a one-hour
    # TTL and comes back at the app's default context, which is under
    # Hermes's floor. A model loaded from the CLI gets no TTL and stays.
    # So the fix is to load it here, not to pass a TTL — and `--ttl 0`
    # is rejected outright ("must be at least 1"), which silently sent
    # an earlier version of this down its own fallback path.
    done = run([str(LMS_CLI), "load", model, "-c", str(context),
                "--gpu", "max", "-y"], check=False)
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip().splitlines()
        return False, (detail[-1] if detail else
                       f"lms load exited {done.returncode}.")

    # Do not trust the exit code. A context length the machine cannot hold
    # can report a successful load and then take the whole server down a
    # moment later — asking for 131,072 on a model that was happy at 65,536
    # did exactly that here, leaving "reloaded successfully" on screen and
    # nothing listening on the port. The only honest confirmation is to ask
    # the server again.
    server = probe_lmstudio()
    if not server.reachable:
        return False, (
            f"{model} reported a successful load at {context:,} tokens and "
            f"then the server stopped answering — almost always a context "
            f"length this machine cannot hold. Start LM Studio's server "
            f"again and reload at a smaller window.")
    live = next((m for m in server.models if m.name == model), None)
    if live is None or not live.loaded:
        return False, (
            f"{model} loaded without error but the server does not list it "
            f"as loaded. Check LM Studio directly.")
    if live.effective_context < MIN_CONTEXT_WINDOW:
        return False, (
            f"{model} came back at {live.effective_context:,} tokens, still "
            f"under the {MIN_CONTEXT_WINDOW:,} Hermes requires.")
    return True, f"{model} reloaded at {live.effective_context:,} tokens."


def probe_lmstudio(host: str = "http://127.0.0.1:1234") -> LocalServer:
    """LM Studio is first-class in Hermes and speaks the OpenAI shape.

    Asked through its own REST API rather than ``/v1/models``, because the
    OpenAI-compatible endpoint returns nothing but ids. ``/api/v0/models``
    reports the three facts that decide whether a model can be used at all:
    whether it does tool calling, whether it takes images, and — the one that
    actually bites — the context length it is *currently loaded at*, which is
    usually a small fraction of what it supports and is set in LM Studio when
    the model is loaded.
    """
    server = LocalServer("LM Studio", "lmstudio", f"{host}/v1")
    rich = _get(f"{host}/api/v0/models", timeout=4.0)
    data = rich if rich is not None else _get(f"{host}/v1/models")
    if data is None:
        server.error = f"nothing answering on {host}"
        return server
    server.reachable = True
    for entry in (data.get("data") or []):
        name = entry.get("id") or ""
        if not name:
            continue
        kind = str(entry.get("type") or "")
        if kind == "embeddings":
            continue          # not something a conversation can run on
        caps = entry.get("capabilities")
        model = LocalModel(
            name=name, server="LM Studio",
            context=int(entry.get("max_context_length") or 0),
            loaded_context=int(entry.get("loaded_context_length") or 0),
            capabilities=tuple(str(c) for c in caps) if isinstance(caps, list) else (),
            vision=kind == "vlm",
            loaded=str(entry.get("state") or "loaded") == "loaded",
            family=str(entry.get("arch") or ""),
            detail=str(entry.get("quantization") or ""),
        )
        server.models.append(model)
    server.models.sort(key=lambda m: (not m.loaded, -m.effective_context, m.name))
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


def serving_mismatch(server: "LocalServer", configured: str) -> str:
    """Why the configured model is not the one being served, if so.

    LM Studio loads a model *on demand* when something asks for one that
    is not loaded, and on a machine without room it can end up holding a
    different, larger model instead — here a 14 GB one on a 24 GB
    machine, at its own default 8,192-token window. Hermes then sends a
    prompt that does not fit and the server answers HTTP 400, which
    surfaces as "LM Studio rejected this request as malformed": true,
    and no help at all in finding the cause.

    Returns an empty string when there is nothing wrong.
    """
    if not configured or not server.reachable or server.is_ollama:
        return ""
    loaded = [m for m in server.models if m.loaded]
    if not loaded:
        return (f"Nothing is loaded in LM Studio, so the first turn will "
                f"make it load {configured} on demand — at its own default "
                f"window, which is under the {MIN_CONTEXT_WINDOW:,} Hermes "
                f"needs. Load it here first.")
    names = [m.name for m in loaded]
    if configured in names:
        return ""
    return (f"LM Studio is serving {', '.join(names)}, not {configured}, "
            f"which is what Hermes will ask for. Loading another model on "
            f"demand can leave no room for this one, and a turn that does "
            f"not fit comes back as a malformed request rather than as an "
            f"out-of-memory error.")


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
        window = model.effective_context
        if not model.loaded:
            return Verdict(
                True, "warn", "Not loaded in LM Studio.",
                f"{model.name} supports {model.context:,} tokens but is not "
                f"loaded, so its served window is unknown. Load it in LM "
                f"Studio with a context length of at least "
                f"{MIN_CONTEXT_WINDOW:,}.")
        if window and window < MIN_CONTEXT_WINDOW:
            return Verdict(
                False, "error",
                f"Loaded at only {window:,} tokens.",
                f"{model.name} supports {model.context:,}, but LM Studio has "
                f"it loaded at {window:,} — below the {MIN_CONTEXT_WINDOW:,} "
                f"Hermes requires, so every turn is refused. Reload it in LM "
                f"Studio and raise the context length; this is a loading "
                f"setting, not a limit of the model.")
        # Hermes sizes its conversation compressor from ollama_num_ctx
        # whatever the provider is — the log line says "Ollama num_ctx"
        # while talking to LM Studio. If that disagrees with the window
        # the server is really serving, compaction is scheduled in the
        # wrong place: too high and a long conversation grows past what
        # the server accepts and is silently truncated, which looks like
        # the model forgetting rather than like a misconfiguration.
        try:
            configured = int(configured_num_ctx or 0)
        except (TypeError, ValueError):
            configured = 0
        if window and configured and configured != window:
            return Verdict(
                False, "warn",
                f"Hermes thinks the window is {configured:,}.",
                f"LM Studio is serving {window:,}. Hermes sizes its "
                f"conversation compressor from model.ollama_num_ctx, so it "
                f"will compact in the wrong place — too late if that number "
                f"is higher, and a long conversation then grows past what "
                f"the server can take and loses its earlier turns without "
                f"saying so.",
                fix="model.ollama_num_ctx", fix_value=window)
        return Verdict(True, "ok", f"Loaded at {window:,} tokens.",
                       "Served by LM Studio.")

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


#: Provider values Hermes's own doctor accepts for a local server. "ollama",
#: "vllm" and "llamacpp" work as aliases but are rejected by `hermes doctor`,
#: so they are recognised here and never written.
CANONICAL_LOCAL = ("custom", "lmstudio")
LOCAL_ALIASES = ("ollama", "vllm", "llamacpp")


#: Above this, a model's KV cache is large enough that asking for a big
#: context window starts to compete with the weights for memory.
LARGE_MODEL_BYTES = 12_000_000_000

#: A comfortable default window. Hermes needs 64,000; asking for much more
#: costs memory in proportion to the model's size and buys nothing until a
#: conversation is actually that long.
DEFAULT_NUM_CTX = 65_536
GENEROUS_NUM_CTX = 131_072


def suggested_num_ctx(model: LocalModel) -> int:
    """How large a window to ask Ollama for when selecting this model.

    Asking for the largest window the model supports is the obvious choice and
    the wrong one. ``num_ctx`` sizes the KV cache, which is allocated up front
    and scales with the model: a 30B asked for 131,072 tokens made the Ollama
    runner die mid-turn with "model runner has unexpectedly stopped ...
    resource limitations", and Hermes then retried into the same wall.

    So the floor is the default and headroom is opt-in. A small model gets a
    generous window because it can afford one; anything large gets what Hermes
    requires and no more, and the Config page can raise it.
    """
    window = model.context or MIN_CONTEXT_WINDOW
    if model.size_bytes and model.size_bytes >= LARGE_MODEL_BYTES:
        return min(max(DEFAULT_NUM_CTX, MIN_CONTEXT_WINDOW), window)
    return min(max(GENEROUS_NUM_CTX, MIN_CONTEXT_WINDOW), window)


def is_local(provider_key: str) -> bool:
    return provider_key in CANONICAL_LOCAL + LOCAL_ALIASES


def canonical_provider(provider_key: str) -> str:
    """The value to write. Aliases become `custom` so doctor stays clean."""
    return "custom" if provider_key in LOCAL_ALIASES else provider_key
