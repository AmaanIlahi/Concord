import json

from openai import OpenAI

from app.config import settings

client = OpenAI(api_key=settings.openai_api_key)

SYSTEM_PROMPT = """You are a data integration assistant. Given a dataset's column \
headers and a few sample rows, infer a canonical field mapping that could be used \
to align this dataset with other datasets describing similar real-world entities \
(e.g. products, businesses, people).

Respond with a single JSON object where each key is a canonical field name \
(lowercase, snake_case, e.g. "name", "price", "category", "address") and each \
value is the original column header from the input that maps to it. Only include \
fields you can confidently infer from the given headers and samples. Do not \
invent canonical fields that have no corresponding column."""


def infer_schema_mapping(headers: list[str], sample_rows: list[dict]) -> dict:
    user_prompt = json.dumps({"headers": headers, "sample_rows": sample_rows[:3]})

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    return json.loads(response.choices[0].message.content)
