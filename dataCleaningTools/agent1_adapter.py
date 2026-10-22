"""
Adapter: Agent 1 profiling report → Agent 2 internal structures.

Responsibilities:
  1. Parse / validate the raw JSON from Agent 1 (schema_version 2.1).
  2. Map Agent1DatasetRef → a filesystem path Agent 2 can register.
  3. Extract normalized Finding list for planning.
  4. Suggest initial TransformationSteps from recommended_cleaning_order,
     imputation_plan, etl_hints and column issues — still only *proposals*.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .models import (
    ColumnIssue,
    ColumnProfile,
    DatasetReference,
    DatasetStatus,
    Finding,
    ProfilingReport,
    RiskLevel,
    TransformationPlan,
    TransformationStep,
    TransformationStatus,
)


def parse_profiling_report(
    payload: Union[str, Path, Dict[str, Any], ProfilingReport],
) -> ProfilingReport:
    """
    Accept a file path, JSON string, dict, or already-parsed model
    and return a validated ProfilingReport.
    """
    if isinstance(payload, ProfilingReport):
        return payload

    if isinstance(payload, (str, Path)):
        path = Path(payload)
        if path.exists() and path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
        else:
            # treat as JSON string
            raw = json.loads(str(payload))
    elif isinstance(payload, dict):
        raw = payload
    else:
        raise TypeError(f"Unsupported payload type: {type(payload)}")

    return ProfilingReport.model_validate(raw)


def resolve_source_path(
    report: ProfilingReport,
    search_roots: Optional[List[Union[str, Path]]] = None,
) -> Path:
    """
    Resolve the dataset file path from Agent 1's dataset_ref.

    Agent 1 may emit absolute Windows paths that don't exist on the
    machine running Agent 2. We try, in order:
      1. The exact file_path if it exists
      2. file_name under each search_root
      3. Raise FileNotFoundError with a clear message
    """
    ref = report.dataset_ref
    candidate = Path(ref.file_path)
    if candidate.exists():
        return candidate.resolve()

    # Windows path on Linux → only keep the basename
    name = ref.file_name or candidate.name
    roots = search_roots or [
        Path("data"),
        Path("data/raw"),
        Path("."),
    ]
    for root in roots:
        root = Path(root)
        hit = root / name
        if hit.exists():
            return hit.resolve()

    raise FileNotFoundError(
        f"Cannot locate dataset '{name}'. "
        f"Agent 1 reported path: {ref.file_path}. "
        f"Searched: {[str(r) for r in roots]}"
    )


def extract_findings(report: ProfilingReport) -> List[Finding]:
    """Flatten column issues + top-level hints into normalized Findings."""
    findings: List[Finding] = []

    for col_name, prof in report.column_profiles.items():
        for issue in prof.issues:
            findings.append(
                Finding(
                    column=col_name,
                    issue_id=issue.issue_id,
                    description=issue.description,
                    severity=issue.severity,
                    evidence=issue.evidence or {},
                    recommendation=_recommendation_from_issue(col_name, prof, issue),
                    is_hypothesis=issue.source == "llm",
                    source=issue.source,
                )
            )

        # Flag high uncertainty even without explicit issues
        if prof.uncertainty.upper() == "HIGH" and not prof.issues:
            findings.append(
                Finding(
                    column=col_name,
                    issue_id="high_uncertainty",
                    description=f"High uncertainty on role/type for '{col_name}' "
                                f"(inferred_role={prof.inferred_role})",
                    severity="LOW",
                    evidence={"uncertainty": prof.uncertainty, "dtype": prof.dtype},
                    recommendation="Verify before aggressive transforms",
                    is_hypothesis=True,
                    source="agent1",
                )
            )

    for item in report.cross_column_issues:
        findings.append(
            Finding(
                column=None,
                issue_id="cross_column",
                description=str(item),
                severity="MEDIUM",
                is_hypothesis=True,
                source="agent1",
            )
        )

    for item in report.llm_discovered_issues:
        findings.append(
            Finding(
                column=None,
                issue_id="llm_discovered",
                description=str(item),
                severity="MEDIUM",
                is_hypothesis=True,
                source="llm",
            )
        )

    return findings


def propose_initial_steps(
    report: ProfilingReport,
    source_ref: DatasetReference,
) -> TransformationPlan:
    """
    Build a *draft* TransformationPlan from Agent 1 signals.

    Rules of thumb (deterministic, overridable by the agent):
      - Follow recommended_cleaning_order when present.
      - type_mismatch + numeric-looking → convert_data_types (coerce)
      - type_mismatch + timestamp → convert to datetime
      - type_mismatch + boolean → map Yes/No → bool
      - missing_values → handle_missing using imputation_plan strategy
      - drop_recommended → only propose after approval (high risk)

    Every step starts as PROPOSED. Risk / approval flags are set
    conservatively; the policy layer can still block execution.
    """
    steps: List[TransformationStep] = []
    findings = extract_findings(report)
    finding_by_col_issue = {
        (f.column, f.issue_id): f.finding_id for f in findings if f.column
    }

    # Prefer Agent 1's suggested order; fall back to column_profiles order
    order = report.recommended_cleaning_order or list(report.column_profiles.keys())

    for col in order:
        prof = report.column_profiles.get(col)
        if prof is None:
            continue

        issue_ids = {i.issue_id for i in prof.issues}

        # --- type conversions ---
        if "type_mismatch" in issue_ids:
            role = (prof.inferred_role or "").lower()
            cast = (prof.etl_cast_to or "none").lower()
            mismatch_desc = " ".join(
                i.description for i in prof.issues if i.issue_id == "type_mismatch"
            ).lower()
            is_dirty_numeric = (
                "dirty numeric" in mismatch_desc
                or "numeric stored as text" in mismatch_desc
                or _looks_like_dirty_numeric(prof)
            )

            if (
                role in ("continuous_numeric", "numeric")
                or cast in ("float", "int", "numeric")
                or is_dirty_numeric
            ):
                if is_dirty_numeric:
                    steps.append(
                        TransformationStep(
                            operation="clean_numeric_string",
                            columns=[col],
                            parameters={"errors": "coerce"},
                            rationale=f"type_mismatch / dirty numeric strings on '{col}'",
                            risk_level=RiskLevel.MODERATE,
                            requires_approval=_needs_approval_for_numeric(prof),
                            source_finding_ids=[
                                finding_by_col_issue.get((col, "type_mismatch"), "")
                            ],
                            expected_effect="Currency/k/m suffixes parsed; garbage → NaN",
                        )
                    )
                else:
                    steps.append(
                        TransformationStep(
                            operation="convert_data_types",
                            columns=[col],
                            parameters={"target_type": "numeric", "errors": "coerce"},
                            rationale=f"type_mismatch on '{col}' (role={prof.inferred_role})",
                            risk_level=RiskLevel.MODERATE,
                            requires_approval=_needs_approval_for_numeric(prof),
                            source_finding_ids=[
                                finding_by_col_issue.get((col, "type_mismatch"), "")
                            ],
                            expected_effect="Numeric values parsable; garbage → NaN",
                        )
                    )
            elif role in ("timestamp", "date", "datetime") or cast in ("datetime", "date"):
                steps.append(
                    TransformationStep(
                        operation="convert_data_types",
                        columns=[col],
                        parameters={"target_type": "datetime", "errors": "coerce"},
                        rationale=f"Date/time stored as text in '{col}'",
                        risk_level=RiskLevel.MODERATE,
                        requires_approval=False,
                        source_finding_ids=[
                            finding_by_col_issue.get((col, "type_mismatch"), "")
                        ],
                        expected_effect="Column becomes datetime64",
                    )
                )
            elif role in ("boolean", "bool") or cast in ("bool", "boolean"):
                steps.append(
                    TransformationStep(
                        operation="normalize_values",
                        columns=[col],
                        parameters={
                            "mapping": {
                                "yes": "true", "no": "false",
                                "Yes": "true", "No": "false",
                                "YES": "true", "NO": "false",
                                "Y": "true", "N": "false",
                                "1": "true", "0": "false",
                                "true": "true", "false": "false",
                            },
                            "case": "lower",
                            "strip_whitespace": True,
                        },
                        rationale=f"Boolean flag stored as text in '{col}'",
                        risk_level=RiskLevel.LOW,
                        requires_approval=False,
                        source_finding_ids=[
                            finding_by_col_issue.get((col, "type_mismatch"), "")
                        ],
                        expected_effect="Normalized yes/no → true/false strings (cast later)",
                    )
                )
                steps.append(
                    TransformationStep(
                        operation="convert_data_types",
                        columns=[col],
                        parameters={"target_type": "boolean", "errors": "coerce"},
                        rationale=f"Cast normalized '{col}' to boolean",
                        risk_level=RiskLevel.LOW,
                        requires_approval=False,
                        expected_effect="bool dtype",
                    )
                )

        # --- dirty numeric strings that profiler labelled categorical ---
        # Revenue-like columns often land here
        if (
            "type_mismatch" not in issue_ids
            and prof.inferred_role == "categorical"
            and _looks_like_dirty_numeric(prof)
        ):
            steps.append(
                TransformationStep(
                    operation="clean_numeric_string",
                    columns=[col],
                    parameters={"errors": "coerce"},
                    rationale=(
                        f"'{col}' looks like currency/numeric text "
                        f"(samples: {prof.sample_values[:4]})"
                    ),
                    risk_level=RiskLevel.MODERATE,
                    requires_approval=True,   # ambiguous values like "1.5k", "banana"
                    source_finding_ids=[],
                    expected_effect="Parsed numeric; unparseable → NaN",
                )
            )

        # --- missing values ---
        if "missing_values" in issue_ids or prof.missing_count > 0:
            strategy = _imputation_strategy(report, col, prof)
            # Dropping rows is higher risk than filling
            risk = RiskLevel.HIGH if strategy == "drop_rows" else RiskLevel.MODERATE
            steps.append(
                TransformationStep(
                    operation="handle_missing_values",
                    columns=[col],
                    parameters={"strategy": strategy},
                    rationale=f"Missing {prof.missing_pct}% in '{col}'",
                    risk_level=risk,
                    requires_approval=risk in (RiskLevel.HIGH, RiskLevel.CRITICAL),
                    source_finding_ids=[
                        finding_by_col_issue.get((col, "missing_values"), "")
                    ],
                    expected_effect=f"Apply {strategy}",
                )
            )

        # --- drop recommended ---
        if prof.drop_recommended:
            steps.append(
                TransformationStep(
                    operation="drop_column",
                    columns=[col],
                    parameters={},
                    rationale=f"Agent 1 marked '{col}' drop_recommended=True",
                    risk_level=RiskLevel.HIGH,
                    requires_approval=True,
                    expected_effect=f"Column '{col}' removed",
                )
            )

    # ETL hint: explicit cast targets
    for col, target in (report.etl_hints.type_casting_targets or {}).items():
        if not any(s.columns == [col] and s.operation == "convert_data_types" for s in steps):
            steps.append(
                TransformationStep(
                    operation="convert_data_types",
                    columns=[col],
                    parameters={"target_type": target, "errors": "coerce"},
                    rationale=f"etl_hints.type_casting_targets['{col}'] = {target}",
                    risk_level=RiskLevel.MODERATE,
                    requires_approval=False,
                )
            )

    overall = RiskLevel.LOW
    if any(s.risk_level == RiskLevel.CRITICAL for s in steps):
        overall = RiskLevel.CRITICAL
    elif any(s.risk_level == RiskLevel.HIGH for s in steps):
        overall = RiskLevel.HIGH
    elif any(s.risk_level == RiskLevel.MODERATE for s in steps):
        overall = RiskLevel.MODERATE

    return TransformationPlan(
        source_dataset=source_ref,
        steps=steps,
        overall_risk=overall,
        human_approval_required=any(s.requires_approval for s in steps),
        notes=[
            report.agent_summary,
            report.recommendation_summary,
        ],
        derived_from_report_summary=report.recommendation_summary,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _recommendation_from_issue(
    col: str, prof: ColumnProfile, issue: ColumnIssue
) -> Optional[str]:
    if issue.issue_id == "type_mismatch":
        return (issue.evidence or {}).get("recommendation") or f"Inspect and cast '{col}'"
    if issue.issue_id == "missing_values":
        return f"Impute or drop missing in '{col}' (strategy={prof.imputation_strategy})"
    return issue.description


def _imputation_strategy(
    report: ProfilingReport, col: str, prof: ColumnProfile
) -> str:
    if col in report.imputation_plan:
        return report.imputation_plan[col].strategy
    if prof.imputation_strategy:
        return prof.imputation_strategy
    role = (prof.inferred_role or "").lower()
    if role in ("continuous_numeric", "numeric"):
        return "median"
    return "mode"


def _needs_approval_for_numeric(prof: ColumnProfile) -> bool:
    """If many values look unparseable, require approval."""
    for issue in prof.issues:
        if issue.issue_id == "type_mismatch":
            evidence = issue.evidence or {}
            # e.g. "1 unparseable entries out of 29" → still mostly ok
            detected = str(evidence.get("detected", ""))
            valid_ratio = evidence.get("valid_ratio")
            if valid_ratio is not None and float(valid_ratio) < 80:
                return True
            if "unparseable" in detected.lower():
                # extract rough ratio if present
                return False  # small number of bad values → auto ok with coerce
    return False


def _looks_like_dirty_numeric(prof: ColumnProfile) -> bool:
    """Heuristic: sample values contain $, k, commas, or spelled numbers."""
    samples = [str(v).lower() for v in (prof.sample_values or [])[:12]]
    if not samples:
        return False
    markers = ("$", "k", ",", "thousand", "million", "banana", "n/a", "none")
    hits = sum(1 for s in samples if any(m in s for m in markers))
    # also pure-looking numbers mixed with junk
    digitish = sum(1 for s in samples if any(c.isdigit() for c in s))
    return hits >= 1 and digitish >= 2