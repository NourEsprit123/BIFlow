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
import re
import time
import threading
from pathlib import Path
from uuid import uuid4

import pandas as pd

from .effects import assess_candidate, present, target_matches

IMAGE = "biflow-cleaning-sandbox:latest"
MAX_BYTES = 64 * 1024 * 1024
BUILD_COMMAND = "docker build -t biflow-cleaning-sandbox:latest -f sandbox/Dockerfile sandbox"
TRANSFORM_SIGNATURE_ERROR = "Define exactly one transform(df) function with one positional argument"
EXECUTION_TIMEOUT = 60
RUNTIME_VERSIONS = {}  # Actual versions reported by this process's sandbox executions, keyed by image ID.


def docker_timeout() -> float:
    """Docker Desktop can take several seconds to answer while busy or waking from Resource Saver."""
    from .llm_client import positive_setting
    return positive_setting("BIFLOW_DOCKER_TIMEOUT", 30)


def is_timeout(exc: BaseException) -> bool:
    """A slow Docker API reply, as opposed to Docker not running or the image missing."""
    return (isinstance(exc, TimeoutError) or type(exc).__name__ in {"ReadTimeout", "ConnectTimeout", "ReadTimeoutError"}
            or "timed out" in str(exc).lower())

# pandas JSON rounds floats (at most 15 decimals), which made untouched columns look changed
# and committed rounding noise. Float columns also travel as exact float.hex() strings.
# One source, used by the host and inside the sandbox wrapper.
FLOAT_CODEC = r'''
def exact_floats(frame):
    return {str(i): [None if pd.isna(v) else float(v).hex() for v in frame.iloc[:, i].tolist()]
            for i in range(frame.shape[1]) if pd.api.types.is_float_dtype(frame.iloc[:, i])}
def restore_floats(frame, floats):
    for i, values in floats.items():
        column = frame.columns[int(i)]
        frame[column] = pd.Series([float('nan') if v is None else float.fromhex(v) for v in values],
                                  index=frame.index, dtype='float64')
    return frame
'''
_codec = {}
exec(FLOAT_CODEC, {"pd": pd}, _codec)
exact_floats, restore_floats = _codec["exact_floats"], _codec["restore_floats"]

# This trusted wrapper runs inside Docker, not on the host. Each invocation
# uses fresh globals and fixed random seeds, and must produce repeatable output.
WRAPPER = r'''
import contextlib, io, json, math, random, re, sys
import numpy as np
import pandas as pd
''' + FLOAT_CODEC + r'''
print('BIFLOW_RUNTIME=' + json.dumps({'python': sys.version.split()[0], 'pandas': pd.__version__, 'numpy': np.__version__}), file=sys.stderr)
# Length framing avoids waiting for EOF on Docker's attached stdin socket.
header = sys.stdin.buffer.read(8)
if len(header) != 8:
    raise ValueError('Incomplete sandbox input header')
size = int.from_bytes(header, 'big')
if not 0 < size <= 64 * 1024 * 1024:
    raise ValueError('Invalid sandbox input size')
raw = sys.stdin.buffer.read(size)
if len(raw) != size:
    raise ValueError('Incomplete sandbox input payload')
payload = json.loads(raw)
before = restore_floats(pd.read_json(io.StringIO(payload['data']), orient='table'), payload['floats'])
code = payload['code']
def invoke():
    random.seed(0)
    np.random.seed(0)
    scope = {'pd': pd, 'np': np, 're': re, 'math': math}
    # Candidate prints are diagnostics, never part of the JSON result stream.
    with contextlib.redirect_stdout(sys.stderr):
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
sys.stdout.buffer.write(json.dumps({'data': first.to_json(orient='table', date_format='iso'),
                                    'floats': exact_floats(first)}).encode())
sys.stdout.buffer.flush()
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
        raise ValueError(TRANSFORM_SIGNATURE_ERROR)


def runtime_status(attempts: int = 2) -> dict:
    """Check Docker and the image; a timed-out reply is retried and reported as transient."""
    for attempt in range(1, attempts + 1):
        client = None
        try:
            import docker
            client = docker.from_env(timeout=docker_timeout())
            client.ping()
            image = client.images.get(os.environ.get("BIFLOW_EXPERIMENT_IMAGE", IMAGE))
            return {"available": True, "backend": "docker", "image_id": image.id,
                    "versions": RUNTIME_VERSIONS.get(image.id, {})}
        except Exception as exc:
            if is_timeout(exc) and attempt < attempts:
                continue
            return {"available": False, "backend": "docker", "error": str(exc), "transient": is_timeout(exc),
                    "attempts": attempt, "setup": f"Start Docker Desktop (Linux containers), then run: {BUILD_COMMAND}"}
        finally:
            if client is not None:
                client.close()


def run_isolated_transform(frame: pd.DataFrame, code: str, *, image_id: str | None = None) -> dict:
    """No host fallback, mounts, network, secrets, or runtime package downloads."""
    validate_code(code)
    client = container = input_socket = None
    watchdog = None
    timed_out = threading.Event()
    phase = "sandbox_setup"
    try:
        import docker
        from docker.types import LogConfig
        from docker.utils.socket import frames_iter
        client = docker.from_env(timeout=docker_timeout())
        image = client.images.get(image_id or os.environ.get("BIFLOW_EXPERIMENT_IMAGE", IMAGE))
        pinned_image = image.id
        payload = json.dumps({"data": frame.to_json(orient="table", date_format="iso"),
                              "floats": exact_floats(frame), "code": code}).encode()
        if len(payload) > MAX_BYTES:
            raise ValueError("Experiment input exceeds the 64 MB limit")
        container = client.containers.create(
            pinned_image, command=["python", "-I", "-c", WRAPPER],
            stdin_open=True,
            working_dir="/workspace", user="65534:65534", network_disabled=True,
            read_only=True, cap_drop=["ALL"], security_opt=["no-new-privileges:true"],
            mem_limit="768m", memswap_limit="768m", nano_cpus=1_000_000_000, pids_limit=64,
            tmpfs={"/workspace": "rw,nosuid,nodev,size=256m,mode=1777", "/tmp": "rw,nosuid,nodev,size=64m,mode=1777"},
            environment={"PYTHONUNBUFFERED": "1", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"},
            log_config=LogConfig(type="json-file", config={"max-size": "1m", "max-file": "1"}),
        )
        # Docker's archive upload rejects read-only root filesystems even for
        # this tmpfs destination. Send input over stdin without filesystem writes.
        phase = "sandbox_input_transfer"
        input_socket = container.attach_socket(params={"stdin": 1, "stream": 1, "stdout": 1, "stderr": 0})
        container.start()
        # Named-pipe reads on Windows can ignore socket timeouts. Killing the
        # container independently unblocks the stream as well as stopping code.
        def stop_execution():
            timed_out.set()
            try:
                container.kill()
            except Exception:
                pass
        watchdog = threading.Timer(EXECUTION_TIMEOUT, stop_execution)
        watchdog.daemon = True
        watchdog.start()
        transport = getattr(input_socket, "_sock", input_socket)
        transport.settimeout(EXECUTION_TIMEOUT)
        transport.sendall(len(payload).to_bytes(8, "big") + payload)
        phase = "sandbox_execution"
        output = bytearray()
        for stream, chunk in frames_iter(transport, tty=False):
            if stream != 1:
                continue
            output.extend(chunk)
            if len(output) > MAX_BYTES:
                raise ValueError("Experiment output exceeds the 64 MB limit")
        outcome = container.wait(timeout=60)
        if timed_out.is_set():
            return {"success": False, "error": f"Sandbox execution timed out after {EXECUTION_TIMEOUT}s",
                    "error_kind": "sandbox_execution", "image_id": pinned_image}
        logs = container.logs(tail=100, stdout=False, stderr=True).decode("utf-8", errors="replace")[-12000:]
        diagnostic_lines = []
        for line in logs.splitlines():
            if line.startswith("BIFLOW_RUNTIME=") and pinned_image not in RUNTIME_VERSIONS:
                try:
                    versions = json.loads(line.removeprefix("BIFLOW_RUNTIME="))
                    if set(versions) == {"python", "pandas", "numpy"} and all(isinstance(v, str) for v in versions.values()):
                        RUNTIME_VERSIONS[pinned_image] = versions
                except (ValueError, TypeError):
                    pass
            elif not line.startswith("BIFLOW_RUNTIME="):
                diagnostic_lines.append(line)
        logs = "\n".join(diagnostic_lines)
        if outcome["StatusCode"] != 0:
            return {"success": False, "error": logs or "Sandbox process failed", "image_id": pinned_image,
                    "error_kind": "sandbox_execution"}
        data = bytes(output)
        phase = "sandbox_output_transfer"
        envelope = json.loads(data.decode())
        result = restore_floats(pd.read_json(io.StringIO(envelope["data"]), orient="table"), envelope["floats"])
        return {"success": True, "df": result, "image_id": pinned_image,
                "repeatable": True, "output_hash": digest(data), "log": logs}
    except Exception as exc:
        if timed_out.is_set():
            return {"success": False, "error": f"Sandbox execution timed out after {EXECUTION_TIMEOUT}s",
                    "error_kind": "sandbox_execution"}
        return {"success": False, "error": str(exc), "transient": is_timeout(exc),
                "error_kind": "sandbox_unavailable" if container is None else "sandbox_execution" if phase == "sandbox_execution" else "sandbox_infrastructure",
                "failure_stage": phase,
                "setup": f"Use an isolated Docker runtime. {BUILD_COMMAND}"}
    finally:
        if watchdog is not None:
            watchdog.cancel()
        if input_socket is not None:
            try:
                input_socket.close()
            except Exception:
                pass
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass
        if client is not None:
            client.close()


def squashed(series):
    """Text with surrounding and repeated spaces removed; missing and blank compare equal."""
    return series.map(lambda v: "" if not isinstance(v, str) and pd.isna(v) else re.sub(r"\s+", " ", str(v)).strip())


def assess_method(before, after, columns, checks, *, verify_numeric_values=True):
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
            elif kind == "preserve_missing":
                passed = (column in before and before.index.equals(after.index)
                          and bool((present(before[column]) | ~present(series)).all()))
            elif kind == "whitespace_only":
                passed = (column in before and before.index.equals(after.index)
                          and squashed(before[column]).tolist() == squashed(series).tolist())  # values only; dtype may change
            elif kind == "unique":
                passed = bool(series.is_unique)
            elif kind == "non_negative":
                numeric = pd.to_numeric(series, errors="coerce")
                passed = bool(numeric.notna().all() and numeric.ge(0).all())
            else:
                passed = target_matches(series, kind)
        rules.append({"rule_name": f"expected:{kind}:{column}", "passed": passed,
                      "message": "The finding is about spaces only: values may change only by surrounding or repeated spaces, "
                                 f"not case or content, in {column}" if kind == "whitespace_only"
                                 else f"Declared outcome: {column} must satisfy {kind}"})
    if verify_numeric_values:
        from .numeric_expectations import numeric_rules
        from .value_interpretation import boolean_rules
        numeric_columns = {c["column"] for c in checks if c["kind"] in {"numeric", "integer", "non_negative"}}
        numeric_columns.update(c for c in columns if c in after and pd.api.types.is_numeric_dtype(after[c])
                               and not pd.api.types.is_bool_dtype(after[c]))
        rules.extend(numeric_rules(before, after, [c for c in columns if c in numeric_columns]))
        boolean_columns = {c["column"] for c in checks if c["kind"] == "boolean"}
        boolean_columns.update(c for c in columns if c in after and pd.api.types.is_bool_dtype(after[c]))
        rules.extend(boolean_rules(before, after, [c for c in columns if c in boolean_columns]))
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
    valid_checks = {"whitespace_only", "no_missing", "unique", "non_negative", "numeric", "integer", "boolean", "datetime", "string", "preserve_missing"}
    if not checks or any(c.get("column") not in columns or c.get("kind") not in valid_checks for c in checks):
        raise ValueError("Declare at least one supported outcome check on an affected column")
    evidence_ids = arguments.get("evidence_ids", [])
    if any(key not in state.evidence for key in evidence_ids):
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
            "verify_numeric_values": arguments.get("verify_numeric_values", True),
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
                trial["effect"] = assess_method(frame, execution["df"], columns, checks,
                    verify_numeric_values=spec["verify_numeric_values"])
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
        return CleaningResult(False, error=execution["error"], details={"candidate_id": candidate_id,
            "error_kind": execution.get("error_kind"), "setup": execution.get("setup"), "sandbox_log": execution.get("log", "")})
    if execution["image_id"] != spec["image_id"]:
        return CleaningResult(False, error="Sandbox runtime differs from the tested runtime")
    effect = assess_method(before, execution["df"], spec["columns"], spec["checks"],
        verify_numeric_values=spec.get("verify_numeric_values", True))
    details = {"candidate_id": candidate_id, "code_hash": spec["code_hash"], "image_id": spec["image_id"],
               "full_data_effect": effect, "code_path": spec["code_path"], "sandbox_log": execution.get("log", "")}
    (Path(spec["code_path"]).parent / "full_data_validation.json").write_text(json.dumps(details, indent=2, default=str), encoding="utf-8")
    if not effect["accepted"]:
        return CleaningResult(False, error="Full-data validation failed; working version preserved", details=details)
    return CleaningResult(True, df=execution["df"], affected_rows=int(effect["changed_cells"] or 0),
                          message="Exact tested method passed full-data validation", details=details)
