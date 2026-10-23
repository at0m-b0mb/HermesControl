"""
Where the settings editor gets its knowledge of Hermes.

Hermes ships its configuration as a 2,300-line *annotated* ``config.yaml``:
every option appears with upstream's own prose above it, its default beside
it, and in many cases the list of accepted values spelled out in an inline
comment. Optional settings are present too, commented out, as worked examples.

That file is a better schema than anything written by hand here, for one
reason that matters more than convenience: it ships with the install, so it
describes *the version actually on this machine*. Hermes gains options every
release. A hand-maintained catalogue would start rotting the day it was
written and would quietly stop showing the user settings they have. Parsing
the file instead means the editor is complete by construction, and a Hermes
update is picked up by re-reading it.

So this module does two passes over that one file:

* **YAML**, for the authoritative tree of settings that are *active*, with
  their real values and therefore their real types.
* **Text**, for everything YAML throws away — the section a key belongs to,
  the paragraph explaining it, the inline hint listing its accepted values,
  and the commented-out optional keys that are available but unset.

The two are merged into :class:`Option` records. Nothing here writes: see
``configstore`` for that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# A banner line: the rule above and below a section title.
_BANNER = re.compile(r"^#\s*=====+\s*$")
# An active key: `  foo:` or `  foo: value`.
_ACTIVE_KEY = re.compile(r"^(?P<indent> *)(?P<key>[A-Za-z_][\w-]*):(?P<rest>.*)$")
# A commented-out key: `  # foo: value`. Distinguishing these from ordinary
# prose is the one genuinely ambiguous part of the parse; see _looks_like_key.
_COMMENTED_KEY = re.compile(r"^(?P<indent> *)#\s?(?P<key>[a-z_][\w-]*):(?P<rest>.*)$")
_COMMENT = re.compile(r"^(?P<indent> *)#\s?(?P<text>.*)$")

#: Words that start a sentence often enough that `word:` is prose, not a key.
_PROSE_STARTERS = {
    "note", "example", "examples", "warning", "caution", "default", "defaults",
    "e", "eg", "ie", "see", "tip", "important", "nb", "usage", "syntax",
    "values", "options", "supported", "required", "optional", "format",
    "behavior", "behaviour", "why", "how", "what", "when", "where", "which",
    "set", "use", "run", "docs", "doc", "todo", "fixme", "caveat", "result",
    "effect", "meaning", "reason", "limitation", "limitations", "exception",
}

_CHOICE_PATTERNS = (
    re.compile(r"[Ss]upported values?:\s*(?P<body>.+)"),
    re.compile(r"[Aa]ccepted values?:\s*(?P<body>.+)"),
    re.compile(r"[Vv]alid values?:\s*(?P<body>.+)"),
    re.compile(r"[Oo]ptions?:\s*(?P<body>.+)"),
    re.compile(r"[Oo]ne of:?\s*(?P<body>.+)"),
)
_QUOTED = re.compile(r'"([^"]+)"|\'([^\']+)\'')
_BARE_ALTS = re.compile(r"^[\w.\-]+(?:\s*\|\s*[\w.\-]+)+$")


def _looks_like_key(key: str, rest: str) -> bool:
    """Is `# key: rest` a commented-out setting rather than a sentence?

    Prose beats us occasionally in both directions, so the result is advisory:
    options discovered this way are marked ``commented`` and are offered as
    "available, not set" rather than presented as live configuration. A write
    goes through Hermes's own ``config set``, which is the real validator.
    """
    if key.lower() in _PROSE_STARTERS:
        return False
    body = rest.strip()
    if not body:
        # `# foo:` alone is usually the head of a commented mapping.
        return True
    # A sentence continues past the colon with capitalised words and spaces;
    # a YAML value is a scalar, a list, or a value plus a trailing comment.
    if body[0] in "\"'[{":
        return True
    first = body.split()[0].rstrip(",")
    if first.lower() in ("true", "false", "null", "~", "yes", "no"):
        return True
    try:
        float(first)
        return True
    except ValueError:
        pass
    # `# key: value  # explanation` is still a key.
    if "#" in body:
        return True
    # Anything else with several words is prose.
    return len(body.split()) <= 2 and not body.endswith((".", ",", ":", ";"))


def _parse_choices(text: str) -> list[str]:
    """Pull an accepted-value list out of upstream's prose, if it states one."""
    for pattern in _CHOICE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        body = match.group("body")
        quoted = [a or b for a, b in _QUOTED.findall(body)]
        if len(quoted) >= 2:
            return quoted
        # `wal | delete` or `off | quick | full`
        cleaned = body.strip().rstrip(".").strip()
        if _BARE_ALTS.match(cleaned):
            return [p.strip() for p in cleaned.split("|")]
        # `OFF, NORMAL, FULL, EXTRA`
        parts = [p.strip().rstrip(".") for p in cleaned.split(",")]
        parts = [p for p in parts if p and " " not in p]
        if len(parts) >= 2:
            return parts
    return []


def _infer_kind(value: Any, choices: list[str]) -> str:
    if choices:
        return "choice"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "map"
    if value is None:
        return "optional"
    return "text"


@dataclass
class Option:
    """One configurable setting."""

    path: str                       # dotted key, e.g. "compression.threshold"
    value: Any = None               # current value (None when unset)
    default: Any = None             # what shipped in the annotated file
    kind: str = "text"              # bool|int|float|text|choice|list|map|optional
    choices: list[str] = field(default_factory=list)
    help: str = ""                  # upstream's prose, reflowed
    inline: str = ""                # the trailing `# ...` beside the value
    section: str = "General"        # banner title this key sits under
    commented: bool = False         # discovered commented-out (available, unset)
    line: int = 0                   # 1-based line in config.yaml

    @property
    def name(self) -> str:
        return self.path.rsplit(".", 1)[-1]

    @property
    def is_container(self) -> bool:
        return self.kind in ("map",) and not self.commented


@dataclass
class Schema:
    """Every option Hermes documents, grouped the way upstream groups them."""

    options: list[Option]
    sections: list[str]
    source: Path
    config_version: Any = None

    def by_section(self) -> dict[str, list[Option]]:
        out: dict[str, list[Option]] = {}
        for opt in self.options:
            out.setdefault(opt.section, []).append(opt)
        return out

    def get(self, path: str) -> Option | None:
        for opt in self.options:
            if opt.path == path:
                return opt
        return None

    def search(self, query: str) -> list[Option]:
        q = query.strip().lower()
        if not q:
            return self.options
        hits = []
        for opt in self.options:
            haystack = f"{opt.path} {opt.section} {opt.help} {opt.inline}".lower()
            if all(token in haystack for token in q.split()):
                hits.append(opt)
        return hits


def _flatten(tree: Any, prefix: str = "") -> dict[str, Any]:
    """Dotted-path view of a nested mapping, keeping containers as well."""
    out: dict[str, Any] = {}
    if not isinstance(tree, dict):
        return out
    for key, value in tree.items():
        path = f"{prefix}{key}"
        out[path] = value
        if isinstance(value, dict):
            out.update(_flatten(value, f"{path}."))
    return out


def _reflow(lines: list[str]) -> str:
    """Join a comment block into paragraphs, keeping deliberate breaks."""
    paragraphs: list[list[str]] = [[]]
    for raw in lines:
        text = raw.strip()
        if not text:
            if paragraphs[-1]:
                paragraphs.append([])
            continue
        # Keep list items and examples on their own lines.
        if text.startswith(("-", "*", "•")) or re.match(r"^\w+[.)] ", text):
            paragraphs.append([text])
            paragraphs.append([])
            continue
        paragraphs[-1].append(text)
    chunks = [" ".join(p) for p in paragraphs if p]
    return "\n".join(chunks).strip()


def parse(config_path: Path) -> Schema:
    """Read the annotated ``config.yaml`` and build the schema from it."""
    text = config_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    # --- pass one: the authoritative active tree ---------------------------
    try:
        active = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        active = {}
    flat = _flatten(active if isinstance(active, dict) else {})
    config_version = flat.pop("_config_version", None)

    # --- pass two: structure, prose and commented examples -----------------
    section = "General"
    sections: list[str] = []
    comment_block: list[str] = []
    # indent -> key, so a nested key can be given its full dotted path
    stack: dict[int, str] = {}
    found: dict[str, Option] = {}
    index = 0

    while index < len(lines):
        line = lines[index]

        # A section banner: `# ===`, `# Title`, `# ===`.
        if _BANNER.match(line):
            if (index + 2 < len(lines)
                    and _BANNER.match(lines[index + 2])
                    and (m := _COMMENT.match(lines[index + 1]))):
                title = m.group("text").strip()
                if title:
                    section = title
                    if title not in sections:
                        sections.append(title)
                    comment_block = []
                    index += 3
                    continue
            index += 1
            continue

        if not line.strip():
            comment_block.append("")
            index += 1
            continue

        active_match = _ACTIVE_KEY.match(line)
        if active_match and not line.lstrip().startswith("#"):
            indent = len(active_match.group("indent"))
            key = active_match.group("key")
            rest = active_match.group("rest")
            for deeper in [i for i in stack if i >= indent]:
                stack.pop(deeper, None)
            parent = stack.get(max((i for i in stack if i < indent), default=-1), "")
            path = f"{parent}.{key}" if parent else key
            stack[indent] = path

            if path != "_config_version":
                inline = ""
                if "#" in rest:
                    inline = rest.split("#", 1)[1].strip()
                help_text = _reflow(comment_block)
                choices = _parse_choices(f"{inline}\n{help_text}")
                value = flat.get(path)
                found[path] = Option(
                    path=path, value=value, default=value,
                    kind=_infer_kind(value, choices), choices=choices,
                    help=help_text, inline=inline, section=section,
                    commented=False, line=index + 1,
                )
            comment_block = []
            index += 1
            continue

        commented_match = _COMMENTED_KEY.match(line)
        if commented_match:
            key = commented_match.group("key")
            rest = commented_match.group("rest")
            if _looks_like_key(key, rest):
                indent = len(commented_match.group("indent"))
                parent = stack.get(max((i for i in stack if i < indent), default=-1), "")
                path = f"{parent}.{key}" if parent else key
                if path not in found:
                    inline = ""
                    body = rest.strip()
                    if "#" in body:
                        body, inline = body.split("#", 1)
                        inline = inline.strip()
                    try:
                        example = yaml.safe_load(body) if body.strip() else None
                    except yaml.YAMLError:
                        example = body.strip() or None
                    help_text = _reflow(comment_block)
                    choices = _parse_choices(f"{inline}\n{help_text}")
                    found[path] = Option(
                        path=path, value=None, default=example,
                        kind=_infer_kind(example, choices), choices=choices,
                        help=help_text, inline=inline, section=section,
                        commented=True, line=index + 1,
                    )
                comment_block = []
                index += 1
                continue
            # Prose: keep it as help for whatever key comes next.
            comment_block.append(commented_match.group("rest") and line or line)
            comment = _COMMENT.match(line)
            comment_block[-1] = comment.group("text") if comment else line
            index += 1
            continue

        comment = _COMMENT.match(line)
        if comment:
            comment_block.append(comment.group("text"))
            index += 1
            continue

        comment_block = []
        index += 1

    # Any active key the text pass missed (a list item's child, say) still
    # belongs in the schema: completeness is the point of this module.
    for path, value in flat.items():
        if path not in found:
            found[path] = Option(
                path=path, value=value, default=value,
                kind=_infer_kind(value, []), section="General",
            )

    options = sorted(found.values(), key=lambda o: (o.section, o.path))
    ordered = [s for s in sections if any(o.section == s for o in options)]
    if any(o.section == "General" for o in options):
        ordered.append("General")
    return Schema(options=options, sections=ordered, source=config_path,
                  config_version=config_version)

#: Keys whose value is a credential. Hermes's own ``config get`` masks these
#: unless ``--raw`` is passed; the editor reads the file directly, so it has to
#: make the same judgement itself.
#:
#: The plural ``_tokens`` exclusion is the whole subtlety: in Hermes a "token"
#: is usually a unit of context, so ``compression.threshold_tokens`` and
#: ``proactive_prune_tokens`` are counts, not secrets. Masking them would hide
#: ordinary numbers behind dots and teach people to ignore the mask.
_SECRET = re.compile(
    r"(api_?key|password|passwd|secret|credential|private_key|access_key"
    r"|(?:^|[._])token$|bot_token|client_id)", re.IGNORECASE)


def is_secret(path: str) -> bool:
    """Should this key's value be hidden by default?"""
    leaf = path.rsplit(".", 1)[-1]
    if leaf.endswith("_tokens") or leaf == "tokens":
        return False          # a count of context tokens, not a credential
    return bool(_SECRET.search(path))

