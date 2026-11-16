from datetime import date, datetime, timedelta, timezone

import pytest

from steward.advisor.outgoing import RecordRefused, export, record_parts, record_payload, request_detail, requests_page
from steward_boundary.canonical import canonical, sha256_hex
from tests.factories import make_user

NOW = datetime(2026, 10, 20, 16, 14, tzinfo=timezone.utc)


def part(name, payload):
    return {"part": name, "payload": payload, "sha256": sha256_hex(payload), "bytes": len(canonical(payload))}


def test_parts_are_recorded_exactly_and_listed_one_line_per_request(db, books):
    jr = make_user(db)
    record_parts(db, user_id=jr.id, conversation_id=1, turn_id="t_000000000000000a", seq=1, channel="chat", model=None,
                 parts=[part("question", {"text": "How much went to dining?"}),
                        part("system", {"text": "Today is Tuesday, October 20, 2026."})], now=NOW)
    record_parts(db, user_id=jr.id, conversation_id=1, turn_id="t_000000000000000a", seq=2, channel="chat", model=None,
                 parts=[part("tool_result", {"tool_use_id": "toolu_1", "name": "accounts", "is_error": False,
                                             "content": {"accounts": []}})] * 3, now=NOW + timedelta(seconds=2))
    record_payload(db, user_id=jr.id, conversation_id=None, turn_id="p_000000000000000b", seq=1, channel="prewarm",
                   part="system", payload={"prefix": "steward-advisor-1", "prefix_sha256": "0" * 64, "message": "warmup"},
                   now=NOW + timedelta(seconds=5))
    db.commit()
    page = requests_page(db, books.directory, offset=0, today=date(2026, 10, 20))
    assert [(r["what"], r["channel"], r["who"], r["kind"]) for r in page["requests"]] == [
        ("Steward's instructions to Claude, no household data", "Getting ready", "JR", "prewarm"),
        ("3 results: accounts", "Chat", "JR", "results"), ("Question", "Chat", "JR", "question")]
    assert page["requests"][2]["when"] == "today at 9:14 AM" and page["requests"][2]["day"] == "Today"
    assert page["next_offset"] is None
    detail = request_detail(db, "t_000000000000000a.1")
    assert [p["part"] for p in detail["parts"]] == ["question", "system"]
    assert detail["parts"][0]["payload"] == {"text": "How much went to dining?"}
    assert request_detail(db, "t_000000000000000a.9") is None and request_detail(db, "nonsense") is None
    rows = export(db)
    assert len(rows) == 6 and rows[0]["payload"] == {"text": "How much went to dining?"}


def test_a_part_that_doesnt_match_its_hash_is_refused(db):
    bad = {**part("question", {"text": "x"}), "sha256": "0" * 64}
    with pytest.raises(RecordRefused):
        record_parts(db, user_id=1, conversation_id=1, turn_id="t_000000000000000c", seq=1, channel="chat", model=None,
                     parts=[bad], now=NOW)
    with pytest.raises(RecordRefused):
        record_parts(db, user_id=1, conversation_id=1, turn_id="t_000000000000000c", seq=1, channel="chat", model=None,
                     parts=[{**part("question", {"text": "x"}), "part": "anything"}], now=NOW)


def test_store_rows_name_who_approved_them_and_questions_count_their_replaced_parts(db, books):
    from steward.db.models import ChatConversation, ChatTurn
    jr = make_user(db)
    rows = {"rows": [{"date": "2026-10-18", "amount_cents": -1599, "category": "subscriptions", "merchant": "StreamBox",
                      "account": "Account 2"}] * 9, "payees": [], "more": False}
    conv = ChatConversation(user_id=jr.id, title="Subscriptions", created_at=NOW, updated_at=NOW, last_input_tokens=0)
    db.add(conv)
    db.flush()
    db.add(ChatTurn(conversation_id=conv.id, turn_id="t_000000000000000c", user_id=jr.id, asked="Which?", sent="Which?",
                    chips='[{"start": 0, "end": 8, "label": "Person 2", "layer": "steward"}]', started_at=NOW))
    record_parts(db, user_id=jr.id, conversation_id=conv.id, turn_id="t_000000000000000c", seq=1, channel="chat", model=None,
                 parts=[part("question", {"text": "Which?"})], now=NOW)
    record_parts(db, user_id=jr.id, conversation_id=conv.id, turn_id="t_000000000000000c", seq=2, channel="chat", model=None,
                 parts=[part("merchant_rows", {"tool_use_id": "toolu_m", "name": "merchant_detail", "is_error": False,
                                               "content": rows})], now=NOW,
                 approved={"toolu_m": (jr.id, sha256_hex(rows))})
    db.commit()
    page = requests_page(db, books.directory, offset=0, today=date(2026, 10, 20))
    assert [r["what"] for r in page["requests"]] == ["9 store rows, approved by JR", "Question, with 1 part replaced"]
    only = requests_page(db, books.directory, offset=0, today=date(2026, 10, 20), what="store_rows")
    assert [r["kind"] for r in only["requests"]] == ["store_rows"]
    assert requests_page(db, books.directory, offset=0, today=date(2026, 10, 20), who=jr.id + 99)["requests"] == []
    d = request_detail(db, "t_000000000000000c.2", names={jr.id: "JR"}, labels={"Account 2": "Rewards Card ••4402"},
                       today=date(2026, 10, 20))
    assert d["approved_by"] == "JR" and d["who"] == "JR" and d["when"] == "today at 9:14 AM"
    assert d["conversation"] == "Subscriptions"
    assert d["aliases"] == [{"alias": "Account 2", "label": "Rewards Card ••4402"}] and len(d["checks"]) == 4
    # The known-name check skipped the approved store names, so the log doesn't tick it as if it ran (Task 9).
    assert "Nothing matches a name or number this book knows" not in d["checks"]
    assert d["checks"][3].endswith("Store and payee names were skipped because a manager approved them")
    q = request_detail(db, "t_000000000000000c.1", names={jr.id: "JR"}, today=date(2026, 10, 20))
    assert q["checks"][3] == "Nothing matches a name or number this book knows"
