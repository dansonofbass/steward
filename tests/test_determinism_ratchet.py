"""JR's rule for tests, checked (flaky-test audit S8): a test waits for the real event, never for time. That means no
sleep standing in for "it has happened", no wall-clock budget outside tests/perf, no fake timers tied back to real
time, no clock a test can't freeze, and no React.lazy that skips the test preload. This test reads the trees and fails
on any new offender. tests/determinism_allowlist.txt names the old ones, per file and rule, and may only shrink."""
from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "tests" / "determinism_allowlist.txt"
WEB_TESTS = (".test.ts", ".test.tsx")


@dataclass(frozen=True)
class Rule:
    name: str
    base: str                           # folder under the repo
    suffixes: tuple[str, ...]           # file names it reads end with one of these
    pattern: str                        # one offence per match
    why: str
    skip: tuple[str, ...] = ()          # repo paths it doesn't read: files, or folders ending in /
    not_suffixes: tuple[str, ...] = ()  # file names it doesn't read end with one of these


PY_SKIP = ("tests/perf/", "tests/waiting.py", "tests/test_determinism_ratchet.py")
RULES = (
    Rule("py-sleep", "tests", (".py",), r"\btime\.sleep\(", "wait for the event (tests/waiting.py), never a time", PY_SKIP),
    Rule("py-timer", "tests", (".py",), r"\bthreading\.Timer\(", "when_waiting() acts once the card is up", PY_SKIP),
    Rule("py-async-sleep", "tests", (".py",), r"\basyncio\.sleep\((?!0\))", "hang on asyncio.Event(); signal with one",
         PY_SKIP),
    Rule("py-wall-clock", "tests", (".py",), r"\b(?:monotonic|perf_counter|process_time)\(\)|\btime\.time\(\)",
         "budgets live in tests/perf; deadlines in wait_until()", PY_SKIP),
    Rule("py-real-now", "tests", (".py",), r"\bdatetime\.now\(|\bdate\.today\(", "use steward.clock (fake_clock)",
         PY_SKIP),
    Rule("py-partial-freeze", "tests", (".py",),
         r"""["']steward\.deps\.(?:now|today)["']|\bsetattr\(\s*deps\s*,\s*["'](?:now|today)["']""",
         "patch steward.clock.now: steward.deps.now misses every module that imported it by name", PY_SKIP),
    Rule("src-real-now", "src/steward", (".py",), r"\bdatetime\.now\(|\bdate\.today\(",
         "read the time through steward.clock", ("src/steward/clock.py",)),
    Rule("web-advance-time", "web/src", WEB_TESTS, r"shouldAdvanceTime",
         "plain fake timers: Testing Library advances them"),
    Rule("web-vi-fake-timers", "web/src", WEB_TESTS, r"\bvi\.useFakeTimers\(",
         "useFakeTimers() from test-clock keeps the frozen date"),
    Rule("web-timeout", "web/src", WEB_TESTS, r"\btimeout:\s*\d",
         "remove the cause (preload, fake timers), never raise the ceiling"),
    Rule("web-sleep", "web/src", WEB_TESTS, r"new Promise\(\s*\(?\s*\w*\s*\)?\s*=>\s*(?:window\.)?setTimeout\(",
         "await the real event (isFetching() === 0, a callback), or use fake timers"),
    Rule("web-lazy", "web/src", (".ts", ".tsx"), r"\blazy(?:<.*?>)?\(", "lazyScreen(), so tests preload it",
         ("web/src/lib/lazyScreen.ts",), WEB_TESTS),
    Rule("e2e-fixed-wait", "web/e2e", (".ts",), r"\bwaitForTimeout\(",
         "wait for the condition (toHaveURL, animationsSettled)"),
    Rule("e2e-data-skip", "web/e2e", (".ts",), r"\btest\.skip\([^;]*\bawait\b",
         "restoreVault() makes the data certain: assert it"),
)
WHY = {r.name: r.why for r in RULES} | {"e2e-restore": "call restoreVault() in test.beforeAll"}
# A spec whose every test runs on the empty households (its baseURL fixture is EMPTY_PORT, and it never names the demo
# port) needs no restoreVault(): the keeper holds only the demo vault, and the empty-household specs build on each
# other in order (profile.spec, then welcome.spec).
EMPTY_ONLY = re.compile(r"\bbase\.extend\(\{\s*baseURL:.{0,300}?\bEMPTY_PORT\b", re.S)


def empty_only(text: str) -> bool:
    return bool(EMPTY_ONLY.search(text)) and "DEMO_PORT" not in text


def files(rule: Rule) -> list[Path]:
    out = []
    for p in sorted((ROOT / rule.base).rglob("*")):
        rel = p.relative_to(ROOT).as_posix()
        if not p.is_file() or "node_modules" in p.parts or not rel.endswith(rule.suffixes):
            continue
        if rule.not_suffixes and rel.endswith(rule.not_suffixes):
            continue
        if any(rel == s or (s.endswith("/") and rel.startswith(s)) for s in rule.skip):
            continue
        out.append(p)
    return out


def offences() -> Counter:
    found: Counter = Counter()
    for rule in RULES:
        rx = re.compile(rule.pattern)
        for p in files(rule):
            n = len(rx.findall(p.read_text(encoding="utf-8")))
            if n:
                found[(p.relative_to(ROOT).as_posix(), rule.name)] += n
    for p in sorted((ROOT / "web" / "e2e").rglob("*.spec.ts")):
        text = p.read_text(encoding="utf-8")
        if not empty_only(text) and "restoreVault" not in text:
            found[(p.relative_to(ROOT).as_posix(), "e2e-restore")] += 1
    return found


def allowed() -> Counter:
    out: Counter = Counter()
    for line in ALLOWLIST.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            path, rule, n = line.split()
            out[(path, rule)] = int(n)
    return out


def test_no_new_offenders():
    ok = allowed()
    over = sorted((k, n, ok.get(k, 0)) for k, n in offences().items() if n > ok.get(k, 0))
    assert not over, "\n" + "\n".join(f"{p}: {rule} x{n} (allowed {a}): {WHY[rule]}" for (p, rule), n, a in over)


def test_the_allowlist_only_shrinks():
    now = offences()
    fixed = sorted((k, a, now.get(k, 0)) for k, a in allowed().items() if now.get(k, 0) < a)
    assert not fixed, "\n" + "\n".join(f"{p}: {rule} is down to {n} from {a}; lower it in tests/determinism_allowlist.txt"
                                       for (p, rule), a, n in fixed)


@pytest.mark.parametrize("rule, caught, spared", [
    ("py-sleep", "time.sleep(0.5)", "wait_until(lambda: x, 'x')"),
    ("py-timer", "threading.Timer(0.05, f).start()", "when_waiting(c, t, f)"),
    ("py-async-sleep", "await asyncio.sleep(5)", "await asyncio.sleep(0)"),
    ("py-wall-clock", "t0 = time.monotonic()", "clock.now()"),
    ("py-real-now", "datetime.now(timezone.utc)", "clock.now()"),
    ("py-partial-freeze", 'monkeypatch.setattr("steward.deps.now", f)', 'monkeypatch.setattr("steward.clock.now", f)'),
    ("py-partial-freeze", 'monkeypatch.setattr(deps, "now", f)', 'monkeypatch.setattr(clock, "now", f)'),
    ("src-real-now", "date.today()", "clock.today()"),
    ("web-advance-time", "vi.useFakeTimers({ shouldAdvanceTime: true })", "useFakeTimers()"),
    ("web-vi-fake-timers", "vi.useFakeTimers()", "useFakeTimers()"),
    ("web-timeout", "findByText('x', {}, { timeout: 3000 })", "findByText('x')"),
    ("web-sleep", "await new Promise((r) => setTimeout(r, 50))", "await vi.advanceTimersByTimeAsync(50)"),
    ("web-lazy", "const Plan = lazy(() => import('./Plan'));", "const Plan = lazyScreen(() => import('./Plan'));"),
    ("web-lazy", "lazy<ComponentType<P>>(() => import('./M'))", "lazyScreen<ComponentType<P>>(() => import('./M'))"),
    ("e2e-fixed-wait", "await page.waitForTimeout(500);", "await expect(page).toHaveURL(/q=/);"),
    ("e2e-data-skip", "test.skip((await fresh.count()) < 3, 'few');", "test.skip(info.project.name !== 'desktop', 'pane');"),
])
def test_the_rules_catch_what_they_name(rule, caught, spared):
    rx = re.compile(next(r.pattern for r in RULES if r.name == rule))
    assert rx.search(caught) and not rx.search(spared)


EMPTY_FIXTURE = """const test = base.extend({
  baseURL: async ({}, use, testInfo) => {
    await use(`http://localhost:${testInfo.project.name === 'phone' ? EMPTY_PORT.phone : EMPTY_PORT.desktop}`);
  },
});"""


@pytest.mark.parametrize("text, spared", [
    (EMPTY_FIXTURE, True),
    (EMPTY_FIXTURE + "\nconst ctx = await browser.newContext({ baseURL: `http://localhost:${DEMO_PORT}` });", False),
    ("const ctx = await browser.newContext({ baseURL: `http://localhost:${EMPTY_PORT.desktop}` });", False),
    ("test('x', async ({ page }) => { await page.goto('/'); });", False),
])
def test_only_empty_household_specs_go_without_restore(text, spared):
    assert empty_only(text) is spared


def test_the_empty_household_specs_are_the_ones_spared():
    spared = sorted(p.name for p in (ROOT / "web" / "e2e").rglob("*.spec.ts") if empty_only(p.read_text(encoding="utf-8")))
    assert spared == ["profile.spec.ts", "welcome.spec.ts"]


HEADER = """# Grandfathered offences against tests/test_determinism_ratchet.py: path, rule, count  # why it stays.
# It may only shrink. Never add a line to make a new test pass: fix the test (flaky-test audit; JR's rule).
"""

if __name__ == "__main__":
    if sys.argv[1:] != ["--write"]:
        raise SystemExit("usage: uv run python tests/test_determinism_ratchet.py --write")
    ALLOWLIST.write_text(HEADER + "".join(f"{p}\t{rule}\t{n}\n" for (p, rule), n in sorted(offences().items())))
