import steward.engine as engine


def test_public_surface_is_exported():
    names = ["solve", "SolveResult", "BandPoint", "lever_impacts", "LeverImpact", "savings_checklist", "ChecklistInputs",
             "ChecklistItem", "EngineInputs", "Household", "Person", "Child", "Bucket", "OneOffCost", "Mix", "Levers", "InputError",
             "validate", "digest", "clamp", "default_try", "ObservedTry", "LEVERS", "ENGINE_VERSION",
             "annual_tax", "TaxFacts", "TaxResult", "StateResult", "project", "ProjectionInputs", "Assumptions", "Income",
             "Expense", "LtcPolicy", "HomeSale", "YearRow", "money_lasts_until", "ltc_runs_out"]
    for n in names:
        assert hasattr(engine, n), n
    assert engine.ENGINE_VERSION == "2026.10.5"
