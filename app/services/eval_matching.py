import csv
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Match, MatchJob, Record

PREDICTED_MATCH_STATUSES = {"auto_accepted", "accepted_with_conflicts"}


def _load_gold_pairs(gold_csv_path: Path) -> set[tuple[str, str]]:
    with open(gold_csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return {(row["idAmazon"], row["idGoogleBase"]) for row in reader}


def _is_predicted_match(match: Match) -> bool:
    if match.final_status in PREDICTED_MATCH_STATUSES:
        return True
    if match.llm_verdict and match.llm_verdict.get("match") is True:
        return True
    return False


def compute_matching_accuracy(db: Session, match_job: MatchJob, gold_csv_path: Path) -> dict:
    """Precision/recall/F1 against a gold-standard match file, comparing each
    match's predicted status to the gold set of true (idAmazon, idGoogleBase) pairs.
    Assumes match_job.dataset_a_id is the Amazon-sourced dataset and dataset_b_id is
    the Google-sourced dataset (source ids are read from Record.raw_json["id"])."""
    gold_pairs = _load_gold_pairs(gold_csv_path)

    matches = db.query(Match).filter(Match.job_id == match_job.id).all()

    record_ids = {m.record_a_id for m in matches} | {m.record_b_id for m in matches}
    records_by_id = {
        r.id: r for r in db.query(Record).filter(Record.id.in_(record_ids)).all()
    }

    true_positives = 0
    false_positives = 0
    predicted_pairs = set()

    for match in matches:
        record_a = records_by_id[match.record_a_id]
        record_b = records_by_id[match.record_b_id]
        source_id_a = (record_a.raw_json or {}).get("id")
        source_id_b = (record_b.raw_json or {}).get("id")
        pair = (source_id_a, source_id_b)

        if _is_predicted_match(match):
            predicted_pairs.add(pair)
            if pair in gold_pairs:
                true_positives += 1
            else:
                false_positives += 1

    false_negatives = len(gold_pairs) - true_positives

    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) else 0.0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return {
        "gold_pair_count": len(gold_pairs),
        "predicted_pair_count": len(predicted_pairs),
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        # False if hybrid scoring had no field alignment to work with and fell back
        # to blocking_score alone (see hybrid_scoring.run_hybrid_scoring) — these
        # precision/recall numbers were computed on a degraded signal and should be
        # called out, not reported as equivalent to a normal run.
        "string_similarity_available": match_job.string_similarity_available,
    }


def compute_confidence_calibration(db: Session, match_job: MatchJob, gold_csv_path: Path) -> dict:
    """Buckets judged pairs by llm_verdict.confidence and reports actual accuracy
    (agreement with the gold set) within each bucket. 'Correct' means the judge's
    match/no-match call agrees with whether the pair is truly in the gold set."""
    gold_pairs = _load_gold_pairs(gold_csv_path)

    matches = (
        db.query(Match)
        .filter(Match.job_id == match_job.id, Match.llm_verdict.isnot(None))
        .all()
    )

    record_ids = {m.record_a_id for m in matches} | {m.record_b_id for m in matches}
    records_by_id = {
        r.id: r for r in db.query(Record).filter(Record.id.in_(record_ids)).all()
    }

    buckets = {"high": [], "medium": [], "low": []}

    for match in matches:
        confidence = match.llm_verdict.get("confidence")
        if confidence not in buckets:
            continue

        record_a = records_by_id[match.record_a_id]
        record_b = records_by_id[match.record_b_id]
        source_id_a = (record_a.raw_json or {}).get("id")
        source_id_b = (record_b.raw_json or {}).get("id")
        is_gold_match = (source_id_a, source_id_b) in gold_pairs

        predicted_match = match.llm_verdict.get("match") is True
        buckets[confidence].append(predicted_match == is_gold_match)

    calibration = {}
    for confidence, outcomes in buckets.items():
        if outcomes:
            accuracy = sum(outcomes) / len(outcomes)
        else:
            accuracy = None
        calibration[confidence] = {"count": len(outcomes), "accuracy": accuracy}

    return calibration


def compute_cost_efficiency(db: Session, match_job: MatchJob) -> dict:
    """Fraction of candidate pairs resolved by hybrid scoring alone
    (auto_accepted/auto_rejected assigned before judging) vs. escalated to the judge."""
    matches = db.query(Match).filter(Match.job_id == match_job.id).all()
    total = len(matches)
    escalated = sum(1 for m in matches if m.llm_verdict is not None or m.final_status == "needs_manual_review")
    resolved_by_hybrid_alone = total - escalated

    return {
        "total_candidate_pairs": total,
        "resolved_by_hybrid_alone": resolved_by_hybrid_alone,
        "escalated_to_judge": escalated,
        "hybrid_only_fraction": resolved_by_hybrid_alone / total if total else 0.0,
        "escalated_fraction": escalated / total if total else 0.0,
    }
