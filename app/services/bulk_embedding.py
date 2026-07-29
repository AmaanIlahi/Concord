from sqlalchemy.orm import Session

from app.models import Record
from app.services.embeddings import embed_texts, record_text

EMBED_BATCH_SIZE = 100


def embed_dataset_records(db: Session, dataset_id) -> dict:
    """Embeds every record in a dataset whose embedding is still null, batching
    OpenAI calls in groups of EMBED_BATCH_SIZE. Records already embedded (e.g. from
    compatibility-check sampling) are skipped, not re-embedded."""
    records = db.query(Record).filter(Record.dataset_id == dataset_id).all()

    to_embed = [r for r in records if r.embedding is None]
    skipped_count = len(records) - len(to_embed)

    for i in range(0, len(to_embed), EMBED_BATCH_SIZE):
        batch = to_embed[i : i + EMBED_BATCH_SIZE]
        vectors = embed_texts([record_text(r) for r in batch])
        for record, vector in zip(batch, vectors):
            record.embedding = vector
        db.flush()

    db.commit()

    return {
        "total_records": len(records),
        "skipped_existing_embedding": skipped_count,
        "newly_embedded": len(to_embed),
    }
