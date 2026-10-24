"""Generated cleaning methods: isolated trials, independent checks, exact-code promotion.

Generated Python is only compiled/executed inside a resource-limited container.
Container outputs use JSON, never pickle or executable host-side artifacts.
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import tarfile
import time
from pathlib import Path
from uuid import uuid4

import pandas as pd

from .effects import assess_candidate, present, target_matches

IMAGE = "biflow-cleaning-sandbox:latest"
MAX_BYTES = 64 * 1024 * 1024
BUILD_COMMAND = "docker build -t biflow-cleaning-sandbox:latest -f sandbox/Dockerfile sandbox"

# This trusted wrapper runs inside Docker, not on the host. Each invocation
# uses fresh globals and fixed random seeds, and must produce repeatable output.
WRAPPER = r'''
import io, json, math, random, re, time
from pathlib import Path
import numpy as np
import pandas as pd
request = Path('/workspace/request.json')
for _ in range(800):
    if Path('/workspace/ready').exists():
        break
    time.sleep(0.05)
payload = json.loads(request.read_text())
before = pd.read_json(io.StringIO(payload['data']), orient='table')
code = payload['code']
def invoke():
    random.seed(0)
    np.random.seed(0)
    scope = {'pd': pd, 'np': np, 're': re, 'math': math}
    exec(compile(code, '<cleaning-candidate>', 'exec'), scope)
    result = scope['transform'](before.copy(deep=True))
    if not isinstance(result, pd.DataFrame):
        raise TypeError('transform(df) must return a pandas DataFrame')
    if not result.columns.is_unique:
        raise ValueError('Output columns must be unique')
    return result
first = invoke()
second = invoke()
if not first.equals(second):
    raise ValueError('Candidate produced different outputs on repeated identical inputs')
Path('/workspace/output.json').write_text(first.to_json(orient='table', date_format='iso'))
print(json.dumps({'rows': len(first), 'columns': len(first.columns), 'repeatable': True}))
'''


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_code(code: str) -> None:
    if not isinstance(code, str) or not code.strip() or len(code) > 8000:
        raise ValueError("Provide Python code of at most 8,000 characters")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"Invalid candidate Python at line {exc.lineno}: {exc.msg}") from exc
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "transform"]
    if len(functions) != 1 or len(functions[0].args.args) != 1:
        raise ValueError("Define exactly one transform(df) function with one positional argument")


def runtime_status() -> dict:
    client = None
    try:
        import docker
        client = docker.from_env(timeout=5)
        client.ping()
        image = client.images.get(os.environ.get("BIFLOW_EXPERIMENT_IMAGE", IMAGE))
        return {"available": True, "backend": "docker", "image_id": image.id}
    except Exception as exc:
        return {"available": False, "backend": "docker", "error": str(exc),
                "setup": f"Start Docker Desktop (Linux containers), then run: {BUILD_COMMAND}"}
    finally:
        if client is not None:
            client.close()


def run_isolated_transform(frame: pd.DataFrame, code: str, *, image_id: str | None = None) -> dict:
    """No host fallback, mounts, network, secrets, or runtime package downloads."""
    validate_code(code)
    client = container = None
    try:
        import docker
        from docker.types import LogConfig
        client = docker.from_env(timeout=5)
        image = client.images.get(image_id or os.environ.get("BIFLOW_EXPERIMENT_IMAGE", IMAGE))
        pinned_image = image.id
        payload = json.dumps({"data": frame.to_json(orient="table", date_format="iso"), "code": code}).encode()
        if len(payload) > MAX_BYTES:
            raise ValueError("Experiment input exceeds the 64 MB limit")
        container = client.containers.create(
            pinned_image, command=["python", "-I", "-c", WRAPPER],
            working_dir="/workspace", user="65534:65534", network_disabled=True,
            read_only=True, cap_drop=["ALL"], security_opt=["no-new-privileges:true"],
            mem_limit="768m", memswap_limit="768m", nano_cpus=1_000_000_000, pids_limit=64,
            tmpfs={"/workspace": "rw,nosuid,nodev,size=256m,mode=1777", "/tmp": "rw,nosuid,nodev,size=64m,mode=1777"},
            environment={"PYTHONUNBUFFERED": "1", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"},
            log_config=LogConfig(type="json-file", config={"max-size": "1m", "max-file": "1"}),
        )
        container.start()
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as bundle:
            info = tarfile.TarInfo("request.json")
            info.size, info.mode = len(payload), 0o444
            bundle.addfile(info, io.BytesIO(payload))
            # Written after the payload, so the reader cannot consume a
            # partially transferred JSON file on large inputs.
            ready = tarfile.TarInfo("ready")
            ready.size, ready.mode = 0, 0o444
            bundle.addfile(ready, io.BytesIO())
        container.put_archive("/workspace", archive.getvalue())
        outcome = container.wait(timeout=60)
        logs = container.logs(tail=100).decode("utf-8", errors="replace")[-12000:]
        if outcome["StatusCode"] != 0:
            return {"success": False, "error": logs or "Sandbox process failed", "image_id": pinned_image}
        chunks, _ = container.get_archive("/workspace/output.json")
        output = bytearray()
        for chunk in chunks:
            output.extend(chunk)
            if len(output) > MAX_BYTES:
                raise ValueError("Experiment output exceeds the 64 MB limit")
        # Read one named member; never extract paths from an untrusted archive.
        with tarfile.open(fileobj=io.BytesIO(output)) as bundle:
            member = bundle.getmember("output.json")
            if not member.isfile() or member.size > MAX_BYTES:
                raise ValueError("Invalid sandbox output file")
            data = bundle.extractfile(member).read()
        result = pd.read_json(io.StringIO(data.decode()), orient="table")
        return {"success": True, "df": result, "image_id": pinned_image,
                "repeatable": True, "output_hash": digest(data), "log": logs}
    except Exception as exc:
        return {"success": False, "error": str(exc),
                "setup": f"Use an isolated Docker runtime. {BUILD_COMMAND}"}
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass
        if client is not None:
            client.close()


def assess_method(before, after, columns, checks):
    effect = assess_candidate(before, after, "apply_experimental_method", columns, {})
    rules = effect["rules"]
    rules.append({"rule_name": "row_identity", "passed": before.index.equals(after.index),
                  "message": "Generated methods must preserve row index and order"})
    for check in checks:
        column, kind = check["column"], check["kind"]
        passed = False
        if column in after:
            series = after[column]
            if kind == "no_missing":
                passed = bool(present(series).all())
            elif kind == "unique":
                passed = bool(series.is_unique)
            elif kind == "non_negative":
                numeric = pd.to_numeric(series, errors="coerce")
                passed = bool(numeric.notna().all() and numeric.ge(0).all())
            else:
                passed = target_matches(series, kind)
        rules.append({"rule_name": f"expected:{kind}:{column}", "passed": passed,
                      "message": f"Declared outcome: {column} must satisfy {kind}"})
    effect["column_metrics"] = {}
    for column in columns:
        effect["column_metrics"][column] = {}
        for label, frame in (("before", before), ("after", after)):
            if column not in frame:
                continue
            values = frame[column]
            numeric = pd.to_numeric(values, errors="coerce").dropna()
            effect["column_metrics"][column][label] = {
                "unique": int(values.nunique()), "missing": int((~present(values)).sum()),
                "numeric_count": len(numeric),
                "mean": float(numeric.mean()) if len(numeric) else None,
                "median": float(numeric.median()) if len(numeric) else None,
                "min": float(numeric.min()) if len(numeric) else None,
                "max": float(numeric.max()) if len(numeric) else None,
            }
    effect["accepted"] = all(r["passed"] for r in rules)
    return effect


def experiment(state, arguments) -> dict:
    code, columns = arguments["code"].replace("\r\n", "\n"), arguments["columns"]
    validate_code(code)
    before = state.manager.load(state.current_ref)
    if not columns or set(columns) - set(before.columns):
        raise ValueError("Declare non-empty affected columns that exist in the dataset")
    if before.empty:
        raise ValueError("Cannot experiment on an empty dataset")
    checks = arguments["checks"]
    valid_checks = {"no_missing", "unique", "non_negative", "numeric", "integer", "boolean", "datetime", "string"}
    if not checks or any(c.get("column") not in columns or c.get("kind") not in valid_checks for c in checks):
        raise ValueError("Declare at least one supported outcome check on an affected column")
    evidence_ids = arguments.get("evidence_ids", [])
    if not evidence_ids or any(key not in state.evidence for key in evidence_ids):
        raise ValueError("Reference existing profiling or inspection evidence IDs")
    if not arguments["rationale"].strip() or not arguments["expected_effect"].strip():
        raise ValueError("Explain the rationale and expected effect")
    sample_size = arguments.get("sample_size", 200)
    if not isinstance(sample_size, int) or not 1 <= sample_size <= 500:
        raise ValueError("sample_size must be between 1 and 500")
    candidate_id = f"method-{uuid4().hex[:10]}"
    directory = state.manager.root / state.dataset_id / "experiments" / candidate_id
    directory.mkdir(parents=True)
    spec = {"candidate_id": candidate_id, "code_hash": digest(code.encode()),
            "base_version": state.current_ref.version,
            "dataset_hash": digest(Path(state.current_ref.path).read_bytes()),
            "columns": list(columns), "checks": checks, "rationale": arguments["rationale"],
            "expected_effect": arguments["expected_effect"], "evidence_ids": evidence_ids,
            "code_path": str((directory / "method.py").resolve()), "trials": [], "tested": False}
    Path(spec["code_path"]).write_text(code, encoding="utf-8", newline="\n")
    # Random, disjoint development and holdout rows. Small datasets use all rows
    # across both partitions; a single-row dataset cannot supply a holdout.
    sample = before.sample(n=min(sample_size, max(1, len(before) // 2)), random_state=41)
    remaining = before.drop(index=sample.index)
    partitions = [("sample", sample)]
    if len(remaining):
        partitions.append(("holdout", remaining.sample(n=min(sample_size, len(remaining)), random_state=73)))
    spec["holdout_available"] = len(partitions) > 1
    for name, frame in partitions:
        if time.monotonic() >= state.deadline:
            spec["trials"].append({"partition": name, "rows": len(frame), "success": False, "error": "Run time budget expired before this trial"})
            break
        if state.on_event:
            state.on_event({"phase": f"sandbox {name} trial for {candidate_id} ({len(frame)} rows)"})
        execution = run_isolated_transform(frame, code, image_id=spec.get("image_id"))
        trial = {"partition": name, "rows": len(frame), "row_positions": frame.index.tolist(),
                 **{k: v for k, v in execution.items() if k != "df"}}
        if execution["success"]:
            spec.setdefault("image_id", execution["image_id"])
            if execution["image_id"] != spec["image_id"]:
                trial.update(success=False, error="Sandbox image changed between trials")
            else:
                trial["effect"] = assess_method(frame, execution["df"], columns, checks)
                trial["success"] = trial["effect"]["accepted"]
        spec["trials"].append(trial)
        if not trial["success"]:
            break
    spec["tested"] = len(spec["trials"]) == len(partitions) and all(t["success"] for t in spec["trials"])
    (directory / "experiment.json").write_text(json.dumps(spec, indent=2, default=str), encoding="utf-8")
    state.experiments[candidate_id] = spec
    state.evidence[candidate_id] = {"source": "sandbox experiment", "columns": columns,
                                    "version": spec["base_version"], "code_hash": spec["code_hash"],
                                    "tested": spec["tested"], "expected_effect": spec["expected_effect"]}
    return {"success": spec["tested"], "candidate_id": candidate_id, "code_hash": spec["code_hash"],
            "rationale": spec["rationale"], "expected_effect": spec["expected_effect"],
            "evidence_ids": evidence_ids, "tested": spec["tested"], "trials": spec["trials"],
            "holdout_available": spec["holdout_available"],
            "message": "Trials passed; full-data checks are still required before applying." if spec["tested"] else "Candidate was not approved by the trials; inspect the failure and revise the code."}


def promote(state, candidate_id, before):
    from .cleaning import CleaningResult
    spec = state.experiments.get(candidate_id)
    if time.monotonic() >= state.deadline:
        return CleaningResult(False, error="Run time budget expired before promotion")
    if not spec or not spec["tested"]:
        return CleaningResult(False, error="Candidate must pass sample and holdout trials before promotion")
    if spec["base_version"] != state.current_ref.version or spec["dataset_hash"] != digest(Path(state.current_ref.path).read_bytes()):
        return CleaningResult(False, error="Dataset changed since testing. Run a fresh experiment on the current version.")
    code = Path(spec["code_path"]).read_text(encoding="utf-8")
    if digest(code.encode()) != spec["code_hash"]:
        return CleaningResult(False, error="Candidate code changed after testing. Run a fresh experiment.")
    if state.on_event:
        state.on_event({"phase": f"full-data sandbox validation of {candidate_id} ({len(before)} rows)"})
    execution = run_isolated_transform(before, code, image_id=spec["image_id"])
    if not execution["success"]:
        return CleaningResult(False, error=execution["error"], details={"candidate_id": candidate_id})
    if execution["image_id"] != spec["image_id"]:
        return CleaningResult(False, error="Sandbox runtime differs from the tested runtime")
    effect = assess_method(before, execution["df"], spec["columns"], spec["checks"])
    details = {"candidate_id": candidate_id, "code_hash": spec["code_hash"], "image_id": spec["image_id"],
               "full_data_effect": effect, "code_path": spec["code_path"]}
    (Path(spec["code_path"]).parent / "full_data_validation.json").write_text(json.dumps(details, indent=2, default=str), encoding="utf-8")
    if not effect["accepted"]:
        return CleaningResult(False, error="Full-data validation failed; working version preserved", details=details)
    return CleaningResult(True, df=execution["df"], affected_rows=int(effect["changed_cells"] or 0),
                          message="Exact tested method passed full-data validation", details=details)
