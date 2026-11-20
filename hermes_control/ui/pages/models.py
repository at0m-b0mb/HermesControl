"""
Models — which brain Hermes is using, local or hosted.

The page is organised around the one distinction that actually changes how you
work: whether inference happens on this machine or over the network. Local
servers are probed live; hosted providers are listed with the credential each
needs and whether it is present.

It also enforces Hermes's least obvious requirement. Hermes refuses a context
window under 64,000 tokens, Ollama serves 32,768 unless told otherwise, and
plenty of popular local models were never trained past 40K. Left alone that
produces a turn that dies with a stack trace a minute in. Here it produces a
verdict next to the model, before it is chosen, with a one-click fix when a
fix exists.
"""

from __future__ import annotations

from PySide6.QtWidgets import (QHBoxLayout, QLineEdit, QProgressBar,
                               QTextEdit,
                               QVBoxLayout, QWidget)

from ... import auth as hauth
from ... import providers
from ...ollama import KNOWN_TOO_SMALL, SUGGESTED, Ollama, PullProgress
from .. import widgets as w
from ..shell import Page


def _read_auth(hermes):
    """``hermes auth list`` as (payload, ok, error), ready for ``auth.pool``."""
    ok, payload = hermes.auth_list()
    return (payload if ok else "", ok, "" if ok else payload)


class ModelsPage(Page):
    title = "Models"
    group = "Runtime"

    def __init__(self, app, parent: QWidget | None = None):
        super().__init__(app, parent)
        self._servers: list[providers.LocalServer] = []
        self._ollama = Ollama()
        self._pull_job = None
        self._pulling = ""
        self._reloading = ""
        self._signing_in = ""
        self._sign_in_text = ""
        self._starting = False
        self._pull_layers: set[str] = set()

        body = QWidget()
        layout = QVBoxLayout(body)
        pad = 32
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(20)

        header = w.PageHeader(
            "Runtime", "Models",
            "Hermes will talk to any OpenAI-compatible endpoint, on this "
            "machine or hosted. Pick one here and it becomes the default.")
        header.add_action(w.button("Rescan", "", self.refresh))
        layout.addWidget(header)

        # --- in use --------------------------------------------------------
        self._current = w.Card("In use", accent=True)
        self._current_kv = w.KeyValue()
        self._current.add(self._current_kv)
        self._verdict_dot = w.StatusDot("idle", "")
        self._current.add(self._verdict_dot)
        self._verdict_detail = w.label("", "Faint", wrap=True)
        self._current.add(self._verdict_detail)
        self._fix_row = w.row()
        self._current.add(self._fix_row)
        layout.addWidget(self._current)

        # --- local ---------------------------------------------------------
        self._local_card = w.Card("On this machine")
        self._local_box = QVBoxLayout()
        self._local_box.setSpacing(4)
        self._local_card.add_layout(self._local_box)
        layout.addWidget(self._local_card)

        # --- hosted --------------------------------------------------------
        # --- library --------------------------------------------------------
        self._library = w.Card("Get a model")
        self._library.add(w.label(
            "Ollama publishes no search API, so this is a short list chosen "
            "for one reason: every entry clears the "
            f"{providers.MIN_CONTEXT_WINDOW:,}-token window Hermes requires. "
            "The figures are the publishers' own; the real window is measured "
            "from the model itself once it lands.", "Faint", wrap=True))
        self._library_box = QVBoxLayout()
        self._library_box.setSpacing(4)
        self._library.add_layout(self._library_box)

        self._pull_name = QLineEdit()
        self._pull_name.setPlaceholderText(
            "Or pull any name the registry accepts, such as llama3.3:70b "
            "or hf.co/user/repo:Q4_K_M")
        self._pull_button = w.button("Download", "", self._pull_typed)
        self._library.add(w.row(self._pull_name, self._pull_button,
                                stretch_last=False))

        self._pull_bar = QProgressBar()
        self._pull_bar.setVisible(False)
        self._library.add(self._pull_bar)
        self._pull_status = w.label("", "Faint", wrap=True)
        self._library.add(self._pull_status)
        self._library.add(w.label(
            "Popular models that are too small for Hermes: "
            + ", ".join(f"{n} ({c:,})" for n, c in KNOWN_TOO_SMALL),
            "Faint", wrap=True))
        self._library.add(w.label(
            "A window and tool support are necessary, not sufficient — a "
            "model can have both and still lose the thread once the work has "
            "steps. Seven models tried through Ollama all failed a two-step "
            "job; gemma-4-e4b through LM Studio passed it in 13 seconds and "
            "reads images too, so the serving stack matters as much as the "
            "model. Run tools/model_bench.py before trusting any of them "
            "with real work.", "Faint", wrap=True))
        layout.addWidget(self._library)

        # --- hosted ---------------------------------------------------------
        self._cloud_card = w.Card("Hosted")
        self._cloud_card.add(w.label(
            "A hosted provider needs its credential in .env. Setting one here "
            "writes it through Hermes, which keeps secrets out of config.yaml.",
            "Faint", wrap=True))
        self._cloud_box = QVBoxLayout()
        self._cloud_box.setSpacing(4)
        self._cloud_card.add_layout(self._cloud_box)
        layout.addWidget(self._cloud_card)

        # A device-code flow prints a URL and a short code and then blocks.
        # Both have to be on screen while the person uses them, so this card
        # appears for the duration of a sign-in and stays out of the way
        # otherwise.
        self._sign_in_card = w.Card("Sign in", accent=True)
        self._sign_in_title = w.label("", "body_bold")
        self._sign_in_card.add(self._sign_in_title)
        self._sign_in_code = w.label("", "Mono", wrap=True)
        self._sign_in_card.add(self._sign_in_code)
        self._sign_in_log = QTextEdit()
        self._sign_in_log.setReadOnly(True)
        self._sign_in_log.setMinimumHeight(140)
        self._sign_in_log.setProperty("role", "Mono")
        self._sign_in_card.add(self._sign_in_log)
        self._sign_in_card.add(w.row(
            w.button("Cancel", "Danger", self._cancel_sign_in),
            w.button("Hide", "Quiet",
                     lambda: self._sign_in_card.setVisible(False)),
            w.spacer()))
        self._sign_in_card.add(w.label(
            "The code and the password are yours to enter — this app opens "
            "the flow and reports what it says, and never handles either.",
            "Faint", wrap=True))
        self._sign_in_card.setVisible(False)
        layout.addWidget(self._sign_in_card)

        self._message = w.label("", "Faint", wrap=True)
        layout.addWidget(self._message)
        layout.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(w.scroller(body))

    # --- data ---------------------------------------------------------------

    def refresh(self) -> None:
        self._message.setText("Probing local servers…")
        self.jobs.run(self._gather, self._show, self._fail)

    def _gather(self) -> dict:
        hermes = self.hermes
        return {
            "servers": providers.probe_local(),
            "provider": hermes.config_value("model.provider") or "",
            "model": hermes.config_value("model.default") or "",
            "base_url": hermes.config_value("model.base_url") or "",
            "num_ctx": hermes.config_value("model.ollama_num_ctx"),
            "context_length": hermes.config_value("model.context_length"),
            "secrets": set(hermes.read_env().keys()),
            "auth": hauth.pool(*_read_auth(hermes)),
        }

    def _show(self, data: dict) -> None:
        self._servers = data["servers"]
        mode = self.app.mode
        provider_key = str(data["provider"])
        model_name = str(data["model"])

        self._current_kv.clear()
        self._current_kv.add("Model", model_name or "none selected", mono=True)
        label = providers.CLOUD_BY_KEY.get(provider_key)
        self._current_kv.add(
            "Provider",
            f"{label.label} ({provider_key})" if label else provider_key or "unset")
        self._current_kv.add("Runs", "on this machine"
                             if providers.is_local(provider_key) else "over the network")
        if data["base_url"]:
            self._current_kv.add("Endpoint", str(data["base_url"]), mono=True)
        if data["num_ctx"] and provider_key in ("ollama", "custom"):
            self._current_kv.add("Asks for", f"{int(data['num_ctx']):,} tokens")

        # Judge the model in use against the floor.
        chosen = None
        for server in self._servers:
            for model in server.models:
                if model.name == model_name:
                    chosen = model
        verdict = (providers.context_verdict(chosen, data["num_ctx"])
                   if providers.is_local(provider_key) else
                   providers.Verdict(True, "ok", "Hosted provider.",
                                     "The provider reports its own window."))
        self._verdict_dot.set_state(verdict.state, verdict.headline)
        self._verdict_dot.apply_mode(mode)
        self._verdict_detail.setText(verdict.detail)
        self._clear(self._fix_row.layout())
        if verdict.fix:
            self._fix_row.layout().addWidget(w.button(
                f"Set {verdict.fix} to {verdict.fix_value:,}", "Primary",
                lambda k=verdict.fix, v=verdict.fix_value: self._set_keys({k: v})))
            self._fix_row.layout().addStretch(1)

        # --- local servers -------------------------------------------------
        self._clear(self._local_box)
        for server in self._servers:
            # A server that is down is the commonest reason this page
            # looks broken, and LM Studio's stops whenever its app is
            # quit. Saying "nothing is answering" and leaving the user to
            # find the CLI is a diagnosis without the fix beside it.
            start = None
            if (not server.reachable and not server.is_ollama
                    and providers.lms_available()):
                start = w.button("Start server", "Primary",
                                 self._start_lmstudio)
                start.setEnabled(not self._starting)
                start.setFixedWidth(126)
            head = w.row(
                w.label(server.name, "body_bold"),
                w.Badge("REACHABLE" if server.reachable else "NOT RUNNING",
                        "live" if server.reachable else "idle"),
                w.label(server.base_url, "MonoFaint"),
                w.spacer(), start, stretch_last=False)
            for child in head.findChildren(w.Badge):
                child.apply_mode(mode)
            self._local_box.addWidget(head)
            if not server.reachable:
                self._local_box.addWidget(w.label(
                    f"{server.error}. Start it and rescan.", "Faint"))
                self._local_box.addWidget(w.spacer(10))
                continue
            if not server.models:
                self._local_box.addWidget(w.label(
                    "Running, but serving no models.", "Faint"))
            for model in server.models:
                self._local_box.addWidget(
                    self._model_row(server, model, data, mode))
            self._local_box.addWidget(w.spacer(10))

        # --- hosted --------------------------------------------------------
        self._clear(self._cloud_box)
        secrets = data["secrets"]
        pool = data["auth"]
        if not pool.read:
            self._cloud_box.addWidget(w.label(
                f"Hermes's credential pool could not be read, so these rows "
                f"are guesses from .env: {pool.error}", "Faint", wrap=True))
        for provider in providers.CLOUD:
            if provider.key in ("custom", "auto"):
                continue
            # The pool is the real answer. A key in .env that Hermes has not
            # taken into its pool is not a usable credential, and for an
            # OAuth provider there is no key to look for at all — which is
            # why this used to read `provider.oauth`, a constant, and claim
            # every OAuth provider was ready.
            pooled = pool.has(provider.key) if pool.read else False
            keyed = bool(provider.credential) and provider.credential in secrets
            have = pooled or keyed
            if provider.oauth:
                word, token = (("SIGNED IN", "live") if pooled
                               else ("NOT SIGNED IN", "idle"))
            else:
                word, token = (("KEY SET", "live") if have else ("NO KEY", "idle"))
            badge = w.Badge(word, token)
            badge.setFixedWidth(130)
            badge.apply_mode(mode)
            name = w.label(provider.label, "body_bold")
            name.setFixedWidth(170)
            use = w.button("Use", "", lambda p=provider: self._use_cloud(p))
            use.setEnabled(bool(have))
            if not have:
                use.setToolTip(
                    "Sign in first — selecting a provider with no credential "
                    "behind it makes every turn fail somewhere else"
                    if provider.oauth else
                    f"Set {provider.credential} first")
            widgets = [name, badge]
            if provider.oauth:
                # The button that was missing entirely.
                action = w.button(
                    "Sign out" if pooled else "Sign in",
                    "" if pooled else "Primary",
                    (lambda p=provider: self._sign_out(p)) if pooled
                    else (lambda p=provider: self._sign_in(p)))
                action.setFixedWidth(230)
                action.setEnabled(not self._signing_in)
                widgets.append(action)
            elif provider.credential:
                field = QLineEdit()
                field.setPlaceholderText(provider.credential)
                field.setEchoMode(QLineEdit.EchoMode.Password)
                field.setFixedWidth(230)
                save = w.button("Save key", "Quiet",
                                lambda f=field, p=provider: self._save_key(p, f))
                widgets += [field, save]
            widgets += [w.spacer(), use]
            self._cloud_box.addWidget(w.row(*widgets))

        # --- library --------------------------------------------------------
        self._clear(self._library_box)
        have = {m.name for s in self._servers for m in s.models}
        for suggestion in SUGGESTED:
            name = w.label(suggestion.name, "Mono")
            name.setFixedWidth(170)
            window = w.label(f"{suggestion.published_context:,}", "MonoFaint")
            window.setFixedWidth(72)
            size = w.label(suggestion.size_hint, "MonoFaint")
            size.setFixedWidth(62)
            note = w.label(suggestion.note, "Faint", wrap=True)
            owned = any(h == suggestion.name or h.startswith(suggestion.name + "-")
                        or h.split(":")[0] == suggestion.name.split(":")[0]
                        and h == suggestion.name for h in have)
            action = (w.Badge("INSTALLED", "live") if owned
                      else w.button("Download", "",
                                    lambda n=suggestion.name: self._pull(n)))
            if isinstance(action, w.Badge):
                action.apply_mode(mode)
            else:
                action.setEnabled(not self._pulling)
            # The note takes the slack; the action keeps a button's width.
            # Without this the button stretches across half the card.
            action.setFixedWidth(118)
            holder = QWidget()
            line = QHBoxLayout(holder)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(8)
            for widget in (name, window, size):
                line.addWidget(widget)
            line.addWidget(note, 1)
            line.addWidget(action)
            self._library_box.addWidget(holder)

        reachable = sum(1 for s in self._servers if s.reachable)
        local_models = sum(len(s.models) for s in self._servers)
        usable = sum(1 for s in self._servers for m in s.models
                     if providers.context_verdict(m, 999_999).ok)
        self._message.setText(
            f"{reachable} local server(s) reachable · {local_models} local model(s) · "
            f"{usable} clear Hermes's {providers.MIN_CONTEXT_WINDOW:,}-token floor")

    def _model_row(self, server, model, data, mode) -> QWidget:
        verdict = providers.context_verdict(model, data["num_ctx"])
        in_use = model.name == str(data["model"])
        name = w.label(model.name, "Mono")
        name.setFixedWidth(232)

        # The *served* window, never the advertised one. LM Studio loads a
        # model at a chosen length that is usually far below what it
        # supports, and the loaded figure is the only one Hermes's floor is
        # judged against — so printing the big number alone would promise a
        # window that is not there. When they differ, both are shown.
        served = model.effective_context
        if served and model.context and served != model.context:
            window_text = f"{served:,} of {model.context:,}"
        elif served:
            window_text = f"{served:,}"
        else:
            window_text = "unknown"
        window = w.label(window_text, "MonoFaint")
        window.setFixedWidth(136)
        if served and model.context and served != model.context:
            window.setToolTip(
                f"Loaded at {served:,} tokens; the model itself supports "
                f"{model.context:,}. Hermes judges the loaded figure, so "
                f"this is what counts.")

        size = w.label(model.size_label, "MonoFaint")
        size.setFixedWidth(58)

        # What the model can do, as the server reports it rather than as its
        # name suggests. Vision is here because it decides whether the agent
        # can be handed a screenshot at all, and nothing else surfaces it.
        marks: list[str] = []
        if model.supports_tools:
            marks.append("tools")
        if model.vision:
            marks.append("vision")
        caps = w.label(" · ".join(marks), "MonoFaint")
        caps.setFixedWidth(118)
        caps.setToolTip("Capabilities reported by the server itself")

        # Name the actual problem. "TOO SMALL" on a model refused for having
        # no tool support sends you to fix the wrong thing.
        if in_use:
            word, token = "IN USE", "live"
        elif not model.loaded:
            word, token = "NOT LOADED", "attention"
        elif model.supports_tools is False:
            word, token = "NO TOOLS", "fault"
        elif verdict.ok:
            word, token = "USABLE", "live"
        elif verdict.fix:
            word, token = "NEEDS A SETTING", "attention"
        else:
            word, token = "TOO SMALL", "fault"
        badge = w.Badge(word, token)
        badge.apply_mode(mode)
        badge.setMinimumWidth(118)
        remove = w.button("Remove", "Quiet",
                          lambda n=model.name: self._delete(n))
        remove.setEnabled(server.is_ollama and not in_use
                          and not self._pulling)
        remove.setToolTip("Delete this model from disk"
                          if remove.isEnabled() else
                          "A model in use cannot be removed")
        # A model loaded below the floor is the one failure here that the app
        # can simply undo, so it offers to rather than only explaining it.
        needs_reload = (not server.is_ollama and providers.lms_available()
                        and (not model.loaded
                             or (model.effective_context
                                 and model.effective_context
                                 < providers.MIN_CONTEXT_WINDOW)))
        reload_btn = w.button(
            "Reload", "Quiet",
            lambda n=model.name: self._lms_reload(n))
        reload_btn.setVisible(bool(needs_reload))
        reload_btn.setEnabled(bool(needs_reload) and not self._reloading)
        reload_btn.setToolTip(
            f"Reload in LM Studio at {providers.MIN_CONTEXT_WINDOW:,} tokens, "
            f"the smallest window Hermes accepts")

        use = w.button("Use", "Primary" if not in_use else "",
                       lambda s=server, m=model: self._use_local(s, m))
        # Judged on the verdict rather than on the window alone, so that a
        # model loaded below the floor, or one with no tool support, is
        # unselectable for the reason that actually applies to it.
        use.setEnabled(not in_use and (verdict.ok or bool(verdict.fix)))
        if not use.isEnabled() and not in_use:
            use.setToolTip(verdict.detail or verdict.headline)
        return w.row(name, window, size, caps, badge, w.spacer(),
                     reload_btn, remove, use)

    def _fail(self, error: str) -> None:
        self._message.setText(f"Could not read the model setup: {error}")

    # --- actions ------------------------------------------------------------

    @staticmethod
    def _clear(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _set_keys(self, pairs: dict) -> None:
        self._message.setText("Writing…")

        def work():
            self.hermes.backup_config()
            return [(k, self.hermes.config_set(k, v)) for k, v in pairs.items()]

        def done(results):
            bad = [f"{k}: {r.message}" for k, r in results if not r.ok]
            self._message.setText("; ".join(bad) if bad else
                                  f"Set {', '.join(k for k, _ in results)}.")
            self.refresh()
            runtime = self.app.page("Runtime")
            if runtime is not None:
                runtime.refresh()

        self.jobs.run(work, done, self._fail)

    # --- downloading ------------------------------------------------------

    def _pull_typed(self) -> None:
        name = self._pull_name.text().strip()
        if name:
            self._pull(name)

    def _pull(self, name: str) -> None:
        """Download a model, reporting progress per layer.

        Ollama reports bytes per *layer*, not for the download as a whole, so a
        single percentage computed from them jumps backwards every time a layer
        finishes. The bar tracks the layer in flight and the caption counts the
        layers, which is both honest and more informative.
        """
        if self._pulling:
            return
        self._pulling = name
        self._pull_layers = set()
        self._pull_bar.setVisible(True)
        self._pull_bar.setRange(0, 0)
        self._pull_status.setText(f"Starting download of {name}…")
        self._pull_button.setEnabled(False)
        self._pull_job = self.jobs.stream(
            lambda: self._ollama.pull(name), self._on_pull,
            self._on_pull_done, self._fail)

    def _on_pull(self, progress: PullProgress) -> None:
        if progress.error:
            self._pull_status.setText(f"Download failed: {progress.error}")
            return
        if progress.digest:
            self._pull_layers.add(progress.digest)
        if progress.total > 0:
            self._pull_bar.setRange(0, 100)
            self._pull_bar.setValue(int(progress.fraction * 100))
            mb = progress.completed / 1_000_000
            total_mb = progress.total / 1_000_000
            self._pull_status.setText(
                f"{self._pulling} — {progress.status} — "
                f"{mb:,.0f} of {total_mb:,.0f} MB "
                f"(layer {len(self._pull_layers)})")
        else:
            self._pull_bar.setRange(0, 0)
            self._pull_status.setText(f"{self._pulling} — {progress.status}")

    def _on_pull_done(self) -> None:
        name, self._pulling = self._pulling, ""
        self._pull_bar.setVisible(False)
        self._pull_button.setEnabled(True)
        self._pull_job = None
        self._pull_name.clear()
        # The published figure got it here; the measured one decides whether
        # it is usable, so read it back before saying anything.
        window = self._ollama.context_window(name)
        if not window:
            self._pull_status.setText(
                f"{name}: finished, but its context window could not be read. "
                f"Rescan to check it.")
        elif window < providers.MIN_CONTEXT_WINDOW:
            self._pull_status.setText(
                f"{name} downloaded, but its real window is {window:,} tokens — "
                f"under the {providers.MIN_CONTEXT_WINDOW:,} Hermes requires, "
                f"so it cannot be used. You may want to remove it.")
        else:
            self._pull_status.setText(
                f"{name} is ready — {window:,} tokens. Press Use to select it.")
        self.refresh()

    def _delete(self, name: str) -> None:
        self._pull_status.setText(f"Removing {name}…")

        def work():
            return self._ollama.delete(name)

        def done(result):
            ok, message = result
            self._pull_status.setText(
                f"Removed {name}." if ok else f"Could not remove {name}: {message}")
            self.refresh()

        self.jobs.run(work, done, self._fail)

    def _start_lmstudio(self) -> None:
        """Start LM Studio's server, then load a model into it.

        Two steps because they are two things: the server can be up with
        nothing loaded, which answers the port and serves no model —
        exactly the state that reads as "working" and refuses every turn.
        """
        if self._starting:
            return
        self._starting = True
        self._message.setText("Starting LM Studio's server\u2026")
        self.refresh()

        def work():
            ok, detail = providers.lms_server_start()
            if not ok:
                return ok, detail
            server = providers.probe_lmstudio()
            if any(m.loaded for m in server.models):
                return ok, detail
            # Nothing loaded: bring up whichever model is configured, or
            # the first one the server knows about.
            wanted = str(self.hermes.config_value("model.default") or "")
            names = [m.name for m in server.models]
            choice = wanted if wanted in names else (names[0] if names else "")
            if not choice:
                return False, ("The server is up but knows of no models. "
                               "Download one in LM Studio first.")
            loaded_ok, loaded_detail = providers.lms_reload(choice)
            return loaded_ok, f"{detail} {loaded_detail}"

        def done(outcome):
            self._starting = False
            ok, detail = outcome
            self._message.setText(detail)
            self.refresh()

        self.jobs.run(work, done,
                      lambda e: (setattr(self, "_starting", False),
                                 self._message.setText(e), self.refresh()))

    def _lms_reload(self, name: str) -> None:
        """Reload one LM Studio model at a window Hermes will accept."""
        if self._reloading:
            return
        self._reloading = name
        self._message.setText(
            f"Reloading {name} in LM Studio at "
            f"{providers.MIN_CONTEXT_WINDOW:,} tokens — a large model takes "
            f"a moment…")
        self.refresh()
        self.jobs.run(lambda: providers.lms_reload(name),
                      self._on_reloaded, self._on_reload_failed)

    def _on_reloaded(self, outcome: tuple[bool, str]) -> None:
        self._reloading = ""
        ok, detail = outcome
        self._message.setText(detail if ok else f"Reload failed: {detail}")
        self.refresh()

    def _on_reload_failed(self, error: str) -> None:
        self._reloading = ""
        self._message.setText(f"Reload failed: {error}")
        self.refresh()

    def _use_local(self, server: providers.LocalServer,
                   model: providers.LocalModel) -> None:
        # Selecting a model LM Studio has not loaded writes a config that
        # points at nothing: the server answers, the model is absent, and
        # every turn fails. Load it first, then select it — the two steps
        # are one intention.
        if not server.is_ollama and not model.loaded:
            if not providers.lms_available():
                self._message.setText(
                    f"{model.name} is not loaded in LM Studio, and the lms "
                    f"CLI is not here to load it. Load it in LM Studio at "
                    f"{providers.MIN_CONTEXT_WINDOW:,} tokens or more, then "
                    f"rescan.")
                return
            self._message.setText(
                f"{model.name} is not loaded — loading it first\u2026")
            self.jobs.run(
                lambda n=model.name: providers.lms_reload(n),
                lambda outcome, s=server, m=model: self._loaded_then_use(
                    outcome, s, m),
                lambda e: self._message.setText(e))
            return
        self._apply_local(server, model)

    def _loaded_then_use(self, outcome: tuple[bool, str],
                         server: providers.LocalServer,
                         model: providers.LocalModel) -> None:
        ok, detail = outcome
        self._message.setText(detail)
        if ok:
            self._apply_local(server, model)
        else:
            self.refresh()

    def _apply_local(self, server: providers.LocalServer,
                     model: providers.LocalModel) -> None:
        pairs = {
            "model.provider": providers.canonical_provider(server.provider_key),
            "model.base_url": server.base_url,
            "model.default": model.name,
        }
        if server.is_ollama:
            pairs["model.api_key"] = "ollama"
            if model.context:
                pairs["model.ollama_num_ctx"] = providers.suggested_num_ctx(model)
        else:
            # LM Studio ignores the value but the OpenAI client refuses to
            # send a request without one, and whatever the last provider set
            # would otherwise be left in place.
            pairs["model.api_key"] = "lmstudio"
            # And tell Hermes the window the server will really serve.
            #
            # Hermes sizes its compressor from this key whatever the
            # provider — the log line even calls it "Ollama num_ctx" while
            # talking to LM Studio. Left at a previous model's value it
            # believed 131,072 against a server serving 65,536, so
            # compaction was scheduled past the point the server can
            # accept and a long conversation grew until it was silently
            # truncated. Nothing anywhere reported that; the thread simply
            # started going missing.
            if model.effective_context:
                pairs["model.ollama_num_ctx"] = model.effective_context
        self._set_keys(pairs)

    def _sign_in(self, provider: providers.CloudProvider) -> None:
        """Sign in to a hosted provider, showing the device code as it
        arrives.

        The flow prints a URL and a short code and then blocks until the
        person has used them, so the output has to be streamed — waiting
        for the command to finish would show the code only after it had
        expired.
        """
        if self._signing_in:
            return
        self._signing_in = provider.key
        self._sign_in_text = ""
        self._sign_in_card.setVisible(True)
        self._sign_in_title.setText(f"Signing in to {provider.label}")
        self._sign_in_code.setText("waiting for a code\u2026")
        self._sign_in_log.setPlainText("")
        self.refresh()
        self.jobs.stream(
            lambda p=provider.key: self.hermes.auth_sign_in_stream(p),
            self._on_sign_in_line, self._on_sign_in_done,
            lambda e: self._on_sign_in_done(None, e))

    def _on_sign_in_line(self, line: str) -> None:
        self._sign_in_text += line + "\n"
        self._sign_in_log.setPlainText(self._sign_in_text)
        bar = self._sign_in_log.verticalScrollBar()
        bar.setValue(bar.maximum())
        url, code = hauth.extract_code(self._sign_in_text)
        if code or url:
            self._sign_in_code.setText(
                f"Code: {code}\n{url}" if code else url)

    def _on_sign_in_done(self, _result=None, error: str = "") -> None:
        self._signing_in = ""
        if error:
            self._sign_in_code.setText(f"Sign-in failed: {error}")
        else:
            self._sign_in_code.setText(
                "Flow finished. If it succeeded the badge now reads "
                "SIGNED IN; if it still says NOT SIGNED IN, the sign-in "
                "did not complete.")
        self.refresh()

    def _cancel_sign_in(self) -> None:
        self.hermes.cancel_sign_in()
        self._signing_in = ""
        self._sign_in_code.setText("Cancelled.")
        self.refresh()

    def _sign_out(self, provider: providers.CloudProvider) -> None:
        self._message.setText(f"Signing out of {provider.label}\u2026")
        self.jobs.run(lambda p=provider.key: self.hermes.auth_logout(p),
                      lambda r: (self._message.setText(
                          "Signed out." if r.ok else
                          (r.stderr or r.stdout or r.message).strip()),
                          self.refresh()),
                      lambda e: self._message.setText(e))

    def _use_cloud(self, provider: providers.CloudProvider) -> None:
        pairs = {"model.provider": provider.key}
        if provider.base_url:
            pairs["model.base_url"] = provider.base_url
        self._set_keys(pairs)

    def _save_key(self, provider: providers.CloudProvider, field: QLineEdit) -> None:
        value = field.text().strip()
        if not value:
            self._message.setText("Nothing to save.")
            return
        field.clear()
        self._message.setText(f"Writing {provider.credential} to .env…")

        def work():
            return self.hermes.set_secret(provider.credential, value)

        def done(result):
            self._message.setText(
                f"{provider.credential} saved." if result.ok
                else f"Could not save {provider.credential}: {result.message}")
            self.refresh()

        self.jobs.run(work, done, self._fail)
