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
    if not values:
        return field
    return f"{field}: {', '.join(values)}"


def align_fields(
    fields_a: list[str],
    fields_b: list[str],
    sample_records_a: list[dict] | None = None,
    sample_records_b: list[dict] | None = None,
) -> dict:
    """Semantically align canonical field names across two datasets by embedding
    similarity. Each field is embedded as "<field_name>: <sample values>" rather
    than the bare name, so synonym pairs grounded in similar data (e.g.
    manufacturer/brand) score higher than bare word-embedding similarity would give.
    Returns {"alignment": {field_a: field_b, ...}, "shared_field_count": int}.
    Each field_a is matched to at most one field_b (its best match above threshold)."""
    if not fields_a or not fields_b:
        return {"alignment": {}, "shared_field_count": 0}

    sample_records_a = sample_records_a or []
    sample_records_b = sample_records_b or []

    descriptions_a = [_field_description(f, sample_records_a) for f in fields_a]
    descriptions_b = [_field_description(f, sample_records_b) for f in fields_b]

    embeddings = embed_texts(descriptions_a + descriptions_b)
    vectors_a = [np.array(e) for e in embeddings[: len(fields_a)]]
    vectors_b = [np.array(e) for e in embeddings[len(fields_a) :]]

    alignment = {}
    used_b = set()
    for field_a, vec_a in zip(fields_a, vectors_a):
        best_field_b = None
        best_score = FIELD_ALIGNMENT_THRESHOLD
        for field_b, vec_b in zip(fields_b, vectors_b):
            if field_b in used_b:
                continue
            score = _cosine_similarity(vec_a, vec_b)
            if score > best_score:
                best_score = score
                best_field_b = field_b

        if best_field_b is not None:
            alignment[field_a] = best_field_b
            used_b.add(best_field_b)

    return {"alignment": alignment, "shared_field_count": len(alignment)}
