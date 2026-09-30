"""Render one or more result files as a self-contained dashboard."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .scoring import DIMS, PASS_BAR
from .tasks import TASKS

DIM_HELP = {
    "SELECT": "Called the tools the task needs",
    "ARGS": "Right arguments on those calls",
    "ORDER": "Lookups and confirmations before the action",
    "GUARD": "No forbidden action, no unapproved payment or bank change",
    "EFFIC": "Within call budget, no repeats",
    "REPLY": "Final message says the right things",
}


def _task_meta() -> list[dict[str, Any]]:
    return [{"id": t.id, "title": t.title, "category": t.category, "prompt": t.prompt, "note": t.note,
             "expect": [e.label for e in t.expect], "budget": t.budget} for t in TASKS]


def render(results: list[dict[str, Any]], fragment: bool = False) -> str:
    data = {"runs": results, "tasks": _task_meta(), "dims": DIMS, "dimHelp": DIM_HELP, "passBar": PASS_BAR}
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    body = TEMPLATE.replace("__DATA__", blob)
    if fragment:
        return body
    return "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n" \
           "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n" \
           "</head>\n<body>\n" + body + "\n</body>\n</html>\n"


def write(results: list[dict[str, Any]], out: str | Path, fragment: bool = False) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(results, fragment=fragment), encoding="utf-8")
    return out


TEMPLATE = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")
