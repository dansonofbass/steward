import pytest

from steward.services.ss_import import NOT_A_RECORD, NotAnEarningsRecord, parse_earnings


def statement(rows: str, name: str = "Pat Example") -> bytes:
    """A synthetic my Social Security file in the OSSS 2.0 shape. Every value is made up."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<osss:OnlineSocialSecurityStatementData xmlns:osss="http://ssa.gov/osss/schemas/2.0">
  <osss:FileCreationDate>2026-10-01</osss:FileCreationDate>
  <osss:UserInformation>
    <osss:Name>{name}</osss:Name>
    <osss:DateOfBirth>1982-05-01</osss:DateOfBirth>
  </osss:UserInformation>
  <osss:EstimatedBenefits><osss:FullRetirementEstimate>2500</osss:FullRetirementEstimate></osss:EstimatedBenefits>
  <osss:EarningsRecord>{rows}</osss:EarningsRecord>
</osss:OnlineSocialSecurityStatementData>""".encode()


def row(year, fica, end=None) -> str:
    end = year if end is None else end
    return (f'<osss:Earnings startYear="{year}" endYear="{end}"><osss:FicaEarnings>{fica}</osss:FicaEarnings>'
            f'<osss:MedicareEarnings>{fica}</osss:MedicareEarnings></osss:Earnings>')


def test_years_and_taxed_earnings_round_trip():
    p = parse_earnings(statement(row(2005, 30000) + row(2006, "31500.50") + row(2004, 0)), latest_year=2026)
    assert p.years == ((2004, 0), (2005, 3_000_000), (2006, 3_150_050)) and p.skipped == 0


def test_not_yet_posted_and_multi_year_rows_are_skipped():
    p = parse_earnings(statement(row(2025, 50000) + row(2026, -1) + row(1937, 900, end=1950)), latest_year=2026)
    assert p.years == ((2025, 5_000_000),) and p.skipped == 2


@pytest.mark.parametrize("raw", [
    b"",
    b"not xml at all",
    b"<html><body>Sign in to my Social Security</body></html>",
    b'<osss:Other xmlns:osss="http://ssa.gov/osss/schemas/2.0"/>',
    b'<OnlineSocialSecurityStatementData><EarningsRecord/></OnlineSocialSecurityStatementData>',   # no namespace
    statement(""),                                         # no earnings at all
    statement(row(2005, "lots")),
    statement(row(2005, -20)),
    statement(row(2030, 1000)),                            # in the future
    statement(row(2005, 1) + row(2005, 2)),                # the same year twice
    statement('<osss:Earnings startYear="x" endYear="x"><osss:FicaEarnings>1</osss:FicaEarnings></osss:Earnings>'),
    statement('<osss:Earnings startYear="2005" endYear="2005"></osss:Earnings>'),
    statement(row(2005, "1e30")),
    "<?xml version='1.0' encoding='UTF-8'?><a>\udcff</a>".encode("utf-8", "surrogatepass"),
])
def test_anything_else_is_not_an_earnings_record(raw):
    with pytest.raises(NotAnEarningsRecord, match=NOT_A_RECORD.replace(".", r"\.")):
        parse_earnings(raw, latest_year=2026)


@pytest.mark.parametrize("raw", [
    b'<?xml version="1.0"?><!DOCTYPE z [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
    b'<osss:OnlineSocialSecurityStatementData xmlns:osss="http://ssa.gov/osss/schemas/2.0">&b;</osss:OnlineSocialSecurityStatementData>',
    b'<?xml version="1.0"?><!DOCTYPE z [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
    b'<osss:OnlineSocialSecurityStatementData xmlns:osss="http://ssa.gov/osss/schemas/2.0">&x;</osss:OnlineSocialSecurityStatementData>',
])
def test_entities_are_refused(raw):
    with pytest.raises(NotAnEarningsRecord):
        parse_earnings(raw, latest_year=2026)
