#!/usr/bin/env python3
"""
Does this model actually use its tools?

Not *does it have* tools — the Console's briefing answers that from the
schemas Hermes reports sending. This asks the harder question: when told
to do something, does the model reach for the right tool and does the
world change as a result.

Every check is scored on an effect, never on what the model said about
it. A model that replies "I have created the file" and creates nothing
fails here, which is the whole point: that answer is indistinguishable
from success in a transcript and is the commonest way a weak local model
looks like it is working.

    python3 tools/tool_check.py            # every check
    python3 tools/tool_check.py write read # or some
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hermes_control.cli import Hermes  # noqa: E402


@dataclass
class Check:
    name: str
    prompt: str
    #: Files to lay down before the turn.
    seed: dict[str, str] = field(default_factory=dict)
    #: Given the directory, did the world change as it should have?
    verify: object = None
    #: Tools we expect to see called. Informational: a model that gets the
    #: effect right by another route still passes.
    expect: tuple[str, ...] = ()


CHECKS: list[Check] = [
    Check(
        "write",
        "Create a file called hello.txt containing exactly the word "
        "ORANGE. Use your file tools.",
        verify=lambda d: (d / "hello.txt").exists()
        and "ORANGE" in (d / "hello.txt").read_text(),
        expect=("write_file",)),
    Check(
        "read",
        "Read colour.txt and reply with only the word it contains.",
        seed={"colour.txt": "VERMILION\n"},
        verify=lambda d, answer="": "vermilion" in answer.lower(),  # noqa: ARG005
        expect=("read_file",)),
    Check(
        "edit",
        "Read list.txt and write it back with a fourth line that says "
        "delta. Keep the first three lines exactly as they are.",
        seed={"list.txt": "alpha\nbravo\ncharlie\n"},
        verify=lambda d: [ln.strip() for ln in
                          (d / "list.txt").read_text().splitlines()
                          if ln.strip()] == ["alpha", "bravo", "charlie",
                                             "delta"],
        expect=("read_file", "write_file")),
    Check(
        "search",
        "Find which file in this directory contains the word NEEDLE, then "
        "write that file's name into found.txt.",
        seed={"a.txt": "nothing here\n", "b.txt": "a NEEDLE in here\n",
              "c.txt": "nor here\n"},
        verify=lambda d: (d / "found.txt").exists()
        and "b.txt" in (d / "found.txt").read_text(),
        expect=("search_files", "write_file")),
    Check(
        "shell",
        "Use your terminal tool to count the lines in big.txt, and write "
        "just that number into count.txt.",
        seed={"big.txt": "\n".join(f"line {i}" for i in range(1, 43)) + "\n"},
        verify=lambda d: (d / "count.txt").exists()
        and "42" in (d / "count.txt").read_text(),
        expect=("execute_code", "terminal")),
]


def run(check: Check, hermes: Hermes, timeout: float = 300.0) -> dict:
    """Run one check in a throwaway directory.

    ``timeout`` is enforced here rather than passed to Hermes: a chat is
    a stream, not a call that returns, so the bound has to be applied to
    the loop that reads it. Without this a model that stalls mid-turn
    hangs the whole run with nothing to say about why.
    """
    with TemporaryDirectory(prefix=f"toolcheck-{check.name}-") as tmp:
        d = Path(tmp)
        for name, body in check.seed.items():
            (d / name).write_text(body)
        started = time.monotonic()
        calls: list[str] = []
        answer = ""
        error = ""
        stream = hermes.chat(check.prompt, cwd=d)
        timed_out = False
        for event in stream.events():
            if time.monotonic() - started > timeout:
                timed_out = True
                stream.cancel()
                break
            if event.type == "tool_use":
                calls.append(event.tool)
            elif event.type == "text":
                answer += event.text
            elif event.type == "result":
                error = event.error or ""
        took = time.monotonic() - started
        try:
            verify = check.verify
            passed = bool(
                verify(d, answer) if verify.__code__.co_argcount > 1
                else verify(d))
        except Exception as exc:                       # noqa: BLE001
            passed, error = False, f"{type(exc).__name__}: {exc}"
        if timed_out:
            passed = False
            error = f"gave up after {timeout:.0f}s"
        return {"name": check.name, "passed": passed, "calls": calls,
                "seconds": took, "error": error,
                "answer": answer.strip()[:80]}


def main(argv: list[str]) -> int:
    wanted = set(argv[1:])
    checks = [c for c in CHECKS if not wanted or c.name in wanted]
    hermes = Hermes()
    if not hermes.installed:
        print("Hermes Agent is not installed.")
        return 2
    model = hermes.config_value("model.default") or "?"
    print(f"model: {model}\n")
    print(f"{'check':10} {'result':8} {'time':>7}  tools called")
    print("-" * 72)
    results = []
    for check in checks:
        outcome = run(check, hermes)
        results.append(outcome)
        mark = "PASS" if outcome["passed"] else "FAIL"
        called = ", ".join(outcome["calls"]) or "none"
        print(f"{check.name:10} {mark:8} {outcome['seconds']:6.1f}s  {called}")
        if not outcome["passed"]:
            detail = outcome["error"] or outcome["answer"] or "no effect"
            print(f"{'':10} {'':8} {'':7}  -> {detail[:70]}")
    passed = sum(1 for r in results if r["passed"])
    print("-" * 72)
    print(f"{passed} of {len(results)} checks passed.")
    if passed < len(results):
        print("A failed check means the world did not change, whatever the "
              "model said about it.")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
