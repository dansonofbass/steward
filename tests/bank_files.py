"""The bank fixtures (import/export spec, Testing › Fixtures). Most are files in tests/fixtures/banks/; the ones that
need exact bytes (a BOM with CRLF, UTF-16, a ZIP) or are long and regular (200 rows) are built here. All synthetic."""
from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "banks"

_CHASE_CARD = (
    "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
    "10/03/2024,10/04/2024,TRADER JOE'S #552,Groceries,Sale,-64.18,\n"
    "10/05/2024,10/05/2024,PAYMENT THANK YOU-MOBILE,,Payment,500.00,\n"
    "10/07/2024,10/08/2024,STREAMFLIX.COM,Entertainment,Sale,-15.49,\n"
    "10/09/2024,10/10/2024,\"CORNER HARDWARE, INC\",Home,Sale,-42.10,\n"
    "10/12/2024,10/13/2024,CORNER HARDWARE RETURN,Home,Return,12.00,\n"
)


def _rows(n: int, bad: int) -> bytes:
    """`n` rows of a generic card file, the first `bad` of them with a date that isn't one."""
    lines = ["Date,Description,Amount"]
    for i in range(n):
        day = f"10/{(i % 28) + 1:02d}/2024" if i >= bad else "13/45/2024"
        lines.append(f"{day},SHOP {i},-{(i % 90) + 1}.{i % 100:02d}")
    return ("\n".join(lines) + "\n").encode()


GENERATED: dict[str, bytes] = {
    "chase-card.csv": b"\xef\xbb\xbf" + _CHASE_CARD.replace("\n", "\r\n").encode(),
    "utf16-bom.csv": "Date,Description,Amount\n10/14/2024,CAFÉ LUNE,-4.50\n10/15/2024,HARBOR GROCERY,-20.00\n".encode("utf-16"),
    "tab.tsv": ("Date\tDescription\tAmount\n10/14/2024\tCAFE LUNE\t-4.50\n10/15/2024\tHARBOR GROCERY\t-20.00\n").encode(),
    "renamed.xlsx.csv": b"PK\x03\x04\x14\x00\x06\x00" + bytes(40),
    "empty.csv": b"",
    "bad-rows.csv": _rows(200, 3),
    "mostly-bad.csv": _rows(200, 30),
}


def read(name: str) -> bytes:
    return GENERATED[name] if name in GENERATED else (FIXTURES / name).read_bytes()


def text(name: str) -> str:
    return read(name).decode("utf-8-sig")
