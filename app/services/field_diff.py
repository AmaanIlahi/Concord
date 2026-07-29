import re

NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?$")

# Fraction of the larger numeric value the smaller one must differ by to
# count as a real discrepancy rather than rounding/formatting noise.
NUMERIC_DIFF_TOLERANCE = 0.01


def _normalize(value) -> str:
    return str(value).strip().lower()


def _is_real_diff(value_a: str, value_b: str) -> bool:
    if _normalize(value_a) == _normalize(value_b):
        return False

    if NUMERIC_RE.match(value_a.strip()) and NUMERIC_RE.match(value_b.strip()):
        num_a, num_b = float(value_a), float(value_b)
        if num_a == 0 and num_b == 0:
            return False
        larger = max(abs(num_a), abs(num_b))
        return abs(num_a - num_b) / larger > NUMERIC_DIFF_TOLERANCE

    return True


def _conflict_type(value_a: str, value_b: str) -> str:
    if NUMERIC_RE.match(value_a.strip()) and NUMERIC_RE.match(value_b.strip()):
        return "unit_mismatch"
    return "contradiction"


def diff_fields(canonical_a: dict, canonical_b: dict, field_alignment: dict) -> list[dict]:
    """Direct, non-LLM comparison of each aligned field pair. Returns a list of
    {"field", "value_a", "value_b", "type"} for fields whose values differ
    meaningfully (not just case/whitespace formatting)."""
    conflicts = []
    for field_a, field_b in field_alignment.items():
        value_a = canonical_a.get(field_a)
        value_b = canonical_b.get(field_b)
        if value_a in (None, "") or value_b in (None, ""):
            continue

        value_a, value_b = str(value_a), str(value_b)
        if _is_real_diff(value_a, value_b):
            conflicts.append(
                {
                    "field": field_a,
                    "value_a": value_a,
                    "value_b": value_b,
                    "type": _conflict_type(value_a, value_b),
                }
            )

    return conflicts
