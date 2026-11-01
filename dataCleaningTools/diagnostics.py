"""Evidence-based failure diagnostics; never execute or rewrite candidate code."""
import ast
import re


def failure_diagnostic(case, error, *, code=None, failed_checks=None, trials=None):
    execution_errors = [t.get("error") for t in (trials or []) if t.get("error")]
    if case == "sandbox_execution" and execution_errors:
        error = "\n".join(dict.fromkeys([error, *execution_errors]))
    diagnostic = {
        "stage": case,
        "problem": error or "The requested outcome failed independent checks.",
        "location": None,
        "evidence": {"failed_checks": failed_checks or [], "failed_trials": trials or []},
        "correction": "Use the reported evidence to revise the request or implementation; do not repeat the unchanged failure.",
        "retry": "Submit a corrected request and evaluate its new result before claiming success.",
    }
    if case == "arguments":
        diagnostic["correction"] = "Correct the named argument, nesting or parameter according to the tool schema. Preserve the intended method unless the evidence requires a change."
    elif case == "sandbox_unavailable":
        diagnostic["correction"] = "Resolve the reported Docker/runtime setup problem; changing cleaning logic will not fix runtime availability. Report the blocker if setup is unavailable."
    elif failed_checks:
        diagnostic["correction"] = "Revise the transformation to satisfy the named failed checks while preserving populated information; inspect unsupported values or explain genuine ambiguity. Do not weaken the checks."
    if not isinstance(code, str) or case != "sandbox_execution":
        return diagnostic
    try:
        ast.parse(code)
    except SyntaxError as exc:
        diagnostic.update(stage="python_syntax", problem=exc.msg,
                          location={"line": exc.lineno, "column": exc.offset,
                                    "source": (exc.text or "").rstrip("\r\n")},
                          correction="Correct the Python syntax at the reported line and column; submit the complete corrected transform(df) and checks.")
        diagnostic["evidence"]["execution_started"] = False
        if "\\n" in code and "\n" not in code:
            diagnostic["evidence"]["literal_newline_escapes"] = code.count("\\n")
            diagnostic["correction"] = (
                "The decoded code field contains literal backslash-n text instead of Python line breaks. "
                "Encode line breaks once in the JSON string so decoding produces actual newline characters; "
                "do not double-escape them. Preserve intentional escapes inside Python string literals. "
                "Resubmit the complete corrected transform(df) with checks.")
        return diagnostic
    if "Define exactly one transform(df)" in error:
        diagnostic.update(stage="python_signature", location={"field": "code"},
                          correction="Define exactly one top-level transform(df) function taking one positional argument and returning a DataFrame.")
    else:
        # Only report locations present in the actual traceback, not guessed causes.
        locations = re.findall(r'File "<cleaning-candidate>", line (\d+)(?:, in ([^\n]+))?', error)
        if locations:
            line, function = locations[-1]
            lines = code.splitlines()
            diagnostic["location"] = {"line": int(line), "function": function or None,
                                      "source": lines[int(line)-1] if 0 < int(line) <= len(lines) else None}
        diagnostic["correction"] = "Read the reported exception and candidate location, correct the responsible implementation, return a DataFrame, and resubmit the complete method with checks. Do not guess a business interpretation from an execution error."
    return diagnostic
