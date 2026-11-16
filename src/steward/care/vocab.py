"""Care's stored words. steward_boundary.vocab repeats LEVELS, ROOMS and MEDI_CAL_STATUSES for the chat tool;
tests/advisor/test_vocab_parity.py keeps them equal."""
from __future__ import annotations

LEVELS = ("at_home", "in_home_help", "assisted_living", "memory_care", "nursing_home")
ROOMS = ("shared", "private")
COST_KEYS = ("in_home_hourly", "adult_day_daily", "assisted_living_monthly", "memory_care_monthly",
             "nursing_home_shared_monthly", "nursing_home_private_monthly")
MEDI_CAL_STATUSES = ("eligible", "over_limit", "after_spend_down")
MAX_SCENARIOS = 5
