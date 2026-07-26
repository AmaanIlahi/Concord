from sqlalchemy.orm import Session

from app.models import Match, MatchJob

TERMINAL_STATUSES = {"auto_accepted", "auto_rejected", "needs_manual_review"}


def _real_conflicts(verdict: dict) -> list[dict]:
    return [c for c in verdict.get("conflicts", []) if c.get("type") != "none"]


def _finalize_status(match: Match) -> str:
    if match.final_status in TERMINAL_STATUSES:
        # auto_accepted/auto_rejected from hybrid scoring skipped the judge;
        # needs_manual_review already reflects a failed judge call.
        return match.final_status

    verdict = match.llm_verdict or {}
    is_match = verdict.get("match")
    confidence = verdict.get("confidence")

    if is_match is False or confidence == "low":
        return "flagged_for_review"

    if is_match is True:
        return "accepted_with_conflicts" if _real_conflicts(verdict) else "auto_accepted"

    return "flagged_for_review"


def run_finalize(db: Session, match_job: MatchJob) -> dict:
    matches = db.query(Match).filter(Match.job_id == match_job.id).all()

    tally: dict[str, int] = {}
    for match in matches:
        match.final_status = _finalize_status(match)
        tally[match.final_status] = tally.get(match.final_status, 0) + 1

    db.flush()
    return tally
