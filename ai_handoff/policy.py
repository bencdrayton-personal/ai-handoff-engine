"""Policy loading and evaluation.

The YAML policy file is the substantive artefact. This module only
interprets it. Evaluation is deliberately conservative:

- Tiers are checked from most restrictive (S3) to least (S0).
  The first restrictive tier whose conditions match wins.
- S0 (auto-execute) requires *all* of its conditions to hold.
- A missing or unparseable signal never satisfies a permissive
  condition: when in doubt, the engine defers (S2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import yaml

TIER_ORDER = {"S0": 0, "S1": 1, "S2": 2, "S3": 3}
TIER_ROUTES = {
    "S0": "AUTO_EXECUTE",
    "S1": "SUGGEST_CONFIRM",
    "S2": "DEFER_TO_USER",
    "S3": "DEFER_TO_REVIEWER",
}
FAIL_CLOSED_TIER = "S2"


def _check(value: Any, condition: Any) -> bool:
    """Evaluate one named condition against a signal value.

    Supported condition forms:
        ">= 0.85", "> 10", "< 500", "<= 5000"   numeric comparison
        "0.65..0.85"                            inclusive numeric range
        ["trivial", "moderate"]                 categorical membership
        True / False                            boolean equality
    """
    if value is None:
        return False
    if isinstance(condition, bool):
        return bool(value) is condition
    if isinstance(condition, list):
        return value in condition
    if isinstance(condition, str):
        text = condition.strip()
        if ".." in text:
            lo, hi = (float(part) for part in text.split(".."))
            return lo <= float(value) <= hi
        for op in (">=", "<=", ">", "<", "=="):
            if text.startswith(op):
                bound = float(text[len(op):])
                v = float(value)
                return {
                    ">=": v >= bound,
                    "<=": v <= bound,
                    ">": v > bound,
                    "<": v < bound,
                    "==": v == bound,
                }[op]
    raise ValueError(f"Unsupported condition: {condition!r}")


def _describe(signal: str, value: Any, condition: Any) -> str:
    if isinstance(value, float):
        value = f"{value:g}"
    return f"{signal} {value} matches {condition!r}"


@dataclass
class Policy:
    version: str
    tiers: dict[str, dict]            # tier name -> {conditions, required_gates}
    overrides: dict[str, dict]
    raw: dict

    @classmethod
    def load(cls, path: str) -> "Policy":
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        return cls(
            version=str(raw.get("version", "unversioned")),
            tiers=raw.get("risk_tiers", {}),
            overrides=raw.get("overrides", {}),
            raw=raw,
        )

    def evaluate(self, signals: dict[str, Any]) -> tuple[str, list[str]]:
        """Return (tier, reasons). Most restrictive matching tier wins."""
        # Restrictive tiers first: any_of semantics.
        for tier in ("S3", "S2", "S1"):
            spec = self.tiers.get(tier, {})
            matched = self._match_any(spec.get("conditions", {}), signals)
            if matched:
                return tier, matched

        # S0 last: all_of semantics, fail closed on any miss.
        s0 = self.tiers.get("S0", {})
        matched = self._match_all(s0.get("conditions", {}), signals)
        if matched is not None:
            return "S0", matched

        return FAIL_CLOSED_TIER, ["no tier conditions matched; failing closed"]

    def _match_any(
        self, conditions: dict, signals: dict[str, Any]
    ) -> list[str]:
        reasons = []
        for signal, condition in conditions.get("any_of", {}).items():
            try:
                if _check(signals.get(signal), condition):
                    reasons.append(_describe(signal, signals.get(signal), condition))
            except (ValueError, TypeError):
                continue  # unreadable signal cannot trigger a tier by itself
        return reasons

    def _match_all(
        self, conditions: dict, signals: dict[str, Any]
    ) -> Optional[list[str]]:
        reasons = []
        for signal, condition in conditions.get("all_of", {}).items():
            value = signals.get(signal)
            try:
                if not _check(value, condition):
                    return None
            except (ValueError, TypeError):
                return None
            reasons.append(_describe(signal, value, condition))
        return reasons if reasons else None

    def gates_for(self, tier: str) -> list[str]:
        return list(self.tiers.get(tier, {}).get("required_gates", []))

    def surface_minimum(self, surface: str) -> Optional[str]:
        return (
            self.overrides.get("surfaces", {})
            .get(surface, {})
            .get("minimum_tier")
        )

    def role_auto_cap(self, role: str) -> Optional[float]:
        cap = (
            self.overrides.get("user_roles", {})
            .get(role, {})
            .get("cap_monetary_auto")
        )
        return float(cap) if cap is not None else None
