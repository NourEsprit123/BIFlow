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
    """Canonicalize public arguments without inventing model explanations.

    Columns belong at the top level; parameters contains method options only.
    Conflicting declarations are retained for explicit rejection by dispatch.
    """
    if not (isinstance(tool_name, str) and isinstance(arguments, dict)):
        return arguments

    # Strip obsolete reference fields that the application tracks internally.
    if tool_name in {"test_builtin", "test_generated", "flag_for_review"}:
        arguments = {k: v for k, v in arguments.items() if k not in {"issue_ids", "evidence_ids"}}

    if tool_name == "test_builtin" and isinstance(arguments.get("parameters"), dict):
        arguments = dict(arguments)
        parameters = dict(arguments["parameters"])
        nested = parameters.get("columns")
        if isinstance(nested, list):
            if "columns" not in arguments:
                arguments["columns"] = nested
                parameters.pop("columns")
            elif arguments["columns"] == nested:
                parameters.pop("columns")
        arguments["parameters"] = parameters

    # Row removal is verified by its own effect (duplicates gone, nothing else changed); per-column
    # outcomes such as "customer is unique" do not describe it and only make a correct removal fail.
    if tool_name == "test_builtin" and arguments.get("operation") == "remove_duplicates" and "checks" in arguments:
        arguments = {k: v for k, v in arguments.items() if k != "checks"}

    return arguments
