"""Soul — the agent's identity, which Hermes injects as its first prompt slot."""

from __future__ import annotations

from ._fileedit import FileEditorPage


class SoulPage(FileEditorPage):
    title = "Soul"
    group = "Agent"
    filename = "SOUL.md"
    intro = ("SOUL.md is the first thing in Hermes's system prompt — who it is, "
             "how it speaks, what it refuses. Changing it changes every new "
             "session, including ones that arrive over messaging.")
    placeholder = ("# Who you are\n\nWrite in the second person: \"You are …\".\n")
