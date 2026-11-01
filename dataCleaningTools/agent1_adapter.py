"""Load profiling reports and build proposals for the optional deterministic baseline."""

from __future__ import annotations

from .contracts import canonical_type

from pathlib import Path, PureWindowsPath
from typing import Any, Dict, List, Optional, Union

from .models import (
    ColumnIssue,
    ColumnProfile,
    DatasetReference,
    Finding,
    ProfilingReport,
    RiskLevel,
    TransformationPlan,
    TransformationStep,
)


def parse_profiling_report(payload: Union[str, Path, Dict[str, Any], ProfilingReport]) -> ProfilingReport:
    """Validate a report model/dict, JSON object string, or UTF-8 report file."""
    if isinstance(payload, (ProfilingReport, dict)):
        return ProfilingReport.model_validate(payload)
    if isinstance(payload, Path):
        return ProfilingReport.model_validate_json(payload.read_text(encoding="utf-8-sig"))
    if isinstance(payload, str):
        text = payload if payload.lstrip().startswith(("{", "[")) else Path(payload).read_text(encoding="utf-8-sig")
        return ProfilingReport.model_validate_json(text)
    raise TypeError(f"Unsupported payload type: {type(payload).__name__}")


def resolve_source_path(report: ProfilingReport, search_roots=None) -> Path:
    """Use the exact source file, then its filename under the supplied roots."""
    ref = report.dataset_ref
    name = PureWindowsPath(ref.file_name or ref.file_path).name
    roots = search_roots or [Path("data"), Path("data/raw"), Path(".")]
    candidates = [Path(ref.file_path), *(Path(root) / name for root in roots)]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(f"Cannot locate dataset '{name}'. Searched: {[str(p) for p in candidates]}")


def extract_findings(report: ProfilingReport) -> List[Finding]:
    """Flatten profiler findings without treating recommendations as commands."""
    findings = []
    for column, profile in report.column_profiles.items():
        for issue in profile.issues:
            findings.append(Finding(column=column, issue_id=issue.issue_id,
                description=issue.description, severity=issue.severity, evidence=issue.evidence,
                recommendation=_recommendation_from_issue(column, profile, issue),
                is_hypothesis=issue.source == "llm", source=issue.source))
        if profile.uncertainty.upper() == "HIGH" and not profile.issues:
            findings.append(Finding(column=column, issue_id="high_uncertainty",
                description=f"High uncertainty on role/type for '{column}' (inferred_role={profile.inferred_role})",
                severity="LOW", evidence={"uncertainty": profile.uncertainty, "dtype": profile.dtype},
                recommendation="Verify before aggressive transforms", is_hypothesis=True, source="agent1"))
    for items, issue_id, source in ((report.cross_column_issues, "cross_column", "agent1"),
                                   (report.llm_discovered_issues, "llm_discovered", "llm")):
        findings.extend(Finding(issue_id=issue_id, description=str(item), severity="MEDIUM",
                                is_hypothesis=True, source=source) for item in items)
    return findings


def propose_initial_steps(report: ProfilingReport, source_ref: DatasetReference) -> TransformationPlan:
    """Build proposals for the explicit deterministic baseline, not the LLM task queue."""
    steps = []
    finding_ids = {(f.column, f.issue_id): f.finding_id for f in extract_findings(report) if f.column}

    def add(operation, column, parameters, rationale, expected="", *,
            risk=RiskLevel.MODERATE, approval=False, issue=None):
        finding_id = finding_ids.get((column, issue))
        steps.append(TransformationStep(operation=operation, columns=[column], parameters=parameters,
            rationale=rationale, expected_effect=expected, risk_level=risk, requires_approval=approval,
            source_finding_ids=[finding_id] if finding_id else []))

    for column in report.recommended_cleaning_order or report.column_profiles:
        profile = report.column_profiles.get(column)
        if profile is None:
            continue
        issue_ids = {issue.issue_id for issue in profile.issues}
        role = profile.inferred_role.lower()
        cast = (profile.etl_cast_to or "none").lower()
        if "type_mismatch" in issue_ids:
            descriptions = " ".join(i.description for i in profile.issues if i.issue_id == "type_mismatch").lower()
            dirty = "dirty numeric" in descriptions or "numeric stored as text" in descriptions or _looks_like_dirty_numeric(profile)
            if role in {"continuous_numeric", "numeric"} or cast in {"float", "int", "numeric"} or dirty:
                add("clean_numeric_string" if dirty else "convert_data_types", column,
                    {"errors": "coerce"} if dirty else {"target_type": "numeric", "errors": "coerce"},
                    f"type_mismatch on '{column}' (role={profile.inferred_role}, dirty_numeric={dirty})",
                    "Parse numeric values; unparseable entries become NaN",
                    approval=_needs_approval_for_numeric(profile), issue="type_mismatch")
            elif role in {"timestamp", "date", "datetime"} or cast in {"datetime", "date"}:
                add("convert_data_types", column, {"target_type": "datetime", "errors": "coerce"},
                    f"Date/time stored as text in '{column}'", "Column becomes datetime64", issue="type_mismatch")
            elif role in {"boolean", "bool"} or cast in {"bool", "boolean"}:
                add("normalize_values", column, {"mapping": {
                    "yes": "true", "no": "false", "Yes": "true", "No": "false", "YES": "true", "NO": "false",
                    "Y": "true", "N": "false", "1": "true", "0": "false", "true": "true", "false": "false"},
                    "case": "lower", "strip_whitespace": True},
                    f"Boolean flag stored as text in '{column}'", "Normalize boolean text before casting",
                    risk=RiskLevel.LOW, issue="type_mismatch")
                add("convert_data_types", column, {"target_type": "boolean", "errors": "coerce"},
                    f"Cast normalized '{column}' to boolean", "bool dtype", risk=RiskLevel.LOW)
        elif profile.inferred_role == "categorical" and _looks_like_dirty_numeric(profile):
            add("clean_numeric_string", column, {"errors": "coerce"},
                f"'{column}' looks like currency/numeric text (samples: {profile.sample_values[:4]})",
                "Parsed numeric; unparseable entries become NaN", approval=True)

        if "missing_values" in issue_ids or profile.missing_count > 0:
            strategy = _imputation_strategy(report, column, profile)
            add("handle_missing_values", column, {"strategy": strategy},
                f"Missing {profile.missing_pct}% in '{column}'", f"Apply {strategy}",
                risk=RiskLevel.HIGH if strategy == "drop_rows" else RiskLevel.MODERATE,
                approval=strategy == "drop_rows", issue="missing_values")
        if profile.drop_recommended:
            add("drop_column", column, {}, f"Agent 1 marked '{column}' drop_recommended=True",
                f"Column '{column}' removed", risk=RiskLevel.HIGH, approval=True)

    for column, target in report.etl_hints.type_casting_targets.items():
        if not any(s.columns == [column] and s.operation == "convert_data_types" for s in steps):
            add("convert_data_types", column, {"target_type": canonical_type(target), "errors": "coerce"},
                f"etl_hints.type_casting_targets['{column}'] = {target}")
    return TransformationPlan(source_dataset=source_ref, steps=steps,
        overall_risk=max((s.risk_level for s in steps), key=list(RiskLevel).index, default=RiskLevel.LOW),
        human_approval_required=any(s.requires_approval for s in steps),
        notes=[report.agent_summary, report.recommendation_summary],
        derived_from_report_summary=report.recommendation_summary)


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