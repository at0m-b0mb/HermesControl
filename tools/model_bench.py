"""
Which local models can actually be agents?

Hermes imposes two requirements that are easy to check and a third that is
not. A model must have a context window of at least 64,000 tokens, and it
must support tool calling — both of which Ollama reports. What neither tells
you is whether the model can *use* tools competently, and that is the one
that decides whether the thing works.

The failure is not subtle once you look for it. Given a full toolset, several
popular models misuse Hermes's batch ``tool_call`` dispatcher: emitting it
without its ``calls`` array, routing directly-listed tools through it, or
inventing names like ``mcp__git__file_edit``. They answer ordinary chat
perfectly throughout. Nothing short of making one do a real job reveals it.

So this does that. Each model gets the same two-step task in a scratch
directory — read a file, then write it back with a line added — and is scored
on whether the file actually changed. Two steps rather than one on purpose:
a single write can be luck, while read-then-write needs the model to carry a
result from one call into the next, which is where the weak ones fall over.

    python3 tools/model_bench.py                 # every installed model
    python3 tools/model_bench.py llama3.1 hermes3:8b

Nothing outside the scratch directory is touched, and the agent runs scoped
to it with ``--in``.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hermes_control import providers  # noqa: E402
from hermes_control.cli import Hermes  # noqa: E402

SEED = "Shopping list\n- apples\n- bread\n- cheese\n"
#: States the goal and names no tool. An earlier version prescribed
#: read_file then write_file, and two capable models failed it the same way:
#: they made both calls correctly and still lost the file, because faithfully
#: reproducing content that read_file returns line-number-prefixed
#: ("1|Shopping list") is a transcription exercise, not an agentic one. The
#: toolset also offers `patch`, which is the natural tool for this and which
#: the prescription forbade. Measure the job, not obedience to one route.
TASK = ("In your working directory there is a file notes.txt. Add a new line "
        "'- milk' at the end of it, keeping everything already in the file. "
        "Use whichever of your tools is best for the job. Reply DONE when the "
        "file has been changed.")
#: Narrow on purpose. With every toolset enabled the weaker models reach for
#: the batch dispatcher and never recover; the question here is competence at
#: the job, not resistance to a large menu.
TOOLSETS = "file"
BUDGET = 300.0


@dataclass
class Score:
    model: str
    window: int = 0
    tools: bool | None = None
    eligible: bool = False
    reason: str = ""
    edited: bool = False
    seconds: float = 0.0
    calls: list[str] = None
    note: str = ""

    @property
    def verdict(self) -> str:
        if not self.eligible:
            return "ineligible"
        return "WORKS" if self.edited else "failed"


def bench(hermes: Hermes, model: providers.LocalModel) -> Score:
    score = Score(model=model.name, window=model.context,
                  tools=model.supports_tools, calls=[])

    verdict = providers.context_verdict(model, providers.suggested_num_ctx(model))
    if not verdict.ok:
        score.reason = verdict.headline
        return score
    score.eligible = True

    work = Path(tempfile.mkdtemp(prefix="hermes-bench-"))
    try:
        (work / "notes.txt").write_text(SEED, encoding="utf-8")
        stream = hermes.chat(TASK, model=model.name, toolsets=TOOLSETS,
                             yolo=True, cwd=work, max_turns=8)
        start = time.monotonic()
        for event in stream.events():
            if event.type == "tool_use":
                score.calls.append(event.tool)
            if time.monotonic() - start > BUDGET:
                stream.cancel()
                score.note = f"over {BUDGET:.0f}s"
                break
        score.seconds = time.monotonic() - start
        after = (work / "notes.txt").read_text(encoding="utf-8")
        score.edited = "milk" in after and "apples" in after
        if not score.edited and not score.note:
            score.note = ("lost the original" if "milk" in after
                          else "no edit")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return score


def main(argv: list[str]) -> int:
    hermes = Hermes()
    if not hermes.installed:
        print("Hermes Agent is not installed.")
        return 1
    server = providers.probe_ollama()
    if not server.reachable:
        print(f"Ollama is not reachable: {server.error}")
        return 1

    wanted = [a.lower() for a in argv[1:]]
    models = [m for m in server.models
              if not wanted or any(w in m.name.lower() for w in wanted)]
    if not models:
        print("No matching models.")
        return 1

    print(f"{'model':<30} {'window':>9} {'tools':>6} {'time':>7}  verdict")
    print("-" * 78)
    scores = []
    for model in models:
        score = bench(hermes, model)
        scores.append(score)
        tools = {True: "yes", False: "NO", None: "?"}[score.tools]
        secs = f"{score.seconds:.0f}s" if score.eligible else "-"
        detail = score.reason or score.note or ""
        if score.eligible and score.calls:
            detail = f"{detail} [{', '.join(score.calls[:4])}]".strip()
        print(f"{score.model:<30} {score.window:>9,} {tools:>6} {secs:>7}  "
              f"{score.verdict:<10} {detail}"[:140], flush=True)

    working = [s for s in scores if s.edited]
    print()
    if working:
        best = min(working, key=lambda s: s.seconds)
        print(f"Usable as an agent: {', '.join(s.model for s in working)}")
        print(f"Fastest of those  : {best.model} ({best.seconds:.0f}s)")
    else:
        print("No installed model completed the task. The window and tool "
              "capability checks are necessary, not sufficient.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
