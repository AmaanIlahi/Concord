import numpy as np
from sqlalchemy.orm import Session

from app.models import Dataset, Record
from app.services.domain_classification import classify_domain
from app.services.embeddings import embed_texts
from app.services.field_alignment import align_fields

CENTROID_SAMPLE_SIZE = 20

MIN_SHARED_FIELDS = 2
MIN_CENTROID_SIMILARITY = 0.7


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def _sample_records(db: Session, dataset_id) -> list[Record]:
    return (
        db.query(Record)
        .filter(Record.dataset_id == dataset_id)
        .limit(CENTROID_SAMPLE_SIZE)
        .all()
    )


def _record_text(record: Record) -> str:
    fields = record.canonical_json or record.raw_json or {}
    return " ".join(f"{k}: {v}" for k, v in fields.items())


def _dataset_centroid(db: Session, dataset_id) -> tuple[np.ndarray, list[dict]]:
    """Embeds a sample of a dataset's records, persisting embeddings onto those
    Record rows for reuse. NOTE: the future bulk-embedding step (architecture doc
    step 4) must skip records that already have a non-null embedding, so this
    sampling work isn't redone from scratch."""
    records = _sample_records(db, dataset_id)

    to_embed = [r for r in records if r.embedding is None]
    if to_embed:
        vectors = embed_texts([_record_text(r) for r in to_embed])
        for record, vector in zip(to_embed, vectors):
            record.embedding = vector
        db.flush()

    all_vectors = [np.array(r.embedding) for r in records]
    centroid = np.mean(all_vectors, axis=0)
    sample_canonical = [r.canonical_json for r in records[:3]]
    return centroid, sample_canonical


def run_compatibility_check(db: Session, dataset_a: Dataset, dataset_b: Dataset) -> dict:
    fields_a = list((dataset_a.schema_mapping or {}).keys())
    fields_b = list((dataset_b.schema_mapping or {}).keys())

    centroid_a, sample_a = _dataset_centroid(db, dataset_a.id)
    centroid_b, sample_b = _dataset_centroid(db, dataset_b.id)
    centroid_similarity = _cosine_similarity(centroid_a, centroid_b)
    centroid_ok = centroid_similarity >= MIN_CENTROID_SIMILARITY

    alignment_result = align_fields(fields_a, fields_b, sample_a, sample_b)
    shared_field_count = alignment_result["shared_field_count"]
    field_overlap_ok = shared_field_count >= MIN_SHARED_FIELDS

    domain_a = classify_domain(fields_a, sample_a)
    domain_b = classify_domain(fields_b, sample_b)
    domains_match = domain_a.strip().lower() == domain_b.strip().lower()

    signals_passed = sum([field_overlap_ok, centroid_ok, domains_match])
    is_compatible = signals_passed >= 2

    if is_compatible:
        reasoning = (
            f"Datasets appear compatible: {shared_field_count} aligned fields shared, "
            f"centroid similarity {centroid_similarity:.2f}, domains "
            f"('{domain_a}' vs '{domain_b}')."
        )
    else:
        reasoning = (
            f"Datasets appear incompatible: only {shared_field_count} aligned fields shared, "
            f"centroid similarity {centroid_similarity:.2f}, domains "
            f"('{domain_a}' vs '{domain_b}')."
        )

    return {
        "verdict": "compatible" if is_compatible else "incompatible",
        "reasoning": reasoning,
        "signals": {
            "field_overlap": {
                "shared_field_count": shared_field_count,
                "alignment": alignment_result["alignment"],
                "passed": field_overlap_ok,
            },
            "domain_classification": {
                "domain_a": domain_a,
                "domain_b": domain_b,
                "match": domains_match,
            },
            "centroid_distance": {
                "cosine_similarity": centroid_similarity,
                "passed": centroid_ok,
            },
        },
    }
