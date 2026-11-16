from datetime import datetime, timedelta, timezone

import pytest

from steward_boundary.pairing import PAIR_ALPHABET, short_code
from steward_gateway.pairing import PairRefused, arm, claim, normalize

NOW = datetime(2026, 10, 20, 17, 0, tzinfo=timezone.utc)


def test_a_code_arms_a_window_and_gives_a_token_once(gw_cfg):
    arm(gw_cfg, "abcd-efgh-jkmn-pqrs", NOW)
    token = claim(gw_cfg, "ABCDEFGHJKMNPQRS", NOW + timedelta(minutes=3))
    assert len(token) == 64 and gw_cfg.token_path.read_text() == token
    assert oct(gw_cfg.token_path.stat().st_mode & 0o777) == "0o600"
    with pytest.raises(PairRefused) as e:
        claim(gw_cfg, "ABCDEFGHJKMNPQRS", NOW)
    assert e.value.status == 404


def test_the_window_closes_after_ten_minutes(gw_cfg):
    arm(gw_cfg, "ABCD-EFGH-JKMN-PQRS", NOW)
    with pytest.raises(PairRefused) as e:
        claim(gw_cfg, "ABCD-EFGH-JKMN-PQRS", NOW + timedelta(minutes=11))
    assert e.value.status == 404


def test_five_wrong_codes_end_the_window(gw_cfg):
    arm(gw_cfg, "ABCD-EFGH-JKMN-PQRS", NOW)
    for _ in range(5):
        with pytest.raises(PairRefused) as e:
            claim(gw_cfg, "WXYZ-WXYZ-WXYZ-WXYZ", NOW)
        assert e.value.status == 403
    with pytest.raises(PairRefused) as e:
        claim(gw_cfg, "ABCD-EFGH-JKMN-PQRS", NOW)
    assert e.value.status == 404


def test_normalize():
    assert normalize(" abcd efgh-jkmn pqrs ") == "ABCDEFGHJKMNPQRS"


def test_a_short_code_is_six_characters_from_the_alphabet():
    for _ in range(50):
        c = short_code()
        assert len(c) == 7 and c[3] == "-" and all(ch in PAIR_ALPHABET for ch in c.replace("-", ""))


def test_tries_left_counts_down_to_the_end_of_the_window(gw_cfg):
    arm(gw_cfg, "K7M-4QX", NOW)
    left = []
    for _ in range(5):
        with pytest.raises(PairRefused) as e:
            claim(gw_cfg, "AAAAAA", NOW)
        left.append(e.value.tries_left)
    assert left == [4, 3, 2, 1, 0]
    with pytest.raises(PairRefused) as e:
        claim(gw_cfg, "K7M4QX", NOW)
    assert e.value.status == 404 and e.value.tries_left is None


def test_the_window_file_holds_only_the_hash(gw_cfg):
    arm(gw_cfg, "K7M-4QX", NOW)
    raw = gw_cfg.pending_pair_path.read_text()
    assert "K7M" not in raw and "4QX" not in raw and oct(gw_cfg.pending_pair_path.stat().st_mode & 0o777) == "0o600"
