"""In-memory caches for the plan API (spec 7): results by input digest (LRU, 256 entries), the random draws
(market histories, lifespans) per household shape, so moving a lever never redraws them, and the engine inputs
built from the vault, keyed on (vault write generation, today) so a lever drag never rebuilds them."""
from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable
from datetime import date
from typing import Any, Generic, TypeVar

from steward.db import generation
from steward.engine.inputs import Household
from steward.engine.simulate import Prepared, prepare

RESULT_CACHE_SIZE = 256
PREPARED_CACHE_SIZE = 4


class LRU:
    def __init__(self, size: int):
        self.size = size
        self.hits = 0
        self.misses = 0
        self._items: OrderedDict[Hashable, Any] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> Any | None:
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                self.hits += 1
                return self._items[key]
            self.misses += 1
            return None

    def peek(self, key: Hashable) -> Any | None:
        """get() without counting a hit or a miss or moving the entry: once()'s second look."""
        with self._lock:
            return self._items.get(key)

    def put(self, key: Hashable, value: Any) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


T = TypeVar("T")


class InputsCache(Generic[T]):
    """One built value, kept while the vault is unchanged and the day is the same (controller ruling, final fix
    wave); with a book, while that book and every session naming no book are unchanged (phase 18). The generation is read before building, so a write that commits during a build leaves the value under
    the old key, which no later lookup uses. Builds run outside the lock; two racing builds store the same thing."""

    def __init__(self, book_id: int | None = None):
        self.book_id = book_id
        self.builds = 0
        self._key: tuple[object, date] | None = None
        self._value: T | None = None
        self._lock = threading.Lock()

    def get_or_build(self, today: date, build: Callable[[], T]) -> T:
        key = (generation.current(self.book_id), today)
        with self._lock:
            if self._key == key:
                return self._value  # type: ignore[return-value]
        value = build()
        with self._lock:
            self.builds += 1
            self._key, self._value = key, value
        return value

    def clear(self) -> None:
        with self._lock:
            self._key, self._value = None, None


class PlanCache:
    def __init__(self, results_size: int = RESULT_CACHE_SIZE, prepared_size: int = PREPARED_CACHE_SIZE,
                 book_id: int | None = None):
        self.results = LRU(results_size)
        self.prepared = LRU(prepared_size)
        self.inputs: InputsCache = InputsCache(book_id)
        self._inflight: dict[Hashable, threading.Lock] = {}
        self._inflight_lock = threading.Lock()

    def clear(self) -> None:
        """Everything worked out so far, for when the time zone moves (the day boundaries change)."""
        self.results.clear()
        self.prepared.clear()
        self.inputs.clear()

    def once(self, key: Hashable, compute: Callable[[], Any]) -> Any:
        """The cached result for `key`, or compute() once: a caller that arrives while another computes the same key
        waits for that answer instead of working it out beside it (phase 18: the start-up warm and a first Plan open).
        If the first caller fails, the next one computes."""
        found = self.results.get(key)
        if found is not None:
            return found
        with self._inflight_lock:
            gate = self._inflight.setdefault(key, threading.Lock())
        try:
            with gate:
                found = self.results.peek(key)
                if found is None:
                    found = compute()
                    self.results.put(key, found)
                return found
        finally:
            with self._inflight_lock:
                if self._inflight.get(key) is gate:
                    del self._inflight[key]

    def prepared_for(self, hh: Household) -> Prepared:
        """prepare() depends only on the plan year and each spouse's birth year and sex."""
        key = (hh.plan_year, hh.jr.birth_year, hh.jr.sex, hh.spouse.birth_year, hh.spouse.sex)
        found = self.prepared.get(key)
        if found is None:
            found = prepare(hh)
            self.prepared.put(key, found)
        return found
