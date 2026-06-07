"""AI Handoff Engine.

Routes any AI-generated action to one of four risk tiers:

    S0  AUTO_EXECUTE       AI acts; user informed via audit trail only
    S1  SUGGEST_CONFIRM    AI suggests; user confirms with one click
    S2  DEFER_TO_USER      AI provides input; user completes the action
    S3  DEFER_TO_REVIEWER  AI cannot act; routed to a qualified reviewer

The routing logic lives in a versioned YAML policy file, not in code.
Evaluation is fail-closed: most restrictive tier wins, missing signals
defer to a human, and overrides may only escalate, never relax.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .policy import Policy, TIER_ORDER, TIER_ROUTES


@dataclass
class AIAction:
    """An action proposed by any AI surface."""

    surface: str                      # e.g. "assistant.transaction_categorisation"
    suggestion: dict[str, Any]        # the AI's proposed change, as data
    model_confidence: float           # 0.0 - 1.0
    explanation: str = ""             # model's own reasoning, for the audit record


@dataclass
class ActionContext:
    """The business context the action would land in."""

    monetary_impact: float = 0.0
    reversibility: str = "moderate"   # trivial | moderate | hard | irreversible
    record_state: str = "open"        # open | locked | finalised
    user_role: str = "standard"       # standard | elevated | reviewer
    org_id: str = ""
    user_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def signals(self) -> dict[str, Any]:
        base = {
            "model_confidence": None,  # filled by engine from the action
            "monetary_impact": self.monetary_impact,
            "reversibility": self.reversibility,
            "record_state": self.record_state,
            "user_role": self.user_role,
        }
        base.update(self.extra)
        return base


@dataclass
class Decision:
    tier: str                         # "S0" | "S1" | "S2" | "S3"
    route: str                        # e.g. "AUTO_EXECUTE"
    gates: list[str]                  # required side-effects, e.g. LOG_TO_AUDIT_TRAIL
    reason: str                       # named conditions, human readable
    policy_version: str
    audit_record: dict[str, Any]


class HandoffEngine:
    def __init__(self, policy: str | Policy):
        self.policy = policy if isinstance(policy, Policy) else Policy.load(policy)

    def decide(self, action: AIAction, context: ActionContext) -> Decision:
        signals = context.signals()
        signals["model_confidence"] = action.model_confidence

        tier, reasons = self.policy.evaluate(signals)

        # Per-surface override: escalation only.
        surface_min = self.policy.surface_minimum(action.surface)
        if surface_min and TIER_ORDER[surface_min] > TIER_ORDER[tier]:
            tier = surface_min
            reasons.append(f"surface '{action.surface}' minimum tier {surface_min}")

        # Per-role monetary cap on auto-execution: escalation only.
        cap = self.policy.role_auto_cap(context.user_role)
        if tier == "S0" and cap is not None and context.monetary_impact > cap:
            tier = "S1"
            reasons.append(
                f"impact {context.monetary_impact:g} exceeds role "
                f"'{context.user_role}' auto-cap {cap:g}"
            )

        gates = self.policy.gates_for(tier)
        decision = Decision(
            tier=tier,
            route=TIER_ROUTES[tier],
            gates=gates,
            reason="; ".join(reasons),
            policy_version=self.policy.version,
            audit_record={},
        )
        decision.audit_record = self._audit_record(action, context, decision)
        return decision

    @staticmethod
    def _audit_record(
        action: AIAction, context: ActionContext, decision: Decision
    ) -> dict[str, Any]:
        return {
            "audit_id": f"aho_{uuid.uuid4().hex[:12]}",
            "ts_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "org_id": context.org_id,
            "user_id": context.user_id,
            "user_role": context.user_role,
            "surface": action.surface,
            "ai_suggestion": action.suggestion,
            "model_confidence": action.model_confidence,
            "model_explanation": action.explanation,
            "monetary_impact": context.monetary_impact,
            "reversibility": context.reversibility,
            "record_state": context.record_state,
            "decision": {
                "route": decision.route,
                "tier": decision.tier,
                "gates_applied": decision.gates,
                "policy_version": decision.policy_version,
                "reason": decision.reason,
            },
        }


def write_audit_line(record: dict[str, Any], path: str) -> None:
    """Append one audit record as a JSON line."""
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")
