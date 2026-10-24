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
