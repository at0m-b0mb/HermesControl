"""
What the agent can actually do, before you ask it anything.

The official Hermes chat opens with a card listing the model, the working
directory, the session, every tool grouped by toolset, and the skill
count. It is the best idea in that interface, because the first question
anyone has about an agent — *can it really touch my files?* — is
answerable up front and was previously answerable only by trying.

This module computes that briefing from facts rather than claims: the
tool list comes from Hermes's own ``prompt-size`` breakdown, which
enumerates the schemas actually being sent, and the window comes from
what the server reports it is serving. Nothing here is a capability the
app believes in; everything is one the agent is being handed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

#: ``    file                       4     5,673 B  (5.5 KB)``
_TOOLSET_ROW = re.compile(
    r"^\s{2,}(?P<name>[\w()\- ]+?)\s{2,}(?P<count>\d+)\s+(?P<bytes>[\d,]+)\s*B")
# The line reads:  Tool schemas : 41,142 B  (40.2 KB, 21 tools)
# The count sits *inside* the same bracket as the rounded size, so a
# pattern anchored on "(" finds "40.2 KB, …" and fails.
_TOOLS_TOTAL = re.compile(
    r"Tool schemas\s*:\s*(?P<bytes>[\d,]+)\s*B[^\n]*?(?P<n>\d+)\s+tools")
_PROMPT_TOTAL = re.compile(r"System prompt total\s*:\s*([\d,]+)\s*B")

#: Toolsets worth naming in plain words. The rest are listed by their own
#: name; inventing a description for a toolset this app has not verified
#: would be a guess dressed as documentation.
PLAIN_WORDS: dict[str, str] = {
    "file": "read, write, patch and search files",
    "terminal": "run shell commands",
    "web": "fetch and search the web",
    "vision": "look at images",
    "browser-use": "drive a real browser",
    "code_execution": "run code",
    "skills": "load and write its own procedures",
    "memory": "remember across sessions",
    "delegation": "hand work to a sub-agent",
    "connections": "reach connected apps",
    "tts": "speak",
    "clarify": "ask you a question mid-task",
}


@dataclass
class Toolset:
    name: str
    tools: int
    schema_bytes: int = 0

    @property
    def plain(self) -> str:
        return PLAIN_WORDS.get(self.name, "")


@dataclass
class Briefing:
    model: str = ""
    provider: str = ""
    window: int = 0
    workdir: str = ""
    session: str = ""
    toolsets: list[Toolset] = field(default_factory=list)
    skills: int = 0
    skills_broken: int = 0
    prompt_bytes: int = 0
    schema_bytes: int = 0
    tool_count: int = 0
    #: False when ``prompt-size`` could not be read, in which case the
    #: briefing must not claim a tool list it does not have.
    read: bool = False
    error: str = ""

    @property
    def can_edit_files(self) -> bool:
        """Whether a file toolset is actually being sent to the model."""
        return any(t.name == "file" and t.tools for t in self.toolsets)

    @property
    def can_see_images(self) -> bool:
        return any(t.name == "vision" and t.tools for t in self.toolsets)

    @property
    def can_run_commands(self) -> bool:
        return any(t.name in ("terminal", "code_execution") and t.tools
                   for t in self.toolsets)

    @property
    def overhead(self) -> int:
        """Bytes of prompt sent before a word of conversation.

        Worth stating because on a small window it is most of it: a
        65,536-token model carrying 60 KB of system prompt and tool
        schemas has far less room for the conversation than its headline
        number suggests, and that is the real reason a long chat starts
        compacting sooner than expected.
        """
        return self.prompt_bytes + self.schema_bytes

    def headroom(self, chars_per_token: float = 3.6) -> int:
        """Roughly how many tokens are left for the conversation itself."""
        if not self.window:
            return 0
        return max(0, self.window - int(self.overhead / chars_per_token))


def parse_prompt_size(payload: str) -> tuple[list[Toolset], int, int, int]:
    """Read ``hermes prompt-size``.

    Returns the toolsets, the tool count, the schema bytes and the system
    prompt bytes. There is no JSON form of this command, so the table is
    parsed, and an unrecognised line is skipped rather than aborting.
    """
    toolsets: list[Toolset] = []
    tool_count = 0
    schema_bytes = 0
    prompt_bytes = 0
    in_toolsets = False
    for line in payload.splitlines():
        total = _TOOLS_TOTAL.search(line)
        if total:
            schema_bytes = int(total.group("bytes").replace(",", ""))
            tool_count = int(total.group("n"))
            continue
        prompt = _PROMPT_TOTAL.search(line)
        if prompt:
            prompt_bytes = int(prompt.group(1).replace(",", ""))
            continue
        if "Toolsets by size" in line:
            in_toolsets = True
            continue
        if in_toolsets:
            if line.strip().startswith("Skills by size") or (
                    not line.strip() and toolsets):
                in_toolsets = False
                continue
            if "toolset" in line and "schema" in line:
                continue
            row = _TOOLSET_ROW.match(line)
            if row:
                name = row.group("name").strip()
                if name in ("toolset",):
                    continue
                toolsets.append(Toolset(
                    name=name, tools=int(row.group("count")),
                    schema_bytes=int(row.group("bytes").replace(",", ""))))
    return toolsets, tool_count, schema_bytes, prompt_bytes


def build(payload: str, read: bool, *, model: str = "", provider: str = "",
          window: int = 0, workdir: str = "", session: str = "",
          skills: int = 0, skills_broken: int = 0,
          error: str = "") -> Briefing:
    toolsets, count, schema, prompt = (
        parse_prompt_size(payload) if read else ([], 0, 0, 0))
    return Briefing(
        model=model, provider=provider, window=window, workdir=workdir,
        session=session, toolsets=toolsets, skills=skills,
        skills_broken=skills_broken, prompt_bytes=prompt,
        schema_bytes=schema, tool_count=count, read=read, error=error)
