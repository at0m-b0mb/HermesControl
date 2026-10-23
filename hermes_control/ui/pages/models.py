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
                               QVBoxLayout, QWidget)

from ... import providers
from ...ollama import KNOWN_TOO_SMALL, SUGGESTED, Ollama, PullProgress
from .. import widgets as w
from ..shell import Page


class ModelsPage(Page):
    title = "Models"
    group = "Runtime"

    def __init__(self, app, parent: QWidget | None = None):
        super().__init__(app, parent)
        self._servers: list[providers.LocalServer] = []
        self._ollama = Ollama()
        self._pull_job = None
        self._pulling = ""
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
        if data["num_ctx"]:
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
            head = w.row(
                w.label(server.name, "body_bold"),
                w.Badge("REACHABLE" if server.reachable else "NOT RUNNING",
                        "live" if server.reachable else "idle"),
                w.label(server.base_url, "MonoFaint"),
                w.spacer(), stretch_last=False)
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
        for provider in providers.CLOUD:
            if provider.key in ("custom", "auto"):
                continue
            have = provider.credential in secrets if provider.credential else provider.oauth
            badge = w.Badge(
                "KEY SET" if have and provider.credential else
                "OAUTH" if provider.oauth else "NO KEY",
                "live" if have else "idle")
            badge.apply_mode(mode)
            name = w.label(provider.label, "body_bold")
            name.setFixedWidth(170)
            use = w.button("Use", "", lambda p=provider: self._use_cloud(p))
            use.setEnabled(bool(have))
            widgets = [name, badge]
            if provider.credential:
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
        name.setFixedWidth(300)
        window = w.label(f"{model.context:,}" if model.context else "unknown",
                         "MonoFaint")
        window.setFixedWidth(78)
        size = w.label(model.size_label, "MonoFaint")
        size.setFixedWidth(62)
        badge = w.Badge("IN USE" if in_use else
                        ("USABLE" if verdict.ok or verdict.fix else "TOO SMALL"),
                        "live" if in_use or verdict.ok else
                        ("attention" if verdict.fix else "fault"))
        badge.apply_mode(mode)
        remove = w.button("Remove", "Quiet",
                          lambda n=model.name: self._delete(n))
        remove.setEnabled(server.provider_key == "ollama" and not in_use
                          and not self._pulling)
        remove.setToolTip("Delete this model from disk"
                          if remove.isEnabled() else
                          "A model in use cannot be removed")
        use = w.button("Use", "Primary" if not in_use else "",
                       lambda s=server, m=model: self._use_local(s, m))
        use.setEnabled(not in_use and model.context >= providers.MIN_CONTEXT_WINDOW
                       or (not in_use and not model.context))
        if not use.isEnabled() and not in_use:
            use.setToolTip(verdict.detail or verdict.headline)
        return w.row(name, window, size, badge, w.spacer(), remove, use)

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

    def _use_local(self, server: providers.LocalServer,
                   model: providers.LocalModel) -> None:
        pairs = {
            "model.provider": server.provider_key,
            "model.base_url": server.base_url,
            "model.default": model.name,
        }
        if server.provider_key == "ollama":
            pairs["model.api_key"] = "ollama"
            if model.context:
                pairs["model.ollama_num_ctx"] = min(
                    max(model.context, providers.MIN_CONTEXT_WINDOW), 131_072)
        self._set_keys(pairs)

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
