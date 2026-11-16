"""Bytes to text and what a file is (spec P22): UTF-8, cp1252 and UTF-16 by its BOM; an Excel file and a renamed ZIP
are refused in plain words, as is anything that isn't a CSV, OFX or QFX."""
import pytest

from steward.services.importers.decode import EXCEL, NOT_OURS, FileRefused, decode, kind_of
from tests.bank_files import read


def test_utf8_with_a_bom_loses_the_bom():
    assert decode(read("chase-card.csv")).startswith("Transaction Date,")


def test_utf16_by_its_bom():
    assert decode(read("utf16-bom.csv")).splitlines()[1] == "10/14/2024,CAFÉ LUNE,-4.50"


def test_cp1252_when_it_isnt_utf8():
    assert decode("Date,Description,Amount\n10/14/2024,Caf\xe9,-1.00\n".encode("cp1252")).splitlines()[1] == "10/14/2024,Café,-1.00"


@pytest.mark.parametrize("name", ["chase-card.csv", "semicolon.csv", "tab.tsv", "wells-fargo.csv", "utf16-bom.csv"])
def test_csv_files_by_name_or_by_a_delimiter(name):
    raw = read(name)
    assert kind_of(name, raw, decode(raw)) == "csv"
    assert kind_of("download", raw, decode(raw)) == "csv"           # no extension: the first line's delimiter says


@pytest.mark.parametrize("name", ["bank.ofx", "card.qfx", "two-accounts.ofx"])
def test_ofx_by_its_header_or_name(name):
    raw = read(name)
    assert kind_of(name, raw, decode(raw)) == "ofx"
    assert kind_of("statement.txt", raw, decode(raw)) == "ofx"


@pytest.mark.parametrize("name,raw", [
    ("renamed.xlsx.csv", read("renamed.xlsx.csv")), ("statement.xlsx", b"anything"), ("old.xls", b"anything"),
    ("old.csv", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(20)),
])
def test_excel_is_refused_in_plain_words(name, raw):
    with pytest.raises(FileRefused) as e:
        kind_of(name, raw, decode(raw))
    assert e.value.message == EXCEL == "Excel files can't be read yet. Save it as CSV and try again."


@pytest.mark.parametrize("name,raw", [("statement.pdf", b"%PDF-1.4\n%made up\n"), ("notes", b"just words\n"),
                                      ("x.csv", b"a\x00b,c\n")])
def test_anything_else_is_not_a_file_we_read(name, raw):
    with pytest.raises(FileRefused) as e:
        kind_of(name, raw, decode(raw))
    assert e.value.message == NOT_OURS == "Not a CSV, OFX or QFX file."
