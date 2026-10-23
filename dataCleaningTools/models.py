"""
Shared contracts for BiFlow Agent 2 (Data Cleaning & ETL).

Agent 1 input schema matches the real profiling report (schema_version 2.1).
Agent 2 internal models cover planning, execution, validation and hand-off.

Every inference from an LLM must be labeled as a hypothesis and
supported by observable evidence — never treated as established fact.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    NONE = "NONE"
    INFO = "info"
    LOW = "low"
    MEDIUM = "MEDIUM"      # Agent 1 uses uppercase
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @classmethod
    def _missing_(cls, value: object):
        """Accept mixed-case values from Agent 1 or internal code."""
        if isinstance(value, str):
            upper = value.upper()
            for member in cls:
                if member.value.upper() == upper:
                    return member
            lower = value.lower()
            for member in cls:
                if member.value.lower() == lower:
                    return member
        return None


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskLevel(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class TransformationStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ValidationStatus(str, Enum):
    PASSED = "passed"
    PARTIAL = "partial"
    FAILED = "failed"
    NOT_RUN = "not_run"


class DatasetStatus(str, Enum):
    ORIGINAL = "original"          # V0 – immutable
    WORKING = "working"            # intermediate version
    VALIDATED = "validated"        # final, ready for hand-off
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Dataset reference (Agent 2 versioning — never pass full datasets through LLM)
# ---------------------------------------------------------------------------

class DatasetReference(BaseModel):
    """Lightweight pointer to a managed dataset version."""
    dataset_id: str = Field(default_factory=lambda: str(uuid4()))
    version: str = Field(..., description="e.g. 'V0', 'V1', 'V2'")
    path: str = Field(..., description="Filesystem path or URI")
    format: str = Field(default="csv", description="csv | parquet | excel | ...")
    row_count: Optional[int] = None
    column_count: Optional[int] = None
    columns: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    parent_version: Optional[str] = None
    status: DatasetStatus = DatasetStatus.WORKING
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "ignore"}


# ===========================================================================
# Agent 1 → Agent 2  (schema_version 2.1 — matches real profiler output)
# ===========================================================================

class Agent1DatasetRef(BaseModel):
    """dataset_ref block as emitted by Agent 1."""
    file_path: str
    file_name: str
    rows: int
    columns: int
    size_bytes: Optional[int] = None

    model_config = {"extra": "ignore"}


class HealthScores(BaseModel):
    overall: float = 0.0
    completeness: float = 0.0
    validity: float = 0.0
    uniqueness: float = 0.0
    consistency: float = 0.0

    model_config = {"extra": "ignore"}


class ColumnIssue(BaseModel):
    """Single issue inside a column_profile."""
    issue_id: str
    source: str = "python"                     # python | llm | sandbox
    severity: str = "MEDIUM"
    description: str = ""
    evidence: Dict[str, Any] = Field(default_factory=dict)
    llm_agreement: Optional[str] = None

    model_config = {"extra": "ignore"}


class NumericStats(BaseModel):
    mean: Optional[float] = None
    median: Optional[float] = None
    std: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None
    q1: Optional[float] = None
    q3: Optional[float] = None
    skewness: Optional[float] = None
    zeros_count: Optional[int] = None
    negative_count: Optional[int] = None

    model_config = {"extra": "ignore"}


class ColumnProfile(BaseModel):
    """
    One entry from Agent 1's column_profiles dict.
    Field names match the profiler exactly.
    """
    dtype: str = "object"
    inferred_role: str = "unknown"             # primary_key | categorical | continuous_numeric | timestamp | boolean | ...
    missing_count: int = 0
    missing_pct: float = 0.0
    unique_count: int = 0
    unique_pct: float = 0.0
    sample_values: List[Any] = Field(default_factory=list)
    numeric_stats: Dict[str, Any] = Field(default_factory=dict)
    value_counts: Dict[str, Any] = Field(default_factory=dict)
    is_constant: bool = False
    issues: List[ColumnIssue] = Field(default_factory=list)
    agent_reasoning: str = ""
    business_interpretation: str = ""
    severity: str = "NONE"
    uncertainty: str = "HIGH"
    python_agreement: str = "agree"
    drop_recommended: bool = False
    imputation_strategy: Optional[str] = None   # mode | median | mean | ...
    etl_cast_to: Optional[str] = None           # none | float | int | datetime | bool | ...
    sandbox_triggered: bool = False
    sandbox_result: Optional[Any] = None
    custom_check_code: Optional[str] = None

    model_config = {"extra": "ignore"}


class ETLHints(BaseModel):
    type_casting_targets: Dict[str, str] = Field(default_factory=dict)
    join_key_candidates: List[str] = Field(default_factory=list)
    drop_candidates: List[str] = Field(default_factory=list)
    recommended_output_format: str = "parquet"
    synonym_mappings: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "ignore"}


class ImputationPlanEntry(BaseModel):
    strategy: str = "median"

    model_config = {"extra": "ignore"}


class Agent1Metadata(BaseModel):
    agent_version: Optional[str] = None
    profiling_timestamp: Optional[str] = None
    llm_provider: Optional[str] = None
    llm_model_used: Optional[str] = None
    llm_status: str = "fallback"
    sandbox_executions: int = 0
    llm_driven: bool = False

    model_config = {"extra": "ignore"}


class ProfilingReport(BaseModel):
    """
    Full Agent 1 output (schema_version 2.1).

    This is the primary input contract for Agent 2.
    Treat findings as *evidence*, not unconditional instructions.
    """
    schema_version: str = "2.1"
    dataset_ref: Agent1DatasetRef
    health_scores: HealthScores = Field(default_factory=HealthScores)
    column_profiles: Dict[str, ColumnProfile] = Field(default_factory=dict)
    cross_column_issues: List[Any] = Field(default_factory=list)
    llm_discovered_issues: List[Any] = Field(default_factory=list)
    uncertainty_flags: List[Any] = Field(default_factory=list)
    recommended_cleaning_order: List[str] = Field(default_factory=list)
    etl_hints: ETLHints = Field(default_factory=ETLHints)
    imputation_plan: Dict[str, ImputationPlanEntry] = Field(default_factory=dict)
    outlier_columns: List[str] = Field(default_factory=list)
    agent_summary: str = ""
    recommendation_summary: str = ""
    metadata: Agent1Metadata = Field(default_factory=Agent1Metadata)

    model_config = {"extra": "ignore"}

    # ----- convenience helpers for Agent 2 -----

    def columns_with_issues(self) -> List[str]:
        return [name for name, prof in self.column_profiles.items() if prof.issues]

    def issues_by_id(self, issue_id: str) -> List[tuple[str, ColumnIssue]]:
        found = []
        for col, prof in self.column_profiles.items():
            for issue in prof.issues:
                if issue.issue_id == issue_id:
                    found.append((col, issue))
        return found

    def type_mismatch_columns(self) -> List[str]:
        return [col for col, _ in self.issues_by_id("type_mismatch")]

    def missing_value_columns(self) -> List[str]:
        return [col for col, _ in self.issues_by_id("missing_values")]

    def high_severity_columns(self) -> List[str]:
        return [
            name for name, prof in self.column_profiles.items()
            if prof.severity.upper() in ("HIGH", "CRITICAL", "MEDIUM")
        ]


# ===========================================================================
# Agent 2 internal planning / execution / validation
# ===========================================================================

class Finding(BaseModel):
    """Normalized finding Agent 2 derives from the profiling report."""
    finding_id: str = Field(default_factory=lambda: str(uuid4())[:8])
    column: Optional[str] = None
    issue_id: Optional[str] = None             # e.g. type_mismatch, missing_values
    description: str
    severity: str = "MEDIUM"
    evidence: Dict[str, Any] = Field(default_factory=dict)
    recommendation: Optional[str] = None
    is_hypothesis: bool = True
    source: str = "agent1"


class TransformationStep(BaseModel):
    """One concrete operation the agent intends to perform."""
    step_id: str = Field(default_factory=lambda: str(uuid4())[:8])
    operation: str = Field(
        ...,
        description="Canonical name, e.g. 'convert_dtype', 'normalize_values', 'handle_missing'"
    )
    columns: List[str] = Field(default_factory=list)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    risk_level: RiskLevel = RiskLevel.MODERATE
    preconditions: List[str] = Field(default_factory=list)
    expected_effect: str = ""
    requires_approval: bool = False
    status: TransformationStatus = TransformationStatus.PROPOSED
    depends_on: List[str] = Field(
        default_factory=list,
        description="step_ids that must succeed before this one"
    )
    source_finding_ids: List[str] = Field(default_factory=list)


class TransformationPlan(BaseModel):
    """Ordered plan produced by the agent before any mutation."""
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    source_dataset: DatasetReference
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    steps: List[TransformationStep] = Field(default_factory=list)
    overall_risk: RiskLevel = RiskLevel.MODERATE
    notes: List[str] = Field(default_factory=list)
    human_approval_required: bool = False
    derived_from_report_summary: Optional[str] = None

    def pending_approval_steps(self) -> List[TransformationStep]:
        return [
            s for s in self.steps
            if s.requires_approval and s.status == TransformationStatus.PROPOSED
        ]


class ChangeRecord(BaseModel):
    """Immutable record of a single applied transformation."""
    change_id: str = Field(default_factory=lambda: str(uuid4())[:8])
    step_id: Optional[str] = None
    operation: str
    columns: List[str] = Field(default_factory=list)
    source_version: str
    result_version: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    affected_rows: Optional[int] = None
    success: bool = True
    error_message: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    approval_obtained: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChangeLog(BaseModel):
    """Complete history of transformations for a run."""
    log_id: str = Field(default_factory=lambda: str(uuid4()))
    dataset_id: str
    entries: List[ChangeRecord] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def add(self, record: ChangeRecord) -> None:
        self.entries.append(record)

    def successful_ops(self) -> List[ChangeRecord]:
        return [e for e in self.entries if e.success]


class ValidationRuleResult(BaseModel):
    rule_name: str
    passed: bool
    message: str = ""
    details: Dict[str, Any] = Field(default_factory=dict)


class ValidationReport(BaseModel):
    """Result of post-transformation checks."""
    report_id: str = Field(default_factory=lambda: str(uuid4()))
    dataset_ref: DatasetReference
    status: ValidationStatus = ValidationStatus.NOT_RUN
    rules: List[ValidationRuleResult] = Field(default_factory=list)
    schema_ok: bool = True
    quality_ok: bool = True
    unresolved_issues: List[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def all_passed(self) -> bool:
        return self.status == ValidationStatus.PASSED and not self.unresolved_issues


class CleaningResult(BaseModel):
    """
    Output of Agent 2 for the next team component.
    """
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    source_dataset: DatasetReference
    final_dataset: DatasetReference
    change_log: ChangeLog
    validation: ValidationReport
    transformation_plan: Optional[TransformationPlan] = None
    unresolved_issues: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))