"""The suite's own guards (flaky-test audit S5, S6, S4): a ceiling on every test, half the cores for -n auto, and no
Settings cached from one test into the next."""
import os

import pytest

ENV = {"STEWARD_BASE_URL": "https://nas.tail1234.ts.net", "STEWARD_ENV": "test",
       "STEWARD_SIMPLEFIN_HOSTS": "testserver"}


def test_every_test_has_a_ceiling(pytestconfig):
    """A deadlock fails the run after two minutes instead of freezing the deploy."""
    assert pytestconfig.getini("timeout") == "120"


def test_auto_takes_half_the_cores(pytestconfig):
    from tests.conftest import pytest_xdist_auto_num_workers
    assert pytest_xdist_auto_num_workers(pytestconfig) == max(1, (os.cpu_count() or 2) // 2)


@pytest.mark.parametrize("run", ["first", "second"])
def test_no_settings_are_cached_from_another_test(run, monkeypatch, tmp_path):
    """The first run fills get_settings()'s cache; the second must find it empty."""
    from steward.settings import get_settings
    assert get_settings.cache_info().currsize == 0
    monkeypatch.setenv("STEWARD_DATA_DIR", str(tmp_path))
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    get_settings()
    assert get_settings.cache_info().currsize == 1
