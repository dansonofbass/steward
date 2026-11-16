"""The households How it works' grouping is checked on (polish round P29): the synthetic one, and variants that bring
in every conditional line. Nothing here is real."""
from dataclasses import replace

from steward.engine.inputs import Levers
from steward.engine.synthetic import synthetic_household

_hh = synthetic_household().household
CASES = {
    "base": (_hh, Levers()),
    "full_ss": (_hh, Levers(full_ss_benefits=True)),
    "ny_young_stale": (replace(_hh, state="NY", spending_months=7, spouse=replace(_hh.spouse, earnings=()),
                               default_mix_symbols=("ZZFUNDX",),
                               stale_notes=("Lifespans use the male life table for JR and the female one for Sam.",
                                            "The single filing status is taxed with the single brackets (approximate).",
                                            "Taxable's balance was last updated 120 days ago.")), Levers()),
    "no_kids_paid_off": (replace(_hh, children=(), mortgage_payoff_year=2020, jr=replace(_hh.jr, estimated=True)), Levers()),
}
