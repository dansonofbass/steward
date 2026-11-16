"""The Sample book never syncs and never reaches Claude (guided setup spec 8.3, layer 3).

The registry marks a Sample's engine with an execution option, so any code holding only an engine or a session
(the bank sync, the chat switch) can tell, without a book row in hand."""
from __future__ import annotations

SAMPLE_OPTION = "steward_sample"
SAMPLE_REFUSED = "The Sample book is for looking around. It doesn't do that."


class SampleRefused(RuntimeError):
    """Something that reaches a bank, Claude, a file or a person was asked of a Sample book."""


def is_sample(bind) -> bool:
    return bool(bind.get_execution_options().get(SAMPLE_OPTION))
