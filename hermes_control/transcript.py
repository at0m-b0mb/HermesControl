"""
Making a tool result readable without lying about it.

Hermes returns tool results as JSON, and some are long: creating one
cron job comes back as nine hundred characters describing the job,
most of it nulls. Dumped verbatim into a chat window it buries the
conversation — the answer you were reading ends up below a wall of
``"last_delivery_error": null``.

Truncating at a character count is the obvious fix and the wrong one:
it cuts mid-key and throws away the part that matters, because the
useful fields (``success``, an id, a message, an error) are rarely in
the first two hundred characters.

So a result is *summarised* rather than cut — the fields that say what
happened, in a line — and the full text is kept available rather than
discarded. When a result is not JSON, or has no field worth promoting,
it falls back to plain truncation, which is honest about being a
truncation.
"""

from __future__ import annotations

import json

#: Fields worth promoting, in the order they read best. Chosen because
#: each answers "what happened": whether it worked, what it produced,
#: and what it said.
HEADLINE_KEYS: tuple[str, ...] = (
    # ``content`` first among the payloads: for a read, the file's text
    # *is* the result, and a summary that reports its line count while
    # dropping what it says has summarised away the answer.
    "error", "content", "output", "message", "note", "summary", "status",
    "job_id", "id", "name", "path", "resolved_path", "file",
    "bytes_written", "total_lines", "entry_count", "usage",
    "schedule", "next_run_at", "target", "count", "exit_code",
)

#: Keys that only add noise in a one-line summary.
SKIP_KEYS = frozenset({
    "success", "done", "job", "skills", "skill", "truncated", "is_binary",
    "is_image", "not_found", "lint", "dirs_created", "verified",
    "files_modified", "last_run_at", "last_status", "last_delivery_error",
    "prompt_preview", "model", "provider", "base_url", "pinned",
})


def summarise_result(output: object, limit: int = 220) -> tuple[str, bool]:
    """Return ``(text, was_shortened)`` for one tool result."""
    # ``str(None)`` is "None", which is truthy and would be printed as a
    # result. A tool that returned nothing must read as nothing.
    if output is None:
        return "(no output)", False
    raw = output if isinstance(output, str) else str(output)
    text = raw.strip()
    if not text:
        return "(no output)", False

    data = None
    if text[:1] in "{[":
        try:
            data = json.loads(text)
        except ValueError:
            data = None

    if isinstance(data, dict):
        bits: list[str] = []
        # Lead with the verdict when the tool states one, because a
        # failed call that reads like a successful one is the single most
        # misleading thing a transcript can show.
        if data.get("error"):
            bits.append(f"error: {str(data['error']).strip()}")
        elif data.get("success") is True:
            bits.append("ok")
        elif data.get("success") is False:
            bits.append("failed")
        for key in HEADLINE_KEYS:
            if key == "error" or key in SKIP_KEYS or key not in data:
                continue
            value = data[key]
            if value in (None, "", [], {}):
                continue
            rendered = (value if isinstance(value, str)
                        else json.dumps(value, separators=(",", ":")))
            # One line. A result that spans several breaks the alignment
            # the summary exists to give, and a file's newlines say
            # nothing useful at this size.
            rendered = " ".join(rendered.split())
            # Payload fields get more room than metadata: a path or an id
            # is recognisable in a few characters, a file's contents are
            # not.
            room = 140 if key in ("content", "output") else 70
            if len(rendered) > room:
                rendered = rendered[:room] + "…"
            bits.append(f"{key}={rendered}")
        if bits:
            line = "  ".join(bits)
            shortened = len(line) < len(text)
            if len(line) > limit:
                line = line[:limit] + "…"
                shortened = True
            return line, shortened
        # A dict with nothing worth promoting still reads better as its
        # own keys than as a wall of JSON.
        keys = ", ".join(list(data)[:8])
        return f"{len(data)} field(s): {keys}", True

    if len(text) > limit:
        return text[:limit] + "…", True
    return text, False
