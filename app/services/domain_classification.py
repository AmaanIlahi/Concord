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
    user_prompt = json.dumps({"fields": canonical_fields, "sample_records": sample_records[:3]})

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
