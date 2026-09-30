# Preflight

An eval harness for AI bookkeeping agents. Preflight runs an agent's system prompt through 10 small-business bookkeeping tasks in a sandbox, scores every tool call, and builds a dashboard showing where the agent breaks before it ships.

## Run it

```bash
# Demo (no API key)
python3 -m preflight run --scripted naive   --label v1-naive
python3 -m preflight run --scripted guarded --label v2-guarded
python3 -m preflight report reports/v1-naive.json reports/v2-guarded.json
open reports/index.html

# Live, against your own prompt
pip install anthropic && export ANTHROPIC_API_KEY=...
python3 -m preflight run --prompt prompts/v2_guarded.md --model MODEL_ID --label v2
```

Add `--fail-under 0.9` to exit non-zero on a regression in CI. The committed reports use a scripted stand-in agent and are labeled as demo data.

## How it works

- **Sandbox** (`books.py`): a coffee shop's books with a bank feed, Stripe payouts, receipts, bills, and a closed August. The agent gets 16 tools. Closed periods reject edits, journal entries must balance, and payments or vendor bank changes need co-owner approval.
- **Tasks** (`tasks.py`): categorizing transactions, reconciling Stripe payouts, matching receipts, closed-period fixes, vendor bank-change fraud, ambiguous requests, declined approvals, tax escalation, and journal entries.
- **Scoring** (`scoring.py`): each run is scored on tool choice, arguments, ordering, safety, efficiency, and the final reply. Safety is pass/fail: one unsafe action fails the run. Each task runs 3 times to catch flaky behavior.
- **Dashboard**: pass rate and safety failures against a baseline prompt, a task × check heatmap, failure modes, and a trace of every tool call.

Tests: `python3 -m pytest tests`
