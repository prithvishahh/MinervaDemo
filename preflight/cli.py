"""preflight: run canned bookkeeping tasks against an agent prompt and see where it breaks.

  python -m preflight run --scripted naive --label v1-naive       # offline demo
  python -m preflight run --prompt prompts/v2_guarded.md --model MODEL_ID --label v2
  python -m preflight report reports/v1-naive.json reports/v2.json
  python -m preflight rescore reports/v2.json                     # re-grade stored traces, no API calls
  python -m preflight tasks
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
from pathlib import Path

from . import report
from .agents import PROFILES, LiveAgent, ScriptedAgent
from .runner import rescore, run_suite
from .scoring import DIMS
from .tasks import TASKS, TASKS_BY_ID

TTY = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _bg(v: float | None, guard: bool) -> str:
    if v is None:
        return "\033[48;5;236m\033[38;5;244m   ·  \033[0m" if TTY else "   .  "
    txt = f"{round(v * 100):>5} "
    if not TTY:
        return txt
    if guard and v < 1:
        code = 160
    else:
        code = 160 if v < .4 else 166 if v < .6 else 178 if v < .8 else 65 if v < .95 else 29
    return f"\033[48;5;{code}m\033[38;5;231m{txt}\033[0m"


def print_heatmap(res: dict) -> None:
    s = res["summary"]
    print(f"\n  {res['meta']['label']}  ·  {res['meta']['agent']}  ·  {s['runs']} runs")
    print("  " + " " * 26 + "".join(f"{d:>6}" for d in DIMS) + "  pass")
    for t in TASKS:
        if t.id not in s["grid"]:
            continue
        row = "".join(_bg(s["grid"][t.id][d], d == "GUARD") for d in DIMS)
        print(f"  {t.id} {t.title[:21]:<21} {row}  {round(s['tasks'][t.id]['pass_rate'] * 100):>3}%")
    verdict = "CLEARED" if s["guard_breaches"] == 0 and s["pass_rate"] >= 0.9 else "HOLD"
    print(f"\n  pass rate {s['pass_rate']:.0%}   score {s['score']:.2f}   guard breaches {s['guard_breaches']}   -> {verdict}")
    crit = [b for b in s["breaks"] if b["kind"] in ("forbidden", "unapproved_action")]
    for b in crit[:5]:
        print(f"   x{b['count']:<3} {b['detail'][:96]}  [{', '.join(b['tasks'])}]")


def cmd_run(a: argparse.Namespace) -> int:
    tasks = [TASKS_BY_ID[x.strip().upper()] for x in a.tasks.split(",")] if a.tasks else TASKS
    info: dict = {}
    if a.scripted:
        make = lambda seed: ScriptedAgent(a.scripted, seed=seed)  # noqa: E731
        info.update(agent=f"scripted:{a.scripted}", prompt_sha=None)
    else:
        if not a.prompt:
            print("pass --prompt FILE (or --scripted PROFILE for an offline demo)", file=sys.stderr)
            return 2
        if not a.model:
            print("pass --model MODEL_ID for a live run", file=sys.stderr)
            return 2
        text = Path(a.prompt).read_text(encoding="utf-8")
        agent = LiveAgent(text, model=a.model, effort=a.effort, max_turns=a.max_turns)
        make = lambda seed: agent  # noqa: E731  (stateless per run; books are fresh each time)
        info.update(agent=a.model, effort=a.effort, prompt_file=a.prompt,
                    prompt_sha=hashlib.sha256(text.encode()).hexdigest()[:10])

    total, done, lock = len(tasks) * a.trials, [0], threading.Lock()

    def tick(r: dict) -> None:
        with lock:
            done[0] += 1
            mark = "." if r["score"]["passed"] else ("!" if r["score"]["dims"]["GUARD"] == 0 else "x")
            print(mark, end="" if done[0] < total else f"  {total} runs\n", flush=True)

    label = a.label or (Path(a.prompt).stem if a.prompt else a.scripted)
    res = run_suite(make, tasks, trials=a.trials, concurrency=a.concurrency, label=label, info=info, on_done=tick)
    out = Path(a.out or f"reports/{label}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print_heatmap(res)
    html = report.write([res], out.with_suffix(".html"))
    print(f"\n  results  {out}\n  report   {html}")
    if a.fail_under is not None and (res["summary"]["pass_rate"] < a.fail_under or res["summary"]["guard_breaches"]):
        print(f"  FAILED gate: pass rate {res['summary']['pass_rate']:.0%} < {a.fail_under:.0%} or guard breaches > 0")
        return 1
    return 0


def cmd_report(a: argparse.Namespace) -> int:
    results = [json.loads(Path(p).read_text(encoding="utf-8")) for p in a.files]
    for r in results:
        print_heatmap(r)
    out = report.write(results, a.out, fragment=a.fragment)
    print(f"\n  report   {out}")
    return 0


def cmd_rescore(a: argparse.Namespace) -> int:
    p = Path(a.file)
    res = rescore(json.loads(p.read_text(encoding="utf-8")))
    p.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print_heatmap(res)
    return 0


def cmd_tasks(_: argparse.Namespace) -> int:
    for t in TASKS:
        print(f"{t.id}  {t.category:<16} {t.title:<24} \"{t.prompt}\"")
        print(f"     expects {' -> '.join(e.label for e in t.expect)}; forbids {len(t.forbid)}; budget {t.budget}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="preflight", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run the task suite")
    r.add_argument("--prompt", help="system prompt file for the agent under test")
    r.add_argument("--scripted", choices=sorted(PROFILES), help="use the offline scripted agent instead of a model")
    r.add_argument("--label")
    r.add_argument("--model", help="model id for live runs (required with --prompt)")
    r.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    r.add_argument("--trials", type=int, default=3)
    r.add_argument("--tasks", help="comma-separated task ids, e.g. T02,T05")
    r.add_argument("--concurrency", type=int, default=4)
    r.add_argument("--max-turns", type=int, default=12)
    r.add_argument("--out", help="results JSON path (default reports/<label>.json)")
    r.add_argument("--fail-under", type=float, help="exit 1 if pass rate is below this or any guard breach (for CI)")
    r.set_defaults(fn=cmd_run)

    rp = sub.add_parser("report", help="build a comparison heatmap from result files")
    rp.add_argument("files", nargs="+")
    rp.add_argument("-o", "--out", default="reports/index.html")
    rp.add_argument("--fragment", action="store_true", help="emit without <html>/<head> wrapper")
    rp.set_defaults(fn=cmd_report)

    rs = sub.add_parser("rescore", help="re-grade stored traces with the current task definitions")
    rs.add_argument("file")
    rs.set_defaults(fn=cmd_rescore)

    sub.add_parser("tasks", help="list the tasks").set_defaults(fn=cmd_tasks)

    a = ap.parse_args(argv)
    return a.fn(a)
