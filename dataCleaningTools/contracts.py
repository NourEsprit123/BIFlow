"""Translate profiling dtype vocabulary into cleaning tool vocabulary."""

def canonical_type(value):
    target = str(value).strip().lower()
    aliases = {
        "float64": "float", "float32": "float", "double": "float",
        "int": "integer", "int64": "integer", "int32": "integer",
        "bool": "boolean", "str": "string", "object": "string",
        "date": "datetime", "timestamp": "datetime", "datetime64[ns]": "datetime",
    }
    return aliases.get(target, target)


def model_arguments(tool_name, arguments):
    """Discard obsolete model-supplied references; the application owns them."""
    if isinstance(tool_name, str) and tool_name in {"test_method", "flag_for_review"} and isinstance(arguments, dict):
        return {key: value for key, value in arguments.items() if key not in {"issue_ids", "evidence_ids"}}
    return arguments
