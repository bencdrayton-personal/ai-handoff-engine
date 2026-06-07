import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from ai_handoff import AIAction, ActionContext, HandoffEngine

POLICY = os.path.join(os.path.dirname(__file__), "..", "policies", "default.yaml")


@pytest.fixture
def engine():
    return HandoffEngine(policy=POLICY)


def make_action(confidence=0.9, surface="assistant.test"):
    return AIAction(
        surface=surface,
        suggestion={"field": "value"},
        model_confidence=confidence,
    )


def test_high_confidence_low_impact_auto_executes(engine):
    decision = engine.decide(
        make_action(0.94),
        ActionContext(monetary_impact=87.40, reversibility="trivial"),
    )
    assert decision.tier == "S0"
    assert decision.route == "AUTO_EXECUTE"
    assert "LOG_TO_AUDIT_TRAIL" in decision.gates


def test_mid_confidence_suggests(engine):
    decision = engine.decide(
        make_action(0.72),
        ActionContext(monetary_impact=10.0, reversibility="trivial"),
    )
    assert decision.tier == "S1"
    assert decision.route == "SUGGEST_CONFIRM"


def test_irreversible_always_defers_to_reviewer(engine):
    decision = engine.decide(
        make_action(0.99),
        ActionContext(monetary_impact=1.0, reversibility="irreversible"),
    )
    assert decision.tier == "S3"
    assert decision.route == "DEFER_TO_REVIEWER"


def test_finalised_record_defers_to_reviewer(engine):
    decision = engine.decide(
        make_action(0.99),
        ActionContext(monetary_impact=1.0, reversibility="trivial", record_state="finalised"),
    )
    assert decision.tier == "S3"


def test_high_impact_defers_to_user(engine):
    decision = engine.decide(
        make_action(0.95),
        ActionContext(monetary_impact=12800.0, reversibility="trivial"),
    )
    assert decision.tier == "S2"


def test_surface_override_escalates_only(engine):
    decision = engine.decide(
        make_action(0.97, surface="assistant.outbound_send"),
        ActionContext(monetary_impact=0.0, reversibility="trivial"),
    )
    assert decision.tier == "S2"
    assert "minimum tier" in decision.reason


def test_within_role_cap_still_auto_executes(engine):
    decision = engine.decide(
        make_action(0.95),
        ActionContext(monetary_impact=480.0, reversibility="trivial", user_role="standard"),
    )
    assert decision.tier == "S0"  # 480 below both the S0 threshold and the role cap


def test_role_cap_blocks_auto_execution():
    from ai_handoff import Policy

    policy = Policy.load(POLICY)
    policy.overrides["user_roles"]["standard"]["cap_monetary_auto"] = 100
    engine = HandoffEngine(policy=policy)
    decision = engine.decide(
        make_action(0.95),
        ActionContext(monetary_impact=480.0, reversibility="trivial", user_role="standard"),
    )
    assert decision.tier == "S1"
    assert "auto-cap" in decision.reason


def test_missing_signals_fail_closed():
    engine = HandoffEngine(policy=POLICY)
    decision = engine.decide(
        AIAction(surface="assistant.test", suggestion={}, model_confidence=0.9),
        ActionContext(monetary_impact=10.0, reversibility="unknown_value"),
    )
    # Unknown reversibility cannot satisfy S0's all_of -> falls through to fail-closed
    assert decision.tier == "S2"


def test_audit_record_is_complete(engine):
    decision = engine.decide(
        make_action(0.94),
        ActionContext(monetary_impact=87.40, reversibility="trivial", org_id="ORG_1"),
    )
    record = decision.audit_record
    assert record["decision"]["policy_version"] == engine.policy.version
    assert record["surface"] == "assistant.test"
    assert record["decision"]["route"] == decision.route
