"""
Sandbox execution for Agent 2 via llm-sandbox (>=0.1.0).

Backends (chosen by env BIFLOW_SANDBOX_BACKEND or auto-detect):
  docker       – recommended when Docker is available
  podman       – rootless alternative
  bubblewrap   – local Linux namespaces (no Docker daemon)
  nsjail       – local Linux alternative
  fallback     – host subprocess (DEV ONLY, not isolated)

Environment variables
---------------------
BIFLOW_SANDBOX_BACKEND   docker | podman | bubblewrap | nsjail | fallback | auto
BIFLOW_SANDBOX_TIMEOUT   execution timeout seconds (default 60)
BIFLOW_SANDBOX_VERBOSE   1 to enable verbose session logs
"""

from __future__ import annotations

import os
import math
import shutil
import subprocess
import sys
import tempfile
import textwrap
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class SandboxResult:
    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    backend: str = ""
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "backend": self.backend,
            "error": self.error,
            "metadata": self.metadata,
        }


def _env_backend() -> str:
    return os.environ.get("BIFLOW_SANDBOX_BACKEND", "auto").strip().lower()


def _timeout() -> float:
    try:
        return float(os.environ.get("BIFLOW_SANDBOX_TIMEOUT", "60"))
    except ValueError:
        return 60.0


def _verbose() -> bool:
    return os.environ.get("BIFLOW_SANDBOX_VERBOSE", "0") in ("1", "true", "True")


def detect_backend() -> str:
    """Pick the best available backend."""
    requested = _env_backend()
    if requested != "auto":
        return requested

    # Prefer Docker, then Podman, then local Linux, else fallback
    if _docker_available():
        return "docker"
    if _podman_available():
        return "podman"
    if _binary_available("bwrap"):
        return "bubblewrap"
    if _binary_available("nsjail"):
        return "nsjail"
    return "fallback"


def _binary_available(name: str) -> bool:
    from shutil import which
    return which(name) is not None


def _docker_available() -> bool:
    try:
        r = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def _podman_available() -> bool:
    try:
        r = subprocess.run(
            ["podman", "info"],
            capture_output=True,
            timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def _build_security_policy():
    """Restrict dangerous modules (advisory — must call is_safe before run)."""
    try:
        from llm_sandbox.security import (
            RestrictedModule,
            SecurityIssueSeverity,
            SecurityPolicy,
        )
        return SecurityPolicy(
            severity_threshold=SecurityIssueSeverity.MEDIUM,
            restricted_modules=[
                RestrictedModule(
                    name="os",
                    description="OS interface",
                    severity=SecurityIssueSeverity.HIGH,
                ),
                RestrictedModule(
                    name="subprocess",
                    description="Process execution",
                    severity=SecurityIssueSeverity.HIGH,
                ),
                RestrictedModule(
                    name="socket",
                    description="Network sockets",
                    severity=SecurityIssueSeverity.HIGH,
                ),
                RestrictedModule(
                    name="pathlib",
                    description="Path traversal helper — prefer explicit paths",
                    severity=SecurityIssueSeverity.LOW,
                ),
            ],
        )
    except Exception:
        return None


def _open_session(backend: str, timeout: Optional[float] = None):
    """Create an llm-sandbox SandboxSession for the given backend."""
    from llm_sandbox import SandboxSession

    timeout = _timeout() if timeout is None else timeout
    verbose = _verbose()
    if backend in ("docker", "podman", "micromamba", "kubernetes"):
        return SandboxSession(
            backend=backend,
            lang="python",
            verbose=verbose,
            execution_timeout=timeout,
            default_timeout=timeout,
        )

    if backend in ("bubblewrap", "nsjail"):
        from llm_sandbox import LocalSandboxConfig

        cfg = LocalSandboxConfig(
            network="none",
            cpu_time_limit=int(timeout),
            file_size_limit=64 * 1024 * 1024,
            open_files_limit=256,
            max_output_bytes=2 * 1024 * 1024,
            memory_limit_bytes=512 * 1024 * 1024,
        )
        return SandboxSession(
            backend=backend,
            sandbox_config=cfg,
            lang="python",
            verbose=verbose,
            execution_timeout=timeout,
            default_timeout=timeout,
        )

    raise ValueError(f"Unsupported llm-sandbox backend: {backend}")


def run_code(
    code: str,
    *,
    libraries: Optional[List[str]] = None,
    backend: Optional[str] = None,
    check_safety: bool = True,
    timeout: Optional[float] = None,
    input_files: Optional[Dict[Path, str]] = None,
    output_files: Optional[List[str]] = None,
    work_dir: Optional[Path] = None,
) -> SandboxResult:
    """
    Execute Python code in the configured sandbox.

    Parameters
    ----------
    code :
        Python source to run.
    libraries :
        Optional list of pip packages (requires network-capable backend).
    backend :
        Override auto-detected backend.
    check_safety :
        If True, run SecurityPolicy.is_safe() and refuse unsafe code.
    input_files :
        Host path → sandbox relative path mappings to copy in before run.
    output_files :
        Relative paths inside the sandbox to copy back after run.
    work_dir :
        Host directory for copied output files (default: temp dir).
    """
    backend = backend or detect_backend()
    libraries = libraries or ["pandas", "numpy"]
    timeout = _timeout() if timeout is None else timeout
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Sandbox timeout must be a positive finite number.")

    if backend == "fallback":
        return _run_fallback(
            code,
            libraries=libraries,
            timeout=timeout,
            input_files=input_files,
            output_files=output_files,
            work_dir=work_dir,
        )

    try:
        session = _open_session(backend, timeout=timeout)
    except Exception as e:
        return SandboxResult(
            success=False,
            backend=backend,
            error=f"Failed to open sandbox session: {e}",
            stderr=traceback.format_exc(),
        )

    out_dir = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="biflow_sbx_"))
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        with session:
            if check_safety:
                policy = _build_security_policy()
                if policy is not None and hasattr(session, "is_safe"):
                    # Some versions attach policy via constructor; try both
                    try:
                        is_safe, violations = session.is_safe(code)
                        if not is_safe:
                            msgs = [
                                getattr(v, "description", str(v))
                                for v in (violations or [])
                            ]
                            return SandboxResult(
                                success=False,
                                backend=backend,
                                error="Security policy rejected code",
                                stderr="\n".join(msgs),
                                metadata={"violations": msgs},
                            )
                    except TypeError:
                        pass  # is_safe signature may differ

            # Copy inputs into sandbox workspace
            if input_files:
                for host_path, sbx_name in input_files.items():
                    host_path = Path(host_path)
                    if not host_path.exists():
                        return SandboxResult(
                            success=False,
                            backend=backend,
                            error=f"Input file missing: {host_path}",
                        )
                    if hasattr(session, "copy_to_runtime"):
                        session.copy_to_runtime(str(host_path), str(sbx_name))
                    else:
                        copy_to_container = getattr(session, "copy_to_container", None)
                        if copy_to_container is None:
                            raise AttributeError(
                                "Sandbox session does not support copying input files"
                            )
                        copy_to_container(str(host_path), str(sbx_name))

            result = session.run(code, libraries=libraries)
            exit_code = getattr(result, "exit_code", 0) or 0
            stdout = getattr(result, "stdout", "") or ""
            stderr = getattr(result, "stderr", "") or ""

            # Copy outputs back
            retrieved: Dict[str, str] = {}
            if output_files:
                for name in output_files:
                    dest = out_dir / Path(name).name
                    try:
                        if hasattr(session, "copy_from_runtime"):
                            session.copy_from_runtime(str(name), str(dest))
                        else:
                            copy_from_container = getattr(
                                session, "copy_from_container", None
                            )
                            if copy_from_container is None:
                                raise AttributeError(
                                    "Sandbox session does not support retrieving output files"
                                )
                            copy_from_container(str(name), str(dest))
                        if dest.exists():
                            retrieved[name] = str(dest)
                    except Exception as copy_err:
                        stderr += f"\n[copy_from] {name}: {copy_err}"

            return SandboxResult(
                success=exit_code == 0,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                backend=backend,
                error=None if exit_code == 0 else (stderr or "non-zero exit"),
                metadata={"output_files": retrieved, "work_dir": str(out_dir)},
            )
    except Exception as e:
        return SandboxResult(
            success=False,
            backend=backend,
            error=str(e),
            stderr=traceback.format_exc(),
        )


def run_dataframe_transform(
    input_csv: Path,
    code_body: str,
    *,
    output_name: str = "output.csv",
    backend: Optional[str] = None,
) -> SandboxResult:
    """
    Convenience: run a transform that reads input.csv and writes output.csv.

    ``code_body`` should assume:
        df = pd.read_csv("input.csv")
        # ... mutate df ...
        df.to_csv("output.csv", index=False)
    Or only the middle part; this wrapper adds the boilerplate.
    """
    input_csv = Path(input_csv)
    output_path = Path(output_name)
    if output_path.is_absolute() or ".." in output_path.parts:
        raise ValueError(f"Output name must be a sandbox-relative path: {output_name}")
    output_name = output_path.as_posix()
    wrapper = textwrap.dedent(
        f"""
        from pathlib import Path
        import pandas as pd
        df = pd.read_csv("input.csv")
        # --- user / agent transform ---
        {code_body}
        # --- persist ---
        if "df" in dir():
            Path({output_name!r}).parent.mkdir(parents=True, exist_ok=True)
            df.to_csv({output_name!r}, index=False)
            print(f"WROTE {{len(df)}} rows, {{len(df.columns)}} cols")
        else:
            raise RuntimeError("Transform did not leave a DataFrame named df")
        """
    ).strip()

    return run_code(
        wrapper,
        libraries=["pandas", "numpy"],
        backend=backend,
        input_files={input_csv: "input.csv"},
        output_files=[output_name],
    )


# ---------------------------------------------------------------------------
# Fallback (development only — NOT isolated)
# ---------------------------------------------------------------------------

def _run_fallback(
    code: str,
    libraries: Optional[List[str]] = None,
    timeout: Optional[float] = None,
    input_files: Optional[Dict[Path, str]] = None,
    output_files: Optional[List[str]] = None,
    work_dir: Optional[Path] = None,
) -> SandboxResult:
    """
    Execute on the host in a subprocess. Use only when no real sandbox backend
    is available (CI / restricted environments). Marked clearly in results.
    """
    timeout = _timeout() if timeout is None else timeout
    with tempfile.TemporaryDirectory(prefix="biflow_fallback_") as tmp:
        temp_dir = Path(tmp)
        script = temp_dir / "run.py"
        out_dir = Path(work_dir) if work_dir else Path(
            tempfile.mkdtemp(prefix="biflow_sbx_")
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        def sandbox_path(name: str) -> Path:
            relative_path = Path(name)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise ValueError(f"Sandbox file path must be relative: {name}")
            return temp_dir / relative_path

        try:
            script.write_text(code, encoding="utf-8")
            for host_path, sandbox_name in (input_files or {}).items():
                destination = sandbox_path(sandbox_name)
                host_path = Path(host_path)
                if not host_path.is_file():
                    return SandboxResult(
                        success=False,
                        backend="fallback",
                        error=f"Input file missing: {host_path}",
                    )
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(host_path, destination)

            proc = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=temp_dir,
            )
            retrieved: Dict[str, str] = {}
            for name in output_files or []:
                source = sandbox_path(name)
                if source.is_file():
                    destination = out_dir / Path(name).name
                    shutil.copy2(source, destination)
                    retrieved[name] = str(destination)
            return SandboxResult(
                success=proc.returncode == 0,
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
                backend="fallback",
                error=None if proc.returncode == 0 else proc.stderr[:500],
                metadata={
                    "warning": "NOT ISOLATED — host subprocess",
                    "output_files": retrieved,
                    "work_dir": str(out_dir),
                    "libraries_installed": False,
                    "requested_libraries": libraries or [],
                },
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                success=False,
                backend="fallback",
                error=f"Timeout after {timeout}s",
                exit_code=-1,
            )
        except Exception as e:
            return SandboxResult(
                success=False,
                backend="fallback",
                error=str(e),
                stderr=traceback.format_exc(),
            )


def sandbox_status() -> Dict[str, Any]:
    """Diagnostic info for tests / README."""
    return {
        "requested": _env_backend(),
        "selected": detect_backend(),
        "docker": _docker_available(),
        "podman": _podman_available(),
        "bwrap": _binary_available("bwrap"),
        "nsjail": _binary_available("nsjail"),
        "timeout": _timeout(),
        "llm_sandbox_importable": _can_import_llm_sandbox(),
    }


def _can_import_llm_sandbox() -> bool:
    from importlib.util import find_spec

    return find_spec("llm_sandbox") is not None