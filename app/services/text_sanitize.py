import re

# Postgres text/JSONB columns reject NUL (0x00) outright, and other C0 control
# characters (besides tab/newline/carriage-return) are never meaningful in
# ingested data or LLM-generated text — strip them wherever external text
# (uploaded files, LLM responses) is about to be persisted.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def sanitize_text(value):
    if isinstance(value, str):
        return _CONTROL_CHARS_RE.sub("", value)
    return value


def sanitize_json(value):
    """Recursively strips control characters from every string in a JSON-like
    structure (dict/list/str/other), for sanitizing nested LLM JSON output
    before it's persisted to a JSONB column."""
    if isinstance(value, dict):
        return {k: sanitize_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_json(v) for v in value]
    return sanitize_text(value)
