# AI Handoff Engine

A small, runnable policy engine that answers the central operational question for AI inside regulated software: **for any given AI-generated action, should the system act, suggest, or defer?**

Most AI failures in production are not model failures. They are *action* failures: the AI was right but acted when it should have asked; or it was wrong and the system auto-applied the output with no audit trail; or it deferred to a human on something the user wanted executed silently. The handoff decision is usually implicit, scattered across feature codepaths, and re-litigated for every launch.

This engine encodes that decision in one reviewable place.

## How it works

Every AI action is routed to one of four risk tiers:

| Tier | Route | Meaning |
|------|-------|---------|
| S0 | `AUTO_EXECUTE` | AI acts; user informed via audit trail only |
| S1 | `SUGGEST_CONFIRM` | AI suggests; user confirms with one click |
| S2 | `DEFER_TO_USER` | AI provides input; user completes the action |
| S3 | `DEFER_TO_REVIEWER` | AI cannot act; routed to a qualified reviewer |

The routing is driven by named signals — model confidence, monetary impact, reversibility, record state — evaluated against a **versioned YAML policy file**. The policy file is the substantive artefact: it is the organisation's institutional position on when AI may act, in a form a compliance officer, an auditor, or a regulator can read.

```python
from ai_handoff import HandoffEngine, AIAction, ActionContext

engine = HandoffEngine(policy="policies/default.yaml")

action = AIAction(
    surface="assistant.transaction_categorisation",
    suggestion={"category": "Office Supplies", "tax_code": "GST"},
    model_confidence=0.94,
    explanation="Merchant pattern matches 47 prior categorisations",
)
context = ActionContext(
    monetary_impact=87.40,
    reversibility="trivial",   # trivial | moderate | hard | irreversible
    record_state="open",       # open | locked | finalised
    user_role="standard",      # standard | elevated | reviewer
)

decision = engine.decide(action, context)
# decision.route  -> "AUTO_EXECUTE"
# decision.tier   -> "S0"
# decision.gates  -> ["LOG_TO_AUDIT_TRAIL"]
# decision.reason -> "confidence 0.94 >= 0.85; impact 87.40 < 500; reversibility trivial; record open"
```

Every decision produces a complete audit record (JSON), including the policy version that produced it.

## Design choices that matter

**The decision is not a composite score.** It is a tier assignment whose conditions are all-of / any-of combinations of named signals. Audit defensibility depends on the reasoning being recoverable as a small set of readable conditions. A reviewer can read the YAML. A reviewer cannot cross-examine a 0.91.

**Fail closed.** If no tier matches, or a signal is missing, the engine defers to a human. Uncertainty about the policy is itself a reason not to act.

**Escalation only.** Per-surface and per-role overrides can make the engine *more* conservative, never less. An override cannot grant auto-execution that the base policy denies.

**Promotion is a product process.** Moving a surface from suggest to auto-act is a policy change: edit the YAML, peer-review it, version it, monitor against the audit log. No feature code changes.

## Run it

```bash
pip install -r requirements.txt
python examples/demo.py          # routes sample events, writes examples/sample_audit_log.jsonl
python -m pytest tests/ -q       # unit tests
```

## Layout

```
ai_handoff/        engine + policy evaluation
policies/          versioned YAML policy files (the real artefact)
examples/          runnable demo + sample events + committed sample audit log
tests/             unit tests
```

## Status

A working proof of concept built to make AI governance discussion concrete: small on purpose, dependency-light (PyYAML only), and designed so the policy file — not the code — is where the organisation's judgement lives.

MIT licensed. Built by [Ben Drayton](https://www.linkedin.com/in/ben-drayton).
