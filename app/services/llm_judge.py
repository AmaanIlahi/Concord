import asyncio
import json
import logging

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Conflict, Match, MatchJob, Record
from app.services.text_sanitize import sanitize_json

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=settings.openai_api_key)

MAX_ATTEMPTS = 2
MAX_CONCURRENT_JUDGE_CALLS = 10
COMMIT_EVERY_N_PAIRS = 50

MAX_RATE_LIMIT_RETRIES = 5
RATE_LIMIT_BACKOFF_BASE_SECONDS = 2

# Transient failures worth backing off and retrying, distinct from a malformed
# response (handled separately by the MAX_ATTEMPTS loop in _call_judge_inner).
RETRYABLE_ERRORS = (RateLimitError, APITimeoutError, APIConnectionError)


async def _create_with_rate_limit_retry(**kwargs):
    for attempt in range(MAX_RATE_LIMIT_RETRIES):
        try:
            return await client.chat.completions.create(**kwargs)
        except RETRYABLE_ERRORS as e:
            if attempt == MAX_RATE_LIMIT_RETRIES - 1:
                raise
            backoff = RATE_LIMIT_BACKOFF_BASE_SECONDS * (2 ** attempt)
            logger.warning(
                "%s from OpenAI (attempt %d/%d), backing off %ds",
                type(e).__name__,
                attempt + 1,
                MAX_RATE_LIMIT_RETRIES,
                backoff,
            )
            await asyncio.sleep(backoff)

SYSTEM_PROMPT = """You are a data integration assistant judging whether two records \
from different datasets refer to the same real-world entity.

Respond with a single JSON object in exactly this shape:
{
  "match": true or false,
  "confidence": "high" | "medium" | "low",
  "reasoning": "<one sentence, plain language>",
  "conflicts": [
    {
      "field": "<canonical field name>",
      "value_a": "...",
      "value_b": "...",
      "type": "unit_mismatch" | "stale_data" | "contradiction" | "formatting_difference" | "none"
    }
  ]
}

Only include entries in "conflicts" for fields whose values genuinely differ in a \
meaningful way between the two records. If there are no meaningful conflicts, return \
an empty list."""


async def _call_judge(semaphore: asyncio.Semaphore, match_id, record_a: dict, record_b: dict):
    """Returns (match_id, verdict_or_None) so the caller can match results back to
    the right Match row as they complete, in any order."""
    verdict = await _call_judge_inner(semaphore, record_a, record_b)
    return match_id, verdict


async def _call_judge_inner(semaphore: asyncio.Semaphore, record_a: dict, record_b: dict) -> dict | None:
    user_prompt = json.dumps({"record_a": record_a, "record_b": record_b})

    async with semaphore:
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = await _create_with_rate_limit_retry(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0,
                )
            except RETRYABLE_ERRORS as e:
                logger.error(
                    "LLM judge exhausted retries for this pair (%s), giving up: %s",
                    type(e).__name__,
                    e,
                )
                return None

            raw_content = response.choices[0].message.content

            try:
                verdict = json.loads(raw_content)
                if not isinstance(verdict, dict) or "match" not in verdict:
                    raise ValueError("Response missing required 'match' field")
                # The model can echo control characters back from its input into
                # reasoning/conflict text; Postgres JSONB and text columns reject
                # those outright, so strip them before this verdict is persisted.
                return sanitize_json(verdict)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(
                    "LLM judge attempt %d/%d failed to parse: %s. Raw response: %r",
                    attempt + 1,
                    MAX_ATTEMPTS,
                    e,
                    raw_content,
                )

    return None


def _apply_verdict(db: Session, match: Match, verdict: dict | None) -> None:
    if verdict is None:
        match.final_status = "needs_manual_review"
        return

    match.llm_verdict = verdict

    for conflict in verdict.get("conflicts", []):
        if conflict.get("type") == "none":
            continue
        db.add(
            Conflict(
                match_id=match.id,
                field_name=conflict.get("field"),
                value_a=conflict.get("value_a"),
                value_b=conflict.get("value_b"),
                conflict_type=conflict.get("type"),
            )
        )


async def _judge_all_incremental(db: Session, matches: list[Match], records_by_id: dict) -> int:
    """Runs judge calls concurrently and applies + commits results to the DB as
    each one completes (every COMMIT_EVERY_N_PAIRS pairs), rather than gathering
    every result before writing anything. A large run (thousands of pairs) that
    fails partway through — e.g. a bad value tripping a Postgres constraint, a
    crash, an interrupted process — keeps whatever was already committed instead
    of losing all prior LLM judge calls, which are the expensive part to redo."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_JUDGE_CALLS)
    matches_by_id = {m.id: m for m in matches}

    tasks = [
        _call_judge(
            semaphore,
            match.id,
            records_by_id[match.record_a_id].canonical_json or {},
            records_by_id[match.record_b_id].canonical_json or {},
        )
        for match in matches
    ]

    processed = 0
    for coro in asyncio.as_completed(tasks):
        match_id, verdict = await coro
        _apply_verdict(db, matches_by_id[match_id], verdict)
        processed += 1

        if processed % COMMIT_EVERY_N_PAIRS == 0:
            db.commit()
            logger.info("LLM judge: committed progress at %d/%d pairs", processed, len(matches))

    db.commit()
    return processed


def run_llm_judge(db: Session, match_job: MatchJob) -> int:
    """Judges every not-yet-judged pending_judge pair for this job. Pairs that
    already have an llm_verdict (e.g. from a prior run of this same job that was
    interrupted partway through, since /judge only sets final_status to
    needs_manual_review on failure and otherwise leaves it as pending_judge) are
    skipped rather than re-judged, so resuming an interrupted job doesn't re-pay
    for LLM calls already made and already committed."""
    matches = (
        db.query(Match)
        .filter(
            Match.job_id == match_job.id,
            Match.final_status == "pending_judge",
            Match.llm_verdict.is_(None),
        )
        .all()
    )

    record_ids = {m.record_a_id for m in matches} | {m.record_b_id for m in matches}
    records_by_id = {
        r.id: r for r in db.query(Record).filter(Record.id.in_(record_ids)).all()
    }

    return asyncio.run(_judge_all_incremental(db, matches, records_by_id))
