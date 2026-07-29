ALLOWED_EXTENSIONS = (".csv", ".json")
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024  # 2MB
MAX_ROW_COUNT = 500


class UploadRejected(Exception):
    pass


def validate_filename(filename: str | None) -> None:
    if not filename or not filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise UploadRejected(
            f"Unsupported file type. Allowed extensions: {', '.join(ALLOWED_EXTENSIONS)}"
        )


def validate_file_size(content: bytes) -> None:
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise UploadRejected(
            f"File too large: {len(content)} bytes exceeds the "
            f"{MAX_FILE_SIZE_BYTES // 1024}KB limit."
        )


def validate_row_count(row_count: int) -> None:
    if row_count > MAX_ROW_COUNT:
        raise UploadRejected(
            f"Too many rows: {row_count} exceeds the {MAX_ROW_COUNT}-row limit."
        )
