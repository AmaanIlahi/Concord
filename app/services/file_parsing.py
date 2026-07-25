import csv
import io
import json


class UnsupportedFileType(Exception):
    pass


def parse_upload(filename: str, content: bytes) -> list[dict]:
    if filename.lower().endswith(".csv"):
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        return [dict(row) for row in reader]

    if filename.lower().endswith(".json"):
        data = json.loads(content.decode("utf-8"))
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            raise UnsupportedFileType("JSON file must contain an object or a list of objects")
        return data

    raise UnsupportedFileType(f"Unsupported file type: {filename}")
