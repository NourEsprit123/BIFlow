"""Export measured cleaning results without another model request."""
from pathlib import Path

from .effects import snapshot
from .versioning import DatasetVersionManager


def write_cleaning_report(result, directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    dataset = Path(result.source_dataset.dataset_id).name
    latest = directory / f"{dataset}_cleaning_report.json"
    archive = directory / f"{dataset}_{result.run_id}_cleaning_report.json"
    before = snapshot(DatasetVersionManager._read(Path(result.source_dataset.path), result.source_dataset.format))
    after = snapshot(DatasetVersionManager._read(Path(result.final_dataset.path), result.final_dataset.format))
    applied = result.change_log.successful_ops()
    result.metadata.update(
        report_path=str(latest), report_archive_path=str(archive),
        report_summary={
            "report_type": "cleaning", "schema_version": "1.0",
            "validation_status": result.validation.status.value,
            "before": before, "after": after,
            "changes_applied": len(applied),
            "values_coerced_to_missing": sum(len((item.metadata.get("effect") or {}).get("lost_values", [])) for item in applied),
            "rejected_changes": sum(not item.success for item in result.change_log.entries),
            "generated_candidates": len(result.metadata.get("experiments", {})),
            "generated_changes_applied": sum(item.operation == "apply_experimental_method" for item in applied),
            "note": "Technical checks do not establish business correctness. Builtin methods run on the host; generated methods require isolated Docker trials.",
        },
    )
    payload = result.model_dump_json(indent=2)
    # Keep an export for each run as well as the latest report for the dataset.
    for path in (archive, latest):
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(path)
    return latest
