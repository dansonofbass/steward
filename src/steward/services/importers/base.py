from dataclasses import dataclass
from datetime import date

# The longest description a row keeps. Every row a file, a statement or SimpleFIN gives is a ParsedRow, and ingest
# stores only these, so a transaction stored since this cut holds at most this many characters of raw text, and a
# pattern that later runs on it (tidy and normalize, watch payees, rules) reads at most that much. It bounds the
# length of that input, not a pattern's cost on it: a quadratic pattern still takes on the order of a million steps
# here, and an exponential one isn't saved. It does nothing for patterns that read the file before its rows are built
# (the scan in tests/test_linear_parsing.py covers those), for a row's other fields, or for rows stored before the
# cut. A real bank's text is a few hundred characters at most; a 5 MB OFX name is not (SEC-3's class). A cut row ends
# in "…", so the cut shows.
DESCRIPTION_MAX = 1000


@dataclass(frozen=True)
class ParsedRow:
    posted_at: date
    amount_cents: int
    raw_description: str
    external_id: str | None = None
    page: int | None = None          # PDF statements spec P42: the statement page a row was read from

    def __post_init__(self):
        d = self.raw_description
        if isinstance(d, str) and len(d) > DESCRIPTION_MAX:
            object.__setattr__(self, "raw_description", d[:DESCRIPTION_MAX - 1] + "…")


class ParseError(ValueError):
    def __init__(self, row: int, reason: str):
        super().__init__(f"Row {row}: {reason}")
        self.row = row
        self.reason = reason
