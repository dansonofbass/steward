from datetime import date

from steward.advisor.tools import run_call
from steward.services.plan_cache import PlanCache


def call(engine, book, people, user_id, name, input, today: date, cache: PlanCache | None = None) -> dict:
    """One tool call through the executor, as a turn makes it."""
    return run_call({"id": "toolu_test", "name": name, "input": input}, bind=engine.execution_options(immediate=True),
                    book=book, user_id=user_id, people=tuple(people), today=today, plan_cache=cache or PlanCache())
