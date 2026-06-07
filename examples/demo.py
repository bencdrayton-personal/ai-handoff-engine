"""Route a batch of sample AI actions through the handoff engine.

Run from the repository root:

    python examples/demo.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai_handoff import AIAction, ActionContext, HandoffEngine, write_audit_line

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVENTS = os.path.join(ROOT, "examples", "sample_events.json")
AUDIT_LOG = os.path.join(ROOT, "examples", "sample_audit_log.jsonl")


def main() -> None:
    engine = HandoffEngine(policy=os.path.join(ROOT, "policies", "default.yaml"))

    with open(EVENTS, "r", encoding="utf-8") as fh:
        events = json.load(fh)

    if os.path.exists(AUDIT_LOG):
        os.remove(AUDIT_LOG)

    print(f"policy version: {engine.policy.version}\n")
    for event in events:
        action = AIAction(**event["action"])
        context = ActionContext(**event["context"])
        decision = engine.decide(action, context)
        write_audit_line(decision.audit_record, AUDIT_LOG)

        print(f"  {action.surface}")
        print(f"    -> {decision.tier} {decision.route}")
        print(f"       gates:  {', '.join(decision.gates)}")
        print(f"       reason: {decision.reason}\n")

    print(f"audit log written to {os.path.relpath(AUDIT_LOG, ROOT)}")


if __name__ == "__main__":
    main()
