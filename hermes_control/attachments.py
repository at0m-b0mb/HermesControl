"""
Attaching files and images to a turn.

Hermes has an ``--image`` flag, and it cannot be used here. When a
gateway is running — which it must be, to serve Telegram or email — the
turn is handed to that process, and the gateway refuses the flag
outright::

    Error: Unsupported gateway CLI options: --image.
      --image: use `hermes --tui` or the Desktop app to attach the image

So an attachment built on that flag works right up until someone
connects a messaging channel, and then stops. The route that works in
both cases is the plain one: name the file by **absolute path** in the
prompt and let the agent reach for it with the tools it already has —
``vision_analyze`` for an image, ``read_file`` for anything else. That
is what this module composes.

Absolute paths, always. The agent's working directory is not the user's
and not this app's; a bare filename resolves somewhere nobody intended,
which is precisely how a SOUL.md edit once landed in a home directory
instead of the Hermes install.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Extensions a vision model can look at. Anything else is read as text
#: or handed to a tool that understands it, rather than being described
#: as an image the model cannot actually see.
IMAGE_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif",
})

#: Things worth naming so the agent knows what it is holding, without
#: pretending this app can parse them.
KIND_BY_SUFFIX: dict[str, str] = {
    ".pdf": "PDF", ".csv": "CSV", ".tsv": "TSV", ".json": "JSON",
    ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML", ".md": "Markdown",
    ".txt": "text", ".log": "log", ".py": "Python", ".js": "JavaScript",
    ".ts": "TypeScript", ".html": "HTML", ".css": "CSS", ".sh": "shell",
    ".zip": "archive", ".tar": "archive", ".gz": "archive",
}

#: Beyond this the agent is told the size up front, because reading a
#: very large file into the window is a decision rather than a detail.
LARGE_FILE_BYTES = 200_000


@dataclass(frozen=True)
class Attachment:
    path: Path

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def is_image(self) -> bool:
        return self.path.suffix.lower() in IMAGE_SUFFIXES

    @property
    def kind(self) -> str:
        if self.is_image:
            return "image"
        return KIND_BY_SUFFIX.get(self.path.suffix.lower(), "file")

    @property
    def size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    @property
    def exists(self) -> bool:
        try:
            return self.path.is_file()
        except OSError:
            return False

    @property
    def size_label(self) -> str:
        size = self.size
        if size <= 0:
            return ""
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.0f} KB"
        return f"{size / (1024 * 1024):.1f} MB"

    @property
    def label(self) -> str:
        bits = [self.name]
        if self.size_label:
            bits.append(self.size_label)
        return "  ".join(bits)


def collect(paths) -> list[Attachment]:
    """Normalise a set of paths, dropping anything that is not a file.

    Directories are skipped rather than walked: dropping a folder on a
    chat window should not quietly enqueue four hundred files.
    """
    found: list[Attachment] = []
    seen: set[Path] = set()
    for raw in paths:
        try:
            path = Path(raw).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        found.append(Attachment(path))
    return found


def compose(message: str, attachments: list[Attachment]) -> str:
    """Build the prompt text for a turn that carries attachments.

    The paths go in a clearly delimited block rather than being woven
    into the sentence, so that the agent can find them whatever the user
    wrote, and so a path containing spaces cannot be mistaken for two.
    """
    if not attachments:
        return message
    lines = [message.strip(), "", "---", "Attached, by absolute path:"]
    for item in attachments:
        note = f"- {item.path}  ({item.kind}"
        if item.size_label:
            note += f", {item.size_label}"
        note += ")"
        if not item.exists:
            note += "  [missing now — it was there when attached]"
        elif item.size > LARGE_FILE_BYTES and not item.is_image:
            note += "  [large: read a part of it rather than all of it]"
        lines.append(note)
    images = [a for a in attachments if a.is_image]
    others = [a for a in attachments if not a.is_image]
    hints = []
    if images:
        hints.append("Use vision_analyze on the image path(s)")
    if others:
        hints.append("Use read_file on the other path(s)")
    if hints:
        lines += ["", f"{'. '.join(hints)}. The paths are absolute — use "
                      f"them exactly as written, do not shorten them."]
    return "\n".join(lines)
