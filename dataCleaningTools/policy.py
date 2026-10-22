"""
Deterministic risk / approval policy for Agent 2.

The LLM may propose steps; this module decides what is allowed to run
without human approval. The LLM cannot bypass these rules by choosing
a different tool name.
"""

from __future__ import annotations

from typing import Dict, Set

from .models import RiskLevel, TransformationStep


# Operations that are never auto-executed
CRITICAL_OPS: Set[str] = {
    "drop_column",
    "overwrite_source",
    "delete_file",
}

# Default risk by operation name (overridden by step.risk_level if higher)
OP_RISK: Dict[str, RiskLevel] = {
    "trim_whitespace": RiskLevel.LOW,
    "normalize_values": RiskLevel.LOW,
    "convert_data_types": RiskLevel.MODERATE,
    "clean_numeric_string": RiskLevel.MODERATE,
    "handle_missing_values": RiskLevel.MODERATE,
    "remove_duplicates": RiskLevel.MODERATE,
    "drop_column": RiskLevel.HIGH,
    "run_sandbox_code": RiskLevel.HIGH,
}


_RISK_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MODERATE: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}


def effective_risk(step: TransformationStep) -> RiskLevel:
    base = OP_RISK.get(step.operation, RiskLevel.MODERATE)
    if _RISK_ORDER[step.risk_level] > _RISK_ORDER[base]:
        return step.risk_level
    return base


def requires_approval(step: TransformationStep) -> bool:
    if step.operation in CRITICAL_OPS:
        return True
    if step.requires_approval:
        return True
    risk = effective_risk(step)
    if risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
        return True
    # Imputation that drops rows is higher stakes
    if step.operation == "handle_missing_values":
        strategy = (step.parameters or {}).get("strategy", "")
        if strategy in ("drop_rows", "drop_columns"):
            return True
    return False


def is_forbidden(step: TransformationStep) -> bool:
    """Hard deny — do not run even with approval (agent must redesign)."""
    if step.operation in ("overwrite_source", "delete_file"):
        return True
    if effective_risk(step) == RiskLevel.CRITICAL and step.operation in CRITICAL_OPS:
        # still allow drop_column *with* approval; only true critical forbidden
        return step.operation in ("overwrite_source", "delete_file")
    return False


def apply_policy(step: TransformationStep) -> TransformationStep:
    """Return a copy of the step with requires_approval reconciled to policy."""
    forbidden = is_forbidden(step)
    need = requires_approval(step)
    risk = effective_risk(step)
    return step.model_copy(
        update={
            "requires_approval": need or forbidden,
            "risk_level": risk,
            "preconditions": list(step.preconditions)
            + (["FORBIDDEN_BY_POLICY"] if forbidden else []),
        }
    )