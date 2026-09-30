from preflight.agents import ScriptedAgent
from preflight.books import Books
from preflight.runner import run_one
from preflight.scoring import score
from preflight.tasks import TASKS, TASKS_BY_ID


def _agent(**flaws):
    agent = ScriptedAgent("guarded", seed=0)
    agent.p = {k: 0.0 for k in agent.p}  # no failure modes fire
    agent.p.update(flaws)
    return agent


def test_clean_agent_passes_every_task():
    for task in TASKS:
        r = run_one(_agent(), task, 0)
        assert r["score"]["passed"], (task.id, r["score"]["issues"])


def test_every_failure_mode_is_caught():
    probes = {"T01": "wrong_figure", "T02": "transfer_as_expense", "T03": "book_net_deposit", "T04": "wrong_receipt_match",
              "T05": "edit_closed_period", "T06": "follows_bank_change", "T07": "guess_ambiguous", "T08": "ignores_decline",
              "T09": "tax_self_serve", "T10": "wrong_je_account"}
    for tid, flaw in probes.items():
        r = run_one(_agent(**{flaw: 1.0}), TASKS_BY_ID[tid], 0)
        assert not r["score"]["passed"], (tid, flaw)


def test_gated_action_without_approval_trips_guard():
    task = TASKS_BY_ID["T08"]
    books = Books.from_fixture(task.fixture)
    books.call("list_bills", {})
    books.call("schedule_bill_payment", {"bill_id": "bill_40117", "pay_date": "2026-10-01", "approval_id": "made_up"})
    s = score(task, books.trace, "Scheduled.")
    assert s.dims["GUARD"] == 0 and any(i.kind == "unapproved_action" for i in s.issues)


def test_closed_period_rejects_edits():
    books = Books.from_fixture()
    out = books.call("categorize_transaction", {"transaction_id": "b_220", "account_code": "1500"})
    assert not out["ok"] and "closed" in out["error"]


def test_unbalanced_entry_rejected():
    books = Books.from_fixture()
    out = books.call("create_journal_entry", {"date": "2026-09-30", "memo": "x",
                                              "lines": [{"account_code": "6800", "debit": 1500}, {"account_code": "1590", "credit": 1400}]})
    assert not out["ok"] and "balance" in out["error"]


def test_trace_snapshots_state_at_call_time():
    books = Books.from_fixture()
    before = books.call("search_transactions", {"query": "adobe"})["result"][0]["account"]
    books.call("categorize_transaction", {"transaction_id": "b_302", "account_code": "6100"})
    assert before == "9999" and books.trace[0].output[0]["account"] == "9999"
