"""Standalone diagnostic run of the compatibility check against already-uploaded
datasets, printing the same intermediate signals as the earlier manual debugging:
field descriptions, pairwise similarity matrix, domain classification, and now
whether any field triggered insufficient_data."""
import sys

import numpy as np

from app.db import SessionLocal
from app.models import Dataset
from app.services.compatibility_check import (
    _cosine_similarity,
    _embed_records,
    _sample_records,
    _top_up_sparse_fields,
)
from app.services.domain_classification import classify_domain
from app.services.field_alignment import FIELD_ALIGNMENT_THRESHOLD, _field_description
from app.services.embeddings import embed_texts


def main(dataset_a_id: str, dataset_b_id: str):
    db = SessionLocal()
    try:
        dataset_a = db.get(Dataset, dataset_a_id)
        dataset_b = db.get(Dataset, dataset_b_id)

        fields_a = list((dataset_a.schema_mapping or {}).keys())
        fields_b = list((dataset_b.schema_mapping or {}).keys())
        print(f"fields_a: {fields_a}")
        print(f"fields_b: {fields_b}")

        records_a = _sample_records(db, dataset_a_id)
        records_b = _sample_records(db, dataset_b_id)
        print(f"\nInitial random sample sizes: a={len(records_a)} b={len(records_b)}")

        records_a, insufficient_a = _top_up_sparse_fields(db, dataset_a_id, fields_a, records_a)
        records_b, insufficient_b = _top_up_sparse_fields(db, dataset_b_id, fields_b, records_b)
        print(f"After top-up sizes: a={len(records_a)} b={len(records_b)}")
        print(f"insufficient_data_fields: a={sorted(insufficient_a)} b={sorted(insufficient_b)}")

        centroid_a = _embed_records(db, records_a)
        centroid_b = _embed_records(db, records_b)
        centroid_similarity = _cosine_similarity(centroid_a, centroid_b)
        print(f"\nCentroid cosine similarity: {centroid_similarity:.4f}")

        sample_canonical_a = [r.canonical_json for r in records_a]
        sample_canonical_b = [r.canonical_json for r in records_b]

        for field in fields_a:
            non_empty = sum(1 for r in sample_canonical_a if r.get(field) not in (None, ""))
            print(f"  A.{field}: {non_empty}/{len(sample_canonical_a)} non-empty")
        for field in fields_b:
            non_empty = sum(1 for r in sample_canonical_b if r.get(field) not in (None, ""))
            print(f"  B.{field}: {non_empty}/{len(sample_canonical_b)} non-empty")

        matchable_a = [f for f in fields_a if f not in insufficient_a]
        matchable_b = [f for f in fields_b if f not in insufficient_b]

        descriptions_a = [_field_description(f, sample_canonical_a) for f in matchable_a]
        descriptions_b = [_field_description(f, sample_canonical_b) for f in matchable_b]

        print("\nField description strings (truncated to 200 chars):")
        for f, d in zip(matchable_a, descriptions_a):
            print(f"  A.{f}: {d[:200]!r}")
        for f, d in zip(matchable_b, descriptions_b):
            print(f"  B.{f}: {d[:200]!r}")

        if matchable_a and matchable_b:
            embeddings = embed_texts(descriptions_a + descriptions_b)
            vectors_a = [np.array(e) for e in embeddings[: len(matchable_a)]]
            vectors_b = [np.array(e) for e in embeddings[len(matchable_a):]]

            print(f"\nPairwise cosine similarity matrix (threshold={FIELD_ALIGNMENT_THRESHOLD}):")
            header = " " * 20 + " ".join(f"{fb:>16}" for fb in matchable_b)
            print(header)
            for fa, va in zip(matchable_a, vectors_a):
                row = [f"{_cosine_similarity(va, vb):.4f}" for vb in vectors_b]
                print(f"{fa:>20}" + " ".join(f"{r:>16}" for r in row))
        else:
            print("\nNo matchable fields on one or both sides (all insufficient_data) — skipping similarity matrix.")

        print("\nRunning domain classification...")
        domain_a = classify_domain(fields_a, sample_canonical_a[:3])
        domain_b = classify_domain(fields_b, sample_canonical_b[:3])
        print(f"  domain_a: {domain_a!r}")
        print(f"  domain_b: {domain_b!r}")
        print(f"  match: {domain_a.strip().lower() == domain_b.strip().lower()}")

    finally:
        db.close()


if __name__ == "__main__":
    dataset_a_id = sys.argv[1]
    dataset_b_id = sys.argv[2]
    main(dataset_a_id, dataset_b_id)
