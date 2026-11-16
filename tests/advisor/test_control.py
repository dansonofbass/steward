"""The live turns in this process: Stop, and the answer to a store-names card (plan B rulings 7, 8). Every answer, Stop
and release here lands while the card is up: the helpers wait for wait_for_ok to start, never for a timer."""
from steward.advisor.control import Control
from tests.waiting import CEILING, Later, wait_for_card, when_waiting


def test_an_answer_wakes_the_wait_for_the_right_person_and_call_only():
    c = Control()
    c.begin("t_1", user_id=2, book_id=1)
    assert c.answer("t_1", "toolu_1", 2, 1, True) is False            # nothing is waiting yet
    results = []
    helper = when_waiting(c, "t_1", lambda: results.extend([
        c.answer("t_1", "toolu_1", 3, 1, True), c.answer("t_1", "toolu_2", 2, 1, True),
        c.answer("t_1", "toolu_1", 2, 9, True), c.answer("t_1", "toolu_1", 2, 1, True)]), call_id="toolu_1")
    assert c.wait_for_ok("t_1", "toolu_1", CEILING) == "send"
    helper.done()
    assert results == [False, False, False, True]


def test_decline_timeout_and_stop():
    c = Control()
    c.begin("t_2", 2, 1)
    helper = when_waiting(c, "t_2", lambda: c.answer("t_2", "toolu_1", 2, 1, False), call_id="toolu_1")
    assert c.wait_for_ok("t_2", "toolu_1", CEILING) == "decline"
    helper.done()
    assert c.wait_for_ok("t_2", "toolu_2", 0.05) == "timeout"         # nobody answers: the wait runs out
    helper = when_waiting(c, "t_2", lambda: c.stop("t_2", 2, 1), call_id="toolu_3")
    assert c.wait_for_ok("t_2", "toolu_3", CEILING) == "stopped" and c.is_stopped("t_2")
    helper.done()


def test_stop_needs_the_turns_own_person_and_book_and_ends_with_the_turn():
    c = Control()
    c.begin("t_3", 2, 1)
    assert c.stop("t_3", 3, 1) is False and c.stop("t_3", 2, 4) is False and not c.is_stopped("t_3")
    c.end("t_3")
    assert c.stop("t_3", 2, 1) is False and c.is_stopped("t_3") is False


def test_an_answer_counts_only_with_the_hash_of_the_card_that_was_shown():
    """Task 6.5: the approval is bound to the exact rows on the card. A forged or replayed answer without that hash,
    or with another card's, is refused and the card keeps waiting."""
    c = Control()
    c.begin("t_4", 2, 1)
    results = []

    def answer():
        results.extend([c.answer("t_4", "toolu_1", 2, 1, True), c.answer("t_4", "toolu_1", 2, 1, True, "b" * 64),
                        c.answer("t_4", "toolu_1", 2, 1, True, "a" * 64)])
    helper = when_waiting(c, "t_4", answer, call_id="toolu_1")
    assert c.wait_for_ok("t_4", "toolu_1", CEILING, digest="a" * 64) == "send"
    helper.done()
    assert results == [False, False, True]
    assert c.answer("t_4", "toolu_1", 2, 1, True, "a" * 64) is False          # a replay after the wait is refused


def test_a_browser_that_leaves_ends_a_waiting_card_at_once():
    """Task 6.5: release (the browser went away) wakes the wait with "gone", and a wait that starts after it doesn't
    block at all; a released turn reads as stopped for the reply poll."""
    c = Control()
    c.begin("t_5", 2, 1)
    helper = when_waiting(c, "t_5", lambda: c.release("t_5"), call_id="toolu_1")
    assert c.wait_for_ok("t_5", "toolu_1", CEILING) == "gone"
    helper.done()
    assert c.wait_for_ok("t_5", "toolu_2", CEILING) == "gone"
    assert c.why_stopped("t_5") == "gone" and c.is_stopped("t_5")
    c.begin("t_6", 2, 1)
    assert c.why_stopped("t_6") is None
    c.stop("t_6", 2, 1)
    assert c.why_stopped("t_6") == "stopped"
    c.release("t_unknown")                                  # nothing to release: no error


def test_a_card_going_up_wakes_whoever_watches_for_it():
    """wait_for_ok wakes the turn's condition as the card goes up, so a helper can wait for that moment instead of
    guessing it with a timer."""
    c = Control()
    c.begin("t_7", 2, 1)
    waiter = Later(lambda: c.wait_for_ok("t_7", "toolu_1", CEILING))
    waiter.start()
    wait_for_card(c, "t_7", "toolu_1")
    assert c._turns["t_7"].waiting == "toolu_1"
    c.stop("t_7", 2, 1)
    waiter.done()
