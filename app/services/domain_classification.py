import json

from openai import OpenAI

from app.config import settings

client = OpenAI(api_key=settings.openai_api_key)

SYSTEM_PROMPT = """You are a data integration assistant. Given a dataset's canonical \
field names and a few sample records, classify what kind of real-world entity these \
rows represent (e.g. "electronics products", "restaurant listings", "employee records").

Respond with a single JSON object: {"domain": "<short label>"}. Keep the label \
concise (2-5 words), specific enough to distinguish unrelated domains, but general \
enough to match other datasets describing the same kind of entity."""


def classify_domain(canonical_fields: list[str], sample_records: list[dict]) -> str:
    """temperature=0 makes decoding deterministic for a *given* prompt, but the
    caller's sample_records still varies run to run (compatibility_check draws a
    random sample each time), so the wording of the returned label can still
    drift (e.g. "software products" vs "music and software products") even
    though nothing about the model call itself is random. See
    run_compatibility_check's domain_sample_records for how the caller keeps
    this input stable across runs on the same dataset.

    A small sample (e.g. 3 records) is also vulnerable to being unrepresentative
    regardless of whether it's random or fixed — one outlier can skew the label
    even with a deterministic sample. The caller controls how many records are
    passed in; this function uses whatever it's given rather than truncating to
    a hardcoded 3, so bumping the sample size actually takes effect."""
    user_prompt = json.dumps({"fields": canonical_fields, "sample_records": sample_records})

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    return json.loads(response.choices[0].message.content)["domain"]
