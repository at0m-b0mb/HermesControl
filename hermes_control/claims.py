"""
Did it actually do that, or only say so?

The failure this exists for is the one a transcript cannot show you. A
model is asked to remember something, or to set a reminder, and answers
"Done — I've made a note of that." Sometimes the tool ran and the file
changed. Sometimes no tool ran at all and the sentence is the whole of
it. The two are *identical on screen*, and the second is the commonest
way a small local model looks like it is working.

Hermes reports every tool call, so the app can tell them apart: if the
final answer claims an action of a kind that requires a tool, and no
tool of that kind succeeded in the turn, that is worth saying out loud.

Deliberately conservative. A false alarm on a correct turn trains people
to ignore the warning, which is worse than not having one, so a claim is
only flagged when it is both confident and specific, and never when a
plausible tool did run. Hedged language ("I can remember that if you
like") is not a claim.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

#: A kind of action, the tools that really perform it, and the phrases
#: that assert it was done. Phrases are matched case-insensitively
#: against the final answer only — not the reasoning, where a model
#: talking through a plan would trip every one of them.
@dataclass(frozen=True)
class Kind:
    name: str
    tools: tuple[str, ...]
    patterns: tuple[str, ...]
    advice: str


KINDS: tuple[Kind, ...] = (
    Kind(
        "remember",
        ("memory", "memory_manage", "remember"),
        (r"\bi(?:'ve| have) (?:saved|stored|noted|remembered|made a note)",
         r"\b(?:saved|stored|added) (?:that |this |it )?to (?:my )?memory",
         r"\bi(?:'ll| will) remember (?:that|this|it)\b",
         r"\bnoted (?:that |this |it )?permanently",
         r"\bcommitted (?:that |this |it )?to memory"),
        "Nothing was written to memory. Ask again and name the memory "
        "tool, or add it yourself on the Memory page."),
    Kind(
        "schedule",
        ("cronjob_manage", "cronjob", "schedule"),
        (r"\b(?:reminder|job|task) (?:is )?(?:has been )?(?:set|scheduled|created)",
         r"\bi(?:'ve| have) (?:set|scheduled|created) (?:a |the )?(?:reminder|job|cron)",
         r"\bi(?:'ll| will) remind you\b",
         r"\bscheduled (?:it|that|this) for\b"),
        "No job was created — check the Cron page, it will be empty. The "
        "cron tool is only registered when the agent is run with someone "
        "present; if this keeps happening, say so."),
    Kind(
        "write a file",
        ("write_file", "patch", "edit_file", "create_file", "terminal",
         "execute_code"),
        # "saved" alone is ambiguous — "I have saved that to memory" is a
        # memory claim, not a file one — so a write claim must name
        # something file-shaped: the word file, or a name with a suffix.
        (r"\bi(?:'ve| have) (?:written|created|saved|updated|edited) "
         r"(?:the |a |an |your |my |it |that |to )*"
         r"(?:file|script|document|folder|directory|[\w./~-]+\.\w{1,6})\b",
         r"\bthe file (?:has been |was )(?:written|created|saved|updated)",
         r"\bfile (?:has been |was )(?:saved|created) (?:to|at|in)\b"),
        "No file was written. Check the path you expected — and remember "
        "the agent's working directory is the one shown beside IN."),
    Kind(
        "send a message",
        ("send_message", "messaging", "send", "telegram", "email"),
        (r"\bi(?:'ve| have) (?:sent|emailed|messaged)\b",
         r"\b(?:message|email) (?:has been |was )sent\b"),
        "Nothing was sent. The channel may not be connected — the Gateway "
        "page says which are."),
)

#: Phrases that turn a claim back into an offer. Checked first, because
#: "I can remember that for you" must never be read as "I remembered".
HEDGES = re.compile(
    r"\b(?:i can|i could|would you like|shall i|if you (?:want|like)|"
    r"do you want me to|i am (?:unable|not able)|i cannot|i can't|"
    r"i was unable|failed to|could not)\b", re.IGNORECASE)


@dataclass
class Claim:
    kind: str
    advice: str
    phrase: str


def _succeeded(tools: list[tuple[str, bool]], names: tuple[str, ...]) -> bool:
    """Whether any tool of this kind ran and did not report an error."""
    wanted = {n.lower() for n in names}
    for called, failed in tools:
        name = (called or "").lower()
        if failed:
            continue
        if name in wanted or any(w in name for w in wanted):
            return True
    return False


def unbacked(answer: str, tools: list[tuple[str, bool]]) -> list[Claim]:
    """Claims in ``answer`` that no successful tool call supports.

    ``tools`` is ``[(name, failed), ...]`` in call order.
    """
    text = (answer or "").strip()
    if not text:
        return []
    found: list[Claim] = []
    for kind in KINDS:
        if _succeeded(tools, kind.tools):
            continue
        for pattern in kind.patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            # Only the sentence the phrase sits in decides whether it is a
            # claim or an offer; a hedge three paragraphs away is unrelated.
            start = text.rfind(".", 0, match.start()) + 1
            end = text.find(".", match.end())
            sentence = text[start:end if end != -1 else len(text)]
            if HEDGES.search(sentence):
                continue
            found.append(Claim(kind.name, kind.advice, match.group(0).strip()))
            break
    return found


def summarise(claims: list[Claim]) -> str:
    """One line for the transcript, or empty when there is nothing to say."""
    if not claims:
        return ""
    if len(claims) == 1:
        claim = claims[0]
        return (f"It said “{claim.phrase}” but called no tool that "
                f"would {claim.kind}. {claim.advice}")
    kinds = ", ".join(c.kind for c in claims)
    return (f"It claimed to {kinds}, and called no tool that would do any "
            f"of those. Nothing outside this conversation changed.")
