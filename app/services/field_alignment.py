import numpy as np

from app.services.embeddings import embed_texts

FIELD_ALIGNMENT_THRESHOLD = 0.6
SAMPLE_VALUES_PER_FIELD = 3


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def _field_description(field: str, sample_records: list[dict]) -> str:
    values = [
        str(record[field])
        for record in sample_records
        if record.get(field) not in (None, "")
    ][:SAMPLE_VALUES_PER_FIELD]
    return f"{field}: {', '.join(values)}"


def align_fields(
    fields_a: list[str],
    fields_b: list[str],
    sample_records_a: list[dict] | None = None,
    sample_records_b: list[dict] | None = None,
    insufficient_fields_a: set[str] | None = None,
    insufficient_fields_b: set[str] | None = None,
) -> dict:
    """Semantically align canonical field names across two datasets by embedding
    similarity. Each field is embedded as "<field_name>: <sample values>" rather
    than the bare name, so synonym pairs grounded in similar data (e.g.
    manufacturer/brand) score higher than bare word-embedding similarity would give.

    Fields listed in insufficient_fields_a/b (genuinely sparse/empty even after the
    caller's top-up attempt) are excluded from embedding-based matching entirely —
    matching on a bare field name with no real data would be a false signal, not a
    real alignment — and are reported in "insufficient_data_fields" instead.

    Returns {"alignment": {field_a: field_b, ...}, "shared_field_count": int,
    "insufficient_data_fields": {"a": [...], "b": [...]}}.
    Each field_a is matched to at most one field_b (its best match above threshold)."""
    insufficient_fields_a = insufficient_fields_a or set()
    insufficient_fields_b = insufficient_fields_b or set()

    matchable_fields_a = [f for f in fields_a if f not in insufficient_fields_a]
    matchable_fields_b = [f for f in fields_b if f not in insufficient_fields_b]

    insufficient_data_fields = {
        "a": sorted(insufficient_fields_a),
        "b": sorted(insufficient_fields_b),
    }

    if not matchable_fields_a or not matchable_fields_b:
        return {
            "alignment": {},
            "shared_field_count": 0,
            "insufficient_data_fields": insufficient_data_fields,
        }

    sample_records_a = sample_records_a or []
    sample_records_b = sample_records_b or []

    descriptions_a = [_field_description(f, sample_records_a) for f in matchable_fields_a]
    descriptions_b = [_field_description(f, sample_records_b) for f in matchable_fields_b]

    embeddings = embed_texts(descriptions_a + descriptions_b)
    vectors_a = [np.array(e) for e in embeddings[: len(matchable_fields_a)]]
    vectors_b = [np.array(e) for e in embeddings[len(matchable_fields_a) :]]

    alignment = {}
    used_b = set()
    for field_a, vec_a in zip(matchable_fields_a, vectors_a):
        best_field_b = None
        best_score = FIELD_ALIGNMENT_THRESHOLD
        for field_b, vec_b in zip(matchable_fields_b, vectors_b):
            if field_b in used_b:
                continue
            score = _cosine_similarity(vec_a, vec_b)
            if score > best_score:
                best_score = score
                best_field_b = field_b

        if best_field_b is not None:
            alignment[field_a] = best_field_b
            used_b.add(best_field_b)

    return {
        "alignment": alignment,
        "shared_field_count": len(alignment),
        "insufficient_data_fields": insufficient_data_fields,
    }
