import csv
import io

from steward.services.importers.base import ParseError


def read_rows(text: str) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    """Return the header and (line number, row) pairs. Blank lines are skipped."""
    text = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    try:
        header = [h.strip() for h in (reader.fieldnames or [])]
        reader.fieldnames = header
        rows = [
            (reader.line_num, {k: (v or "").strip() for k, v in row.items() if k is not None})
            for row in reader
        ]
    except csv.Error:
        raise ParseError(0, "This file couldn't be read as a CSV. Save it again as a plain CSV and try once more.") from None
    return header, rows


def header_of(text: str) -> list[str]:
    return read_rows(text)[0]
