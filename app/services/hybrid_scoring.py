import logging

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from app.models import Match, MatchJob, Record

logger = logging.getLogger(__name__)

STRING_SCORE_WEIGHT = 0.5
BLOCKING_SCORE_WEIGHT = 0.5

HYBRID_HIGH_THRESHOLD = 0.85
HYBRID_LOW_THRESHOLD = 0.3


def _string_similarity(record_a: Record, record_b: Record, field_alignment: dict) -> float:
    """Average rapidfuzz token_sort_ratio (0-1) across each aligned canonical
    field pair. Fields with no value on either side are skipped."""
    canonical_a = record_a.canonical_json or {}
    canonical_b = record_b.canonical_json or {}

    scores = []
    for field_a, field_b in field_alignment.items():
        value_a = canonical_a.get(field_a)
        value_b = canonical_b.get(field_b)
        if value_a in (None, "") or value_b in (None, ""):
            continue
        scores.append(fuzz.token_sort_ratio(str(value_a), str(value_b)) / 100.0)

    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def _assign_status(hybrid_score: float) -> str:
    if hybrid_score >= HYBRID_HIGH_THRESHOLD:
        return "auto_accepted"
    if hybrid_score <= HYBRID_LOW_THRESHOLD:
        return "auto_rejected"
    return "pending_judge"


def run_hybrid_scoring(db: Session, match_job: MatchJob) -> list[dict]:
    """Scores every candidate pair from blocking, persisting hybrid_score and
    final_status on each Match row. Returns per-pair details (including the
    string_score component, which isn't a persisted column) for callers that
    want to inspect the score breakdown.

    If the compatibility check produced no field alignment at all (field_overlap
    found zero shared fields), there is no meaningful string-similarity signal to
    compute — falling back to string_score=0.0 for every pair would silently read
    as "definitely different" when it actually means "never compared." Instead,
    hybrid_score falls back to blocking_score alone for the whole job, and
    match_job.string_similarity_available is set to False so this degraded-signal
    run stays visible to any caller (including the eval module) rather than being
    indistinguishable from a normal run with real string scores."""
    field_alignment = (
        match_job.compatibility_check.get("signals", {})
        .get("field_overlap", {})
        .get("alignment", {})
    )
    string_similarity_available = bool(field_alignment)
    match_job.string_similarity_available = string_similarity_available

    if not string_similarity_available:
        logger.warning(
            "Match job %s has an empty field alignment (field_overlap found no "
            "shared fields) — falling back to blocking_score alone for every pair "
            "in this job. string_similarity_available=False.",
            match_job.id,
        )

    matches = db.query(Match).filter(Match.job_id == match_job.id).all()

    record_ids = {m.record_a_id for m in matches} | {m.record_b_id for m in matches}
    records_by_id = {
        r.id: r for r in db.query(Record).filter(Record.id.in_(record_ids)).all()
    }

    results = []
    for match in matches:
        record_a = records_by_id[match.record_a_id]
        record_b = records_by_id[match.record_b_id]

        if string_similarity_available:
            string_score = _string_similarity(record_a, record_b, field_alignment)
            hybrid_score = (
                STRING_SCORE_WEIGHT * string_score
                + BLOCKING_SCORE_WEIGHT * match.blocking_score
            )
        else:
            string_score = None
            hybrid_score = match.blocking_score

        match.hybrid_score = hybrid_score
        match.final_status = _assign_status(hybrid_score)

        results.append(
            {
                "match_id": match.id,
                "record_a_id": match.record_a_id,
                "record_b_id": match.record_b_id,
                "blocking_score": match.blocking_score,
                "string_score": string_score,
                "hybrid_score": hybrid_score,
                "final_status": match.final_status,
            }
        )

    db.flush()
    return results
