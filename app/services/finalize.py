from sqlalchemy.orm import Session

from app.models import Conflict, Match, MatchJob, Record
from app.services.field_diff import diff_fields

TERMINAL_STATUSES = {"auto_accepted", "auto_rejected", "needs_manual_review"}


def _real_llm_conflicts(verdict: dict) -> list[dict]:
    return [c for c in verdict.get("conflicts", []) if c.get("type") != "none"]


def _judged_status(match: Match) -> str:
    verdict = match.llm_verdict or {}
    is_match = verdict.get("match")
    confidence = verdict.get("confidence")

    if is_match is False or confidence == "low":
        return "flagged_for_review"

    if is_match is True:
        return "accepted_with_conflicts" if _real_llm_conflicts(verdict) else "auto_accepted"

    return "flagged_for_review"


def run_finalize(db: Session, match_job: MatchJob) -> dict:
    field_alignment = (
        match_job.compatibility_check.get("signals", {})
        .get("field_overlap", {})
        .get("alignment", {})
    )

    matches = db.query(Match).filter(Match.job_id == match_job.id).all()

    record_ids = {m.record_a_id for m in matches} | {m.record_b_id for m in matches}
    records_by_id = {
        r.id: r for r in db.query(Record).filter(Record.id.in_(record_ids)).all()
    }

    existing_conflict_match_ids = {
        c.match_id
        for c in db.query(Conflict.match_id)
        .filter(Conflict.match_id.in_([m.id for m in matches]))
        .all()
    }

    tally: dict[str, int] = {}
    for match in matches:
        if match.final_status in TERMINAL_STATUSES:
            final_status = match.final_status
        else:
            final_status = _judged_status(match)

        # Field-level diff check runs regardless of path (auto_accepted,
        # auto_rejected, or judged) — a high hybrid/embedding score can still
        # hide a real field discrepancy the LLM judge never saw because the
        # pair auto-accepted before reaching it.
        if match.id not in existing_conflict_match_ids:
            record_a = records_by_id.get(match.record_a_id)
            record_b = records_by_id.get(match.record_b_id)
            if record_a is not None and record_b is not None:
                diffs = diff_fields(
                    record_a.canonical_json or {}, record_b.canonical_json or {}, field_alignment
                )
                for diff in diffs:
                    db.add(
                        Conflict(
                            match_id=match.id,
                            field_name=diff["field"],
                            value_a=diff["value_a"],
                            value_b=diff["value_b"],
                            conflict_type=diff["type"],
                        )
                    )
                if diffs and final_status == "auto_accepted":
                    final_status = "accepted_with_conflicts"

        match.final_status = final_status
        tally[final_status] = tally.get(final_status, 0) + 1

    db.flush()
    return tally
