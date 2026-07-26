from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Match, Record

TOP_K = 5


def run_blocking(db: Session, job_id, dataset_a_id, dataset_b_id) -> int:
    """For each embedded record in dataset A, finds the top-k nearest records in
    dataset B by pgvector cosine distance (<=>), using the HNSW index on
    records.embedding. Creates a `matches` row per candidate pair with
    blocking_score set to cosine similarity (1 - distance). Returns the number of
    match rows created."""
    records_a = (
        db.query(Record)
        .filter(Record.dataset_id == dataset_a_id, Record.embedding.isnot(None))
        .all()
    )

    match_count = 0
    for record_a in records_a:
        rows = db.execute(
            text(
                """
                SELECT id, embedding <=> :embedding AS distance
                FROM records
                WHERE dataset_id = :dataset_b_id AND embedding IS NOT NULL
                ORDER BY embedding <=> :embedding
                LIMIT :top_k
                """
            ),
            {
                "embedding": str(record_a.embedding),
                "dataset_b_id": str(dataset_b_id),
                "top_k": TOP_K,
            },
        ).fetchall()

        for record_b_id, distance in rows:
            db.add(
                Match(
                    job_id=job_id,
                    record_a_id=record_a.id,
                    record_b_id=record_b_id,
                    blocking_score=1 - distance,
                    final_status=None,
                )
            )
            match_count += 1

    db.flush()
    return match_count
