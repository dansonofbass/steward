"""Payroll tax on wages (Social Security and Medicare, 26 U.S.C. 3101 and 3111), from payroll_<year>.json.

annual_tax covers income tax, self-employment tax and the additional 0.9% Medicare tax; the 7.65% each side pays on
wages is here, for the S-corp comparison and anything else that pays a salary. Money is integer cents.
"""
from __future__ import annotations

from dataclasses import dataclass

from steward.engine.tax import rules


@dataclass(frozen=True)
class PayrollTax:
    employee_cents: int      # what the employee pays, after the credit for Social Security over the wage base
    employer_cents: int      # what the employer pays; deductible by the business
    rules_year: int

    @property
    def total_cents(self) -> int:
        return self.employee_cents + self.employer_cents


def payroll_tax(wages_cents: int, year: int, other_ss_wages_cents: int = 0) -> PayrollTax:
    """Both halves of Social Security and Medicare tax on `wages_cents` from one employer.

    The employer pays Social Security up to the wage base whatever the employee earns elsewhere. The employee's
    Social Security stops at the wage base less their other Social Security wages (`other_ss_wages_cents`): anything
    withheld beyond that comes back as a credit on their return, so it isn't counted."""
    p = rules.table("payroll", year)
    e, r = p["employee"], p["employer"]
    base = p["wage_base"] * 100
    wages = max(wages_cents, 0)
    employer = min(wages, base) * r["oasdi_rate"] + wages * r["medicare_rate"]
    employee = min(wages, max(base - max(other_ss_wages_cents, 0), 0)) * e["oasdi_rate"] + wages * e["medicare_rate"]
    return PayrollTax(employee_cents=round(employee), employer_cents=round(employer), rules_year=p.year)
