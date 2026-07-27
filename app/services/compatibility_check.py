import logging

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Dataset, Record
from app.services.domain_classification import classify_domain
from app.services.embeddings import embed_texts, record_text
from app.services.field_alignment import align_fields

logger = logging.getLogger(__name__)

CENTROID_SAMPLE_SIZE = 50
MIN_NON_EMPTY_PER_FIELD = 5

MIN_SHARED_FIELDS = 2
MIN_CENTROID_SIMILARITY = 0.7


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def _sample_records(db: Session, dataset_id) -> list[Record]:
    return (
        db.query(Record)
        .filter(Record.dataset_id == dataset_id)
        .order_by(func.random())
        .limit(CENTROID_SAMPLE_SIZE)
        .all()
    )


def _top_up_sparse_fields(
    db: Session, dataset_id, fields: list[str], records: list[Record]
) -> tuple[list[Record], set[str]]:
    """Ensures each canonical field has at least MIN_NON_EMPTY_PER_FIELD non-empty
    values across `records`. For any field short of that, runs a targeted query for
    additional records where that field is non-empty and appends them. Returns the
    (possibly extended) record list and the set of fields that still couldn't reach
    the threshold even after exhausting the dataset (genuinely sparse fields)."""
    seen_ids = {r.id for r in records}
    insufficient_fields = set()

    for field in fields:
        non_empty_count = sum(
            1
            for r in records
            if (r.canonical_json or {}).get(field) not in (None, "")
        )
        if non_empty_count >= MIN_NON_EMPTY_PER_FIELD:
            continue

        needed = MIN_NON_EMPTY_PER_FIELD - non_empty_count
        top_up_query = (
            db.query(Record)
            .filter(
                Record.dataset_id == dataset_id,
                Record.canonical_json[field].astext.isnot(None),
                Record.canonical_json[field].astext != "",
            )
        )
        if seen_ids:
            top_up_query = top_up_query.filter(Record.id.notin_(seen_ids))

        top_up_records = top_up_query.order_by(func.random()).limit(needed).all()

        records.extend(top_up_records)
        seen_ids.update(r.id for r in top_up_records)
        non_empty_count += len(top_up_records)

        if non_empty_count < MIN_NON_EMPTY_PER_FIELD:
            logger.warning(
                "Field %r on dataset %s has only %d non-empty value(s) even after "
                "top-up (needed %d); marking insufficient_data.",
                field,
                dataset_id,
                non_empty_count,
                MIN_NON_EMPTY_PER_FIELD,
            )
            insufficient_fields.add(field)

    return records, insufficient_fields


def _embed_records(db: Session, records: list[Record]) -> np.ndarray:
    """Embeds any records in the list still missing an embedding, persisting them
    for reuse (e.g. by the later bulk-embedding step, which skips non-null
    embeddings). Returns the centroid (mean vector) across all given records."""
    to_embed = [r for r in records if r.embedding is None]
    if to_embed:
        vectors = embed_texts([record_text(r) for r in to_embed])
        for record, vector in zip(to_embed, vectors):
            record.embedding = vector
        db.flush()

    all_vectors = [np.array(r.embedding) for r in records]
    return np.mean(all_vectors, axis=0)


def run_compatibility_check(db: Session, dataset_a: Dataset, dataset_b: Dataset) -> dict:
    fields_a = list((dataset_a.schema_mapping or {}).keys())
    fields_b = list((dataset_b.schema_mapping or {}).keys())

    records_a = _sample_records(db, dataset_a.id)
    records_b = _sample_records(db, dataset_b.id)

    records_a, insufficient_fields_a = _top_up_sparse_fields(db, dataset_a.id, fields_a, records_a)
    records_b, insufficient_fields_b = _top_up_sparse_fields(db, dataset_b.id, fields_b, records_b)

    centroid_a = _embed_records(db, records_a)
    centroid_b = _embed_records(db, records_b)
    centroid_similarity = _cosine_similarity(centroid_a, centroid_b)
    centroid_ok = centroid_similarity >= MIN_CENTROID_SIMILARITY

    sample_canonical_a = [r.canonical_json for r in records_a]
    sample_canonical_b = [r.canonical_json for r in records_b]

    alignment_result = align_fields(
        fields_a,
        fields_b,
        sample_canonical_a,
        sample_canonical_b,
        insufficient_fields_a=insufficient_fields_a,
        insufficient_fields_b=insufficient_fields_b,
    )
    shared_field_count = alignment_result["shared_field_count"]
    field_overlap_ok = shared_field_count >= MIN_SHARED_FIELDS

    domain_a = classify_domain(fields_a, sample_canonical_a[:3])
    domain_b = classify_domain(fields_b, sample_canonical_b[:3])
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
                "insufficient_data_fields": alignment_result["insufficient_data_fields"],
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
