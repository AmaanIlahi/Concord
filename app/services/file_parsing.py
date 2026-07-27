import csv
import io
import json

from app.services.text_sanitize import sanitize_text


class UnsupportedFileType(Exception):
    pass


def _sanitize_row(row: dict) -> dict:
    return {k: sanitize_text(v) for k, v in row.items()}


def parse_upload(filename: str, content: bytes) -> list[dict]:
    if filename.lower().endswith(".csv"):
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        return [_sanitize_row(dict(row)) for row in reader]

    if filename.lower().endswith(".json"):
        data = json.loads(content.decode("utf-8"))
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            raise UnsupportedFileType("JSON file must contain an object or a list of objects")
        return [_sanitize_row(row) for row in data]

    raise UnsupportedFileType(f"Unsupported file type: {filename}")
