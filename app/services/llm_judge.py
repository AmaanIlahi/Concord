import json
import logging

from openai import OpenAI
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Conflict, Match, MatchJob, Record

logger = logging.getLogger(__name__)

client = OpenAI(api_key=settings.openai_api_key)

MAX_ATTEMPTS = 2

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


def _call_judge(record_a: dict, record_b: dict) -> dict | None:
    user_prompt = json.dumps({"record_a": record_a, "record_b": record_b})

    for attempt in range(MAX_ATTEMPTS):
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw_content = response.choices[0].message.content

        try:
            verdict = json.loads(raw_content)
            if not isinstance(verdict, dict) or "match" not in verdict:
                raise ValueError("Response missing required 'match' field")
            return verdict
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(
                "LLM judge attempt %d/%d failed to parse: %s. Raw response: %r",
                attempt + 1,
                MAX_ATTEMPTS,
                e,
                raw_content,
            )

    return None


def run_llm_judge(db: Session, match_job: MatchJob) -> int:
    matches = (
        db.query(Match)
        .filter(Match.job_id == match_job.id, Match.final_status == "pending_judge")
        .all()
    )

    record_ids = {m.record_a_id for m in matches} | {m.record_b_id for m in matches}
    records_by_id = {
        r.id: r for r in db.query(Record).filter(Record.id.in_(record_ids)).all()
    }

    for match in matches:
        record_a = records_by_id[match.record_a_id]
        record_b = records_by_id[match.record_b_id]

        verdict = _call_judge(record_a.canonical_json or {}, record_b.canonical_json or {})

        if verdict is None:
            match.final_status = "needs_manual_review"
            continue

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

    db.flush()
    return len(matches)
