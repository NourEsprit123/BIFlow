"""Live Docker checks using synthetic data; no model calls or dataset application."""
import json
import os
from pathlib import Path
import sys
import time
import argparse
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import docker
import pandas as pd
from dataCleaningTools.experiments import run_isolated_transform, assess_method, runtime_status
from dataCleaningTools import experiments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=60, help="Execution limit for this diagnostic process only")
    options = parser.parse_args()
    if options.timeout < 1:
        parser.error("timeout must be positive")
    experiments.EXECUTION_TIMEOUT = options.timeout
    destination = ROOT / "data/diagnostics" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_sandbox_" + uuid4().hex[:8])
    destination.mkdir(parents=True)
    results = []
    containers = []
    controls = []
    factory = docker.from_env
    canary = destination / "host_only_canary.txt"
    canary.write_text("synthetic isolation probe", encoding="utf-8")
    old_probe = os.environ.get("BIFLOW_HOST_ONLY_PROBE")
    os.environ["BIFLOW_HOST_ONLY_PROBE"] = "synthetic-secret"

    def client_factory(**kwargs):
        client = factory(**kwargs)
        manager = client.containers
        def create(*args, **options):
            container = manager.create(*args, **options)
            containers.append(container.id)
            container.reload()
            host = container.attrs["HostConfig"]
            controls.append({"read_only": host["ReadonlyRootfs"], "network_disabled": container.attrs["Config"]["NetworkDisabled"],
                "user": container.attrs["Config"]["User"], "memory": host["Memory"], "cpus": host["NanoCpus"],
                "pids": host["PidsLimit"], "cap_drop": host["CapDrop"], "security_options": host["SecurityOpt"],
                "binds": host.get("Binds"), "tmpfs": host.get("Tmpfs")})
            return container
        return SimpleNamespace(images=client.images, containers=SimpleNamespace(create=create), close=client.close)

    def check(name, frame, code, verify):
        print("RUNNING " + name, flush=True)
        started = time.monotonic()
        result = run_isolated_transform(frame, code)
        try:
            verify(result)
            passed, error = True, None
        except Exception as exc:
            passed, error = False, str(exc)
        results.append({"test": name, "passed": passed, "seconds": round(time.monotonic()-started, 3),
            "assertion_error": error, "runner": {k: v for k, v in result.items() if k != "df"}})
        print(("PASS " if passed else "FAIL ") + name, flush=True)

    def require(condition, message):
        if not condition:
            raise AssertionError(message)

    status = runtime_status()
    if not status["available"]:
        raise RuntimeError(status)
    docker.from_env = client_factory
    frame = pd.DataFrame({"amount": ["$1,200.50", "850.00"], "label": ["échantillon", "東京"]})
    try:
        check("roundtrip_and_diagnostic_output", frame,
            "def transform(df):\n    print('candidate log')\n    df['amount'] = pd.to_numeric(df['amount'].str.replace('$', '', regex=False).str.replace(',', '', regex=False))\n    return df",
            lambda r: require(r.get("success") and r["df"]["amount"].tolist() == [1200.5, 850.0]
                and r["df"]["label"].tolist() == frame["label"].tolist() and "candidate log" in r["log"], "Roundtrip/log mismatch"))
        check("runtime_exception_traceback", frame, "def transform(df):\n    raise ValueError('sandbox-probe-error')",
            lambda r: require(not r["success"] and "sandbox-probe-error" in r["error"] and "<cleaning-candidate>" in r["error"], "Missing traceback"))
        check("invalid_return_type", frame, "def transform(df):\n    return 42",
            lambda r: require(not r["success"] and "must return a pandas DataFrame" in r["error"], "Invalid return accepted"))
        check("repeatability_check", frame,
            "def transform(df):\n    import uuid\n    df['label'] = str(uuid.uuid4())\n    return df",
            lambda r: require(not r["success"] and "different outputs" in r["error"], "Nonrepeatable result accepted"))
        isolation = """def transform(df):
    import os, socket
    from pathlib import Path
    assert os.getuid() == 65534
    assert 'BIFLOW_HOST_ONLY_PROBE' not in os.environ
    assert not Path(HOST_CANARY).exists()
    try:
        Path('/etc/biflow_isolation_probe').write_text('probe')
    except OSError:
        pass
    else:
        raise AssertionError('Root filesystem is writable')
    Path('/workspace/probe').write_text('temporary')
    assert Path('/workspace/probe').read_text() == 'temporary'
    sock = socket.socket()
    sock.settimeout(1)
    try:
        sock.connect(('198.51.100.1', 9))
    except OSError:
        pass
    else:
        raise AssertionError('Outbound network connection succeeded')
    finally:
        sock.close()
    return df
""".replace("HOST_CANARY", repr(str(canary)))
        check("identity_filesystem_network_environment_isolation", frame, isolation,
            lambda r: require(r["success"], r.get("error", "Isolation failure")))
        check("independent_data_loss_validation", frame,
            "def transform(df):\n    df['amount'] = None\n    return df",
            lambda r: require(r["success"] and not assess_method(frame, r["df"], ["amount"], [])['accepted'], "Data loss was not rejected"))
        check("execution_timeout", frame, "def transform(df):\n    import time\n    time.sleep(600)\n    return df",
            lambda r: require(not r["success"] and any(s in r.get("error", "").lower() for s in ("timed out", "timeout")), "Timeout not enforced"))
    finally:
        docker.from_env = factory
        if old_probe is None:
            os.environ.pop("BIFLOW_HOST_ONLY_PROBE", None)
        else:
            os.environ["BIFLOW_HOST_ONLY_PROBE"] = old_probe
    client = factory(timeout=5)
    leftovers = []
    try:
        for identity in containers:
            try:
                client.containers.get(identity)
                leftovers.append(identity)
            except docker.errors.NotFound:
                pass
    finally:
        client.close()
    results.append({"test": "resource_configuration", "passed": bool(controls) and all(
        c["read_only"] and c["network_disabled"] and c["user"] == "65534:65534"
        and c["memory"] == 768*1024*1024 and c["cpus"] == 1_000_000_000 and c["pids"] == 64
        and c["cap_drop"] == ["ALL"] and "no-new-privileges:true" in c["security_options"] and not c["binds"] for c in controls)})
    results.append({"test": "container_cleanup", "passed": not leftovers, "leftovers": leftovers})
    report = {"runtime": status, "results": results, "controls": controls, "all_passed": all(r["passed"] for r in results)}
    (destination / "sandbox_test_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(destination, flush=True)
    print(json.dumps({"passed": sum(r["passed"] for r in results), "total": len(results), "all_passed": report["all_passed"]}), flush=True)
    if not report["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
