"""Run every task × trial against an agent and collect traces + scores."""
from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Any, Callable

from .agents import Agent
from .books import Books, Call
from .scoring import DIMS, Issue, score
from .tasks import TASKS_BY_ID, Task

VERSION = "0.3.0"


def run_one(agent: Agent, task: Task, trial: int) -> dict[str, Any]:
    books = Books.from_fixture(task.fixture)
    t0 = time.time()
    try:
        res = agent.run(task, books)
        reply, meta = res.reply, res.meta
    except Exception as exc:  # an agent crash is a result, not a harness crash
        reply, meta = "", {"crash": f"{type(exc).__name__}: {exc}"}
    meta["seconds"] = round(time.time() - t0, 2)
    s = score(task, books.trace, reply)
    if "crash" in meta:
        s.issues.insert(0, Issue("agent_crash", meta["crash"]))
    return {"task_id": task.id, "trial": trial, "trace": [asdict(c) for c in books.trace],
            "reply": reply, "meta": meta, "score": s.to_json()}


def run_suite(make_agent: Callable[[int], Agent], tasks: list[Task], trials: int = 3, concurrency: int = 4,
              label: str = "run", info: dict[str, Any] | None = None,
              on_done: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    jobs = [(t, k) for t in tasks for k in range(trials)]

    def work(job: tuple[Task, int]) -> dict[str, Any]:
        task, k = job
        seed = int(hashlib.sha1(f"{label}:{task.id}:{k}".encode()).hexdigest()[:8], 16)
        r = run_one(make_agent(seed), task, k)
        if on_done:
            on_done(r)
        return r

    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        runs = list(pool.map(work, jobs))
    return {"meta": {"label": label, "started": started, "trials": trials, "harness": VERSION, **(info or {})},
            "runs": runs, "summary": summarize(runs)}


def rescore(results: dict[str, Any]) -> dict[str, Any]:
    """Re-grade stored traces with the current task definitions (no model calls)."""
    for r in results["runs"]:
        task = TASKS_BY_ID[r["task_id"]]
        trace = [Call(**c) for c in r["trace"]]
        r["score"] = score(task, trace, r["reply"]).to_json()
    results["summary"] = summarize(results["runs"])
    return results


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    cells: dict[str, dict[str, list[float]]] = {}
    totals: dict[str, list[float]] = {}
    passes: dict[str, list[bool]] = {}
    breaks: dict[str, dict[str, Any]] = {}
    for r in runs:
        tid, sc = r["task_id"], r["score"]
        for d in DIMS:
            v = sc["dims"].get(d)
            if v is not None:
                cells.setdefault(tid, {}).setdefault(d, []).append(v)
        totals.setdefault(tid, []).append(sc["total"])
        passes.setdefault(tid, []).append(sc["passed"])
        for issue in sc["issues"]:
            if issue["kind"] == "tool_error":
                continue
            key = issue["kind"] + "|" + issue["detail"].split(":")[0]
            b = breaks.setdefault(key, {"kind": issue["kind"], "detail": issue["detail"], "count": 0, "tasks": set()})
            b["count"] += 1
            b["tasks"].add(tid)
    mean = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
    grid = {tid: {d: (round(mean(v), 3) if v else None) for d, v in ((d, cells.get(tid, {}).get(d)) for d in DIMS)}
            for tid in totals}
    task_rows = {tid: {"total": round(mean(totals[tid]), 3), "pass_rate": round(mean([float(p) for p in passes[tid]]), 3)}
                 for tid in totals}
    all_runs = [p for ps in passes.values() for p in ps]
    guard_runs = [r["score"]["dims"]["GUARD"] for r in runs]
    return {
        "grid": grid,
        "tasks": task_rows,
        "pass_rate": round(mean([float(p) for p in all_runs]), 3) if all_runs else 0.0,
        "score": round(mean([r["score"]["total"] for r in runs]), 3) if runs else 0.0,
        "guard_breaches": int(sum(1 for g in guard_runs if g == 0)),
        "runs": len(runs),
        "breaks": sorted(({**b, "tasks": sorted(b["tasks"])} for b in breaks.values()),
                         key=lambda b: (b["kind"] not in ("forbidden", "unapproved_action"), -b["count"])),
    }
