"""T3 (spec 2026-11-05, section 3; plan D13): every delete of something you've saved has an Undo or a clear confirm.
DELETES lists every DELETE route in the app with how a person gets back from it, so a DELETE route added later fails
here until someone says which it has and names the test that proves it.

- `undo`: a pytest test that deletes through the API and then undoes it.
- `confirm`: a vitest or e2e test titled for the screen that calls the route, showing that nothing is sent until the
  confirm (a ConfirmSheet, or an inline Remove/Keep row) is pressed, and that it is sent after.
- `unsaved: <reason>`: the route drops something not yet saved, such as a staged upload before import. Its proof is
  the handler.

CALLERS lists every place in web/src that sends a DELETE, so a second screen (or a second button on the same screen)
that calls a listed route fails here until it is named with a web test of its own."""
import re
from pathlib import Path

from tests.test_claims import proof_problem
from tests.test_isolation_sweep import api_routes

ROOT = Path(__file__).resolve().parents[1]
B = "/api/b/{slug}"
WEB_TESTS = (".test.ts", ".test.tsx", ".spec.ts")

DELETES: dict[str, tuple[str, str]] = {
    # Signing in
    "DELETE /api/auth/sessions/{sid}": (
        "confirm", "web/src/screens/you/SignInDevices.test.tsx::signing out another device asks first and says the other devices stay"),
    "DELETE /api/auth/passkeys/{pid}": (
        "confirm", "web/src/screens/you/SignInDevices.test.tsx::removing a passkey asks first and says the password still works"),
    "DELETE /api/install/settings/email": (
        "confirm", "web/src/screens/ready/panels.test.tsx::removes app-stored email only after the sheet confirms"),
    # Books and members
    "DELETE /api/books/sample": (
        "undo", "tests/test_sample_book.py::test_remove_archives_it_and_undo_brings_it_back_within_15_minutes"),
    "DELETE /api/books/{slug}/invites/{invite_id}": (
        "confirm", "web/src/screens/settings/Members.test.tsx::a manager sees pending invites as Invited rows and can cancel one"),
    "DELETE /api/books/{slug}/members/{user_id}": (
        "confirm", "web/src/screens/settings/Members.test.tsx::removing someone asks first and says what they lose and what stays"),
    # Import
    f"DELETE {B}/import/files/{{token}}": (
        "unsaved: a staged file isn't in the books until it is imported", "src/steward/api/imports.py::drop_file"),
    f"DELETE {B}/import/layouts/{{lid}}": (
        "undo", "tests/test_import_layouts_api.py::test_forget_hides_the_layout_and_undo_brings_it_back_once"),
    f"DELETE {B}/import/statements/{{sid}}": (
        "undo", "tests/test_statement_review_api.py::test_remove_restore_and_final"),
    f"DELETE {B}/import/statement-layouts/{{lid}}": (
        "undo", "tests/test_statement_review_api.py::test_forget_and_undo_and_the_layout_list"),
    # Transactions
    f"DELETE {B}/transactions/{{tid}}": (
        "confirm", "web/src/screens/review/Duplicates.test.tsx::removing the file copy asks first and says the bank copy stays"),
    f"DELETE {B}/transactions/{{tid}}/notes/{{note_id}}": (
        "undo", "tests/test_notes_undo.py::test_remove_answers_a_token_and_undo_brings_the_same_note_back_in_its_place"),
    f"DELETE {B}/categorize/rules/{{rule_id}}": (
        "confirm", "web/src/screens/settings/CategoryRules.test.tsx::removing a rule asks first and says past transactions stay as they are"),
    f"DELETE {B}/simplefin": (
        "confirm", "web/src/screens/settings/Banks.test.tsx::unlinking asks first and says the accounts and transactions stay"),
    # Household
    f"DELETE {B}/children/{{cid}}": (
        "undo", "tests/test_undo_profile.py::test_a_removed_kid_comes_back_with_its_529_and_its_name_never_enters_the_journal"),
    f"DELETE {B}/spending/targets/{{category}}/kept": (
        "undo", "tests/test_spending_over.py::test_keep_waits_three_months_and_check_again_asks_again"),
    f"DELETE {B}/setasides/{{sa_id}}": (
        "confirm", "web/src/screens/spending/setasides/SetAside.test.tsx::Not this one undoes a match, and Stop archives after a confirmation"),
    f"DELETE {B}/setasides/match/{{transaction_id}}": (
        "undo", "tests/test_setasides_api.py::test_not_this_one_is_undone_by_matching_the_payment_again"),
    f"DELETE {B}/business/rules/{{rule_id}}": (
        "confirm", "web/src/screens/business/BusinessSettings.test.tsx::removing a rule asks first and says tagged transactions keep their tags"),
    f"DELETE {B}/chat/conversations/{{cid}}": (
        "confirm", "web/src/screens/chat/History.test.tsx::deleting asks first, says the log keeps what was sent, and takes the row off the list"),
    # A parent's book
    f"DELETE {B}/inventory/files/{{file_id}}": (
        "confirm", "web/src/screens/inventory/ItemPage.test.tsx::removing a file asks first and sends nothing until Remove"),
    f"DELETE {B}/care/scenarios/{{scenario_id}}": (
        "confirm", "web/src/screens/care/Care.test.tsx::asks before removing a scenario"),
    f"DELETE {B}/care/quotes/{{key}}": (
        "confirm", "web/src/screens/care/Care.test.tsx::asks before dropping a quote for the typical figure, and Keep keeps it"),
}


W = "web/src/screens"

# Every place the web app sends a DELETE (see delete_senders), with how many call sites are there, and for each route
# those reach, a web test of that caller: for a `confirm` route, one that shows nothing is sent until the confirm.
# A second caller of a listed route, or a second call in the same place, fails until it is named here with its proof.
CALLERS: dict[str, tuple[int, tuple[tuple[str, str], ...]]] = {
    "web/src/book/sample/Sample.tsx::direct": (1, (
        ("DELETE /api/books/sample", "web/src/book/sample/Sample.test.tsx::names the Sample, opens the household book, and removes the Sample"),)),
    f"{W}/you/SignInDevices.tsx::direct": (2, (
        ("DELETE /api/auth/passkeys/{pid}", DELETES["DELETE /api/auth/passkeys/{pid}"][1]),
        ("DELETE /api/auth/sessions/{sid}", DELETES["DELETE /api/auth/sessions/{sid}"][1]))),
    f"{W}/ready/EmailPanel.tsx::removeEmail": (1, (
        ("DELETE /api/install/settings/email", DELETES["DELETE /api/install/settings/email"][1]),)),
    f"{W}/settings/Members.tsx::direct": (2, (
        ("DELETE /api/books/{slug}/members/{user_id}", DELETES["DELETE /api/books/{slug}/members/{user_id}"][1]),
        ("DELETE /api/books/{slug}/invites/{invite_id}", DELETES["DELETE /api/books/{slug}/invites/{invite_id}"][1]))),
    f"{W}/import/Import.tsx::dropFile": (1, (
        (f"DELETE {B}/import/files/{{token}}",
         f"{W}/import/Import.test.tsx::remove collapses the row, says so with Undo, and lets the staging go when the toast does"),)),
    f"{W}/import/Import.tsx::removeStatement": (1, (
        (f"DELETE {B}/import/statements/{{sid}}", f"{W}/import/Import.test.tsx::a removed line collapses with Undo and goes for good when the toast does"),)),
    f"{W}/import/Import.tsx::finalRemove": (1, (
        (f"DELETE {B}/import/statements/{{sid}}", f"{W}/import/Import.test.tsx::the toast running out removes the statement for good"),)),
    f"{W}/import/Layouts.tsx::direct": (1, (
        (f"DELETE {B}/import/layouts/{{lid}}", f"{W}/import/Layouts.test.tsx::Forget collapses the row and says so with Undo, through the journal"),
        (f"DELETE {B}/import/statement-layouts/{{lid}}",
         f"{W}/import/Layouts.test.tsx::a statement layout reads as one, has Forget only, and Forget takes the statement route with Undo"))),
    f"{W}/review/Duplicates.tsx::direct": (1, (
        (f"DELETE {B}/transactions/{{tid}}", DELETES[f"DELETE {B}/transactions/{{tid}}"][1]),)),
    f"{W}/transactions/NotesList.tsx::direct": (1, (
        (f"DELETE {B}/transactions/{{tid}}/notes/{{note_id}}",
         f"{W}/transactions/Notes.test.tsx::Remove hides the line at once and says Removed · Undo; Undo brings it back in its place"),)),
    f"{W}/settings/CategoryRules.tsx::direct": (1, (
        (f"DELETE {B}/categorize/rules/{{rule_id}}", DELETES[f"DELETE {B}/categorize/rules/{{rule_id}}"][1]),)),
    f"{W}/settings/Banks.tsx::direct": (1, (
        (f"DELETE {B}/simplefin", DELETES[f"DELETE {B}/simplefin"][1]),)),
    f"{W}/profile/kids/KidsList.tsx::removeChild": (1, (
        (f"DELETE {B}/children/{{cid}}", f"{W}/profile/kids/Kids.test.tsx::Remove folds the row away with \"Removed Ava · Undo\", and Undo posts the token"),)),
    f"{W}/spending/KeptTargets.tsx::checkAgain": (1, (
        (f"DELETE {B}/spending/targets/{{category}}/kept",
         f"{W}/spending/Targets.test.tsx::Kept targets lists each kept target, and Check again asks again, with Undo"),)),
    # Both Stop and "No, archive it" open the one Stop sheet, whose confirm is the only call.
    f"{W}/spending/setasides/SetAside.tsx::stopSetAside": (1, (
        (f"DELETE {B}/setasides/{{sa_id}}", DELETES[f"DELETE {B}/setasides/{{sa_id}}"][1]),
        (f"DELETE {B}/setasides/{{sa_id}}",
         f"{W}/spending/setasides/SetAside.test.tsx::No, archive it asks first, then stops the paid one-off; with no offer there is nothing to Start"))),
    f"{W}/spending/setasides/SetAside.tsx::unmatchPayment": (1, (
        (f"DELETE {B}/setasides/match/{{transaction_id}}",
         f"{W}/spending/setasides/SetAside.test.tsx::Not this one undoes a match, and Stop archives after a confirmation"),)),
    f"{W}/spending/Spending.tsx::unmatchPayment": (1, (
        (f"DELETE {B}/setasides/match/{{transaction_id}}",
         f"{W}/spending/Spending.test.tsx::a month with a matched payment names it under the figure and lists it with an undo"),)),
    f"{W}/transactions/PaidFrom.tsx::unmatchPayment": (1, (
        (f"DELETE {B}/setasides/match/{{transaction_id}}",
         f"{W}/transactions/PaidFrom.test.tsx::a matched payment says so and offers Not this one, refreshing through invalidateSetAsides"),)),
    f"{W}/business/BusinessSettings.tsx::direct": (1, (
        (f"DELETE {B}/business/rules/{{rule_id}}", DELETES[f"DELETE {B}/business/rules/{{rule_id}}"][1]),)),
    f"{W}/chat/History.tsx::deleteConversation": (1, (
        (f"DELETE {B}/chat/conversations/{{cid}}", DELETES[f"DELETE {B}/chat/conversations/{{cid}}"][1]),)),
    f"{W}/inventory/ItemPage.tsx::removeFile": (1, (
        (f"DELETE {B}/inventory/files/{{file_id}}", DELETES[f"DELETE {B}/inventory/files/{{file_id}}"][1]),)),
    f"{W}/care/Care.tsx::removeScenario": (1, (
        (f"DELETE {B}/care/scenarios/{{scenario_id}}", DELETES[f"DELETE {B}/care/scenarios/{{scenario_id}}"][1]),)),
    f"{W}/care/QuoteSheet.tsx::removeQuote": (1, (
        (f"DELETE {B}/care/quotes/{{key}}", DELETES[f"DELETE {B}/care/quotes/{{key}}"][1]),)),
}

SEND = re.compile(r"\bdel\(\)|method:\s*['\"]DELETE['\"]")
HELPER = re.compile(r"^export const (\w+)\s*=", re.M)
IMPORTS = re.compile(r"^(import\b[^;]*;|export\s*\{[^}]*\}[^;\n]*;?)", re.M)


def web_sources(root: Path) -> dict[str, str]:
    """Each .ts/.tsx under web/src that isn't a test, by its path from root."""
    return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in sorted((root / "web/src").rglob("*"))
            if p.suffix in (".ts", ".tsx") and not re.search(r"\.test\.tsx?$", p.name)}


def delete_senders(sources: dict[str, str]) -> dict[str, int]:
    """Every place a web source sends a DELETE, as "path::how" with how many times: `direct` for a fetch written in
    place (del() or method: 'DELETE'), else the helper it calls (an `export const` whose line sends one). A helper's
    own file counts only if it uses the helper too. Imports don't count; a reference without a call does."""
    found: dict[str, int] = {}
    helpers: set[str] = set()
    for path, text in sources.items():
        prev = ""
        for line in text.splitlines():
            n, before = len(SEND.findall(line)), prev
            prev = line
            if not n or line.startswith("export const del ="):
                continue
            # A helper's arrow body may start on the line after its name.
            if (m := HELPER.match(line)) or ((m := HELPER.match(before)) and before.rstrip().endswith("=>")):
                helpers.add(m.group(1))
            else:
                found[f"{path}::direct"] = found.get(f"{path}::direct", 0) + n
    for name in sorted(helpers):
        use, own = re.compile(rf"\b{name}\b"), re.compile(rf"^export const {name}\b", re.M)
        for path, text in sources.items():
            body = IMPORTS.sub("", text)
            if n := len(use.findall(body)) - len(own.findall(body)):
                found[f"{path}::{name}"] = n
    return found


def delete_routes(app) -> set[str]:
    return {f"{method} {path}" for path, method, _, _ in api_routes(app) if method == "DELETE"}


def kind_problem(route: str, kind: str, proof: str) -> str | None:
    """What's wrong with a row's kind and proof, or None. An undo is proven by a pytest test, a confirm by a web test's
    title; neither may stand on a bare file."""
    path, _, name = proof.partition("::")
    if kind == "undo" and not (path.startswith("tests/") and path.endswith(".py") and name.startswith("test_")):
        return f"{route}: an undo is proven by a pytest test (tests/...py::test_...), not {proof!r}"
    if kind == "confirm" and not (path.startswith("web/") and path.endswith(WEB_TESTS) and name):
        return f"{route}: a confirm is proven by a web test's title (web/...test.tsx::title), not {proof!r}"
    if kind.startswith("unsaved: "):
        return None if kind.removeprefix("unsaved: ").strip() and name else f"{route}: unsaved needs a reason and its handler"
    if kind not in ("undo", "confirm"):
        return f"{route}: kind {kind!r} isn't undo, confirm or 'unsaved: <reason>'"
    return None


def test_every_delete_route_is_listed(app):
    live = delete_routes(app)
    assert len(live) >= 21
    assert sorted(live - set(DELETES)) == [], "DELETE routes with no row in DELETES"
    assert sorted(set(DELETES) - live) == [], "rows in DELETES for routes the app no longer has"


def test_the_inventory_notices_a_new_delete_route(app):
    from fastapi import APIRouter, Depends
    from steward.deps import open_book
    rogue = APIRouter(dependencies=[Depends(open_book)])

    @rogue.delete("/rogue/{rid}")
    def _rogue(rid: int):
        return {}
    app.include_router(rogue, prefix=B)
    assert sorted(delete_routes(app) - set(DELETES)) == [f"DELETE {B}/rogue/{{rid}}"]


def test_each_delete_has_an_undo_or_a_confirm_with_a_proof():
    found = [p for route, (kind, proof) in DELETES.items() if (p := kind_problem(route, kind, proof))]
    found += [f"{route}: {p}" for route, (_, proof) in DELETES.items() if (p := proof_problem(ROOT, proof))]
    assert found == []


def test_the_kind_check_refuses_a_row_without_its_proof():
    assert kind_problem("DELETE /x", "undo", "web/src/X.test.tsx::undoes it")
    assert kind_problem("DELETE /x", "confirm", "tests/test_x.py::test_x")
    assert kind_problem("DELETE /x", "confirm", "web/src/X.tsx")
    assert kind_problem("DELETE /x", "unsaved: ", "src/steward/api/x.py::drop")
    assert kind_problem("DELETE /x", "gone", "tests/test_x.py::test_x")
    assert kind_problem("DELETE /x", "undo", "tests/test_x.py::test_x") is None
    assert proof_problem(ROOT, "web/src/screens/chat/History.test.tsx::no test has this title")


def test_every_web_caller_of_a_delete_is_listed_with_its_own_proof():
    found = delete_senders(web_sources(ROOT))
    assert len(found) >= 23
    assert {k: n for k, n in found.items() if CALLERS.get(k, (None,))[0] != n} == {}, \
        "a DELETE sent from a place CALLERS doesn't list, or more times than it says: name each with its proof"
    assert sorted(set(CALLERS) - set(found)) == [], "rows in CALLERS for places that no longer send a DELETE"
    problems = [f"{k}: {route} isn't in DELETES" for k, (_, rows) in CALLERS.items() for route, _ in rows if route not in DELETES]
    problems += [f"{k}: {route}: a caller is proven by a web test's title, not {proof!r}"
                 for k, (_, rows) in CALLERS.items() for route, proof in rows if kind_problem(route, "confirm", proof)]
    problems += [f"{k}: {p}" for k, (_, rows) in CALLERS.items() for _, proof in rows if (p := proof_problem(ROOT, proof))]
    assert problems == []
    reached = {route for _, rows in CALLERS.values() for route, _ in rows}
    assert sorted(set(DELETES) - reached) == [], "DELETE routes no web caller reaches"


def test_the_caller_scan_notices_a_second_caller():
    sources = {
        "web/src/api/client.ts": "export const del = (): RequestInit => ({ method: 'DELETE' });\n",
        "web/src/api/things.ts": "export const dropThing = (id: number) =>\n  api<void>(`/api/things/${id}`, del());\n",
        "web/src/screens/Thing.tsx": "import { dropThing } from '../api/things';\nconst go = () => dropThing(1);\n",
        "web/src/screens/Quick.tsx": "import {\n  dropThing,\n} from '../api/things';\nconst a = () => dropThing(2);\nconst b = dropThing;\n",
        "web/src/screens/Inline.tsx": "await api('/api/other', { method: 'DELETE' });\n",
        "web/src/screens/Calm.tsx": "import { dropThing } from '../api/things';\n",
    }
    assert delete_senders(sources) == {"web/src/screens/Thing.tsx::dropThing": 1, "web/src/screens/Quick.tsx::dropThing": 2,
                                       "web/src/screens/Inline.tsx::direct": 1}
