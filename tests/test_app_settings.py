import base64
import json
import logging

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.app_settings import EMAIL_KEYS, KEYS, AppSettings, SettingRefused, masked_ping, seal, secret_key, unseal
from steward.books.service import create_book
from steward.db.directory_models import AppSetting, DirectoryEvent, DirectoryMeta
from steward.db.keys import new_key
from tests.factories import login, make_person

SENTINEL = "-".join(["sentinel", "pw", "7f3a" * 3])    # built at run time, so gitleaks sees no secret-shaped literal


def test_the_registry_names_each_setting_and_its_variable():
    assert {k: (s.env, s.kind, s.group) for k, s in KEYS.items()} == {
        "email.host": ("STEWARD_SMTP_HOST", "plain", "email"), "email.port": ("STEWARD_SMTP_PORT", "plain", "email"),
        "email.user": ("STEWARD_SMTP_USER", "plain", "email"),
        "email.password": ("STEWARD_SMTP_PASSWORD", "secret", "email"),
        "email.from": ("STEWARD_MAIL_FROM", "plain", "email"),
        "backup.at": ("STEWARD_BACKUP_AT", "plain", "backups"),
        "backup.ping_url": ("STEWARD_BACKUP_PING_URL", "secret", "backups"),
        "general.timezone": ("STEWARD_TIMEZONE", "plain", "general"),
        "general.gateway_name": ("STEWARD_GATEWAY_NAME", "plain", "general")}
    assert EMAIL_KEYS == ("email.host", "email.port", "email.user", "email.password", "email.from")


def test_seal_round_trips_and_hides_the_text():
    k = secret_key(new_key())
    blob = seal(k, "email.password", SENTINEL)
    assert blob[:4] == b"SST1" and len(blob) == 4 + 12 + len(SENTINEL.encode()) + 16
    assert SENTINEL.encode() not in blob and seal(k, "email.password", SENTINEL) != blob   # a fresh nonce each time
    assert unseal(k, "email.password", blob) == SENTINEL


def test_the_aad_binds_a_sealed_value_to_its_setting():
    k = secret_key(new_key())
    assert unseal(k, "backup.ping_url", seal(k, "email.password", SENTINEL)) is None


def test_the_aad_binds_the_password_to_its_server_port_and_user():
    k = secret_key(new_key())
    blob = seal(k, "email.password", SENTINEL, bound="smtp.example.com|465|steward@example.com")
    assert unseal(k, "email.password", blob, bound="smtp.example.com|465|steward@example.com") == SENTINEL
    for other in ("smtp.other.example|465|steward@example.com", "smtp.example.com|587|steward@example.com",
                  "smtp.example.com|465|other@example.com", ""):
        assert unseal(k, "email.password", blob, bound=other) is None, other


def test_a_wrong_key_or_a_damaged_blob_unseals_to_none():
    blob = seal(secret_key(new_key()), "email.password", SENTINEL)
    assert unseal(secret_key(new_key()), "email.password", blob) is None
    assert unseal(secret_key(new_key()), "email.password", b"SST0" + blob[4:]) is None
    assert unseal(secret_key(new_key()), "email.password", b"") is None


EMAIL = {"host": "smtp.example.com", "port": 465, "user": "steward@example.com", "password": SENTINEL,
         "from": "Steward <steward@example.com>"}
BY = {"by_id": None, "by_name": "Pat"}      # updated_by is a foreign key to user.id (foreign_keys is ON); None is allowed


def store_for(books, **env) -> AppSettings:
    """env fields as if .env set them: model_copy(update=) marks each one set, as pydantic-settings does for a line.
    The settings fixture sets STEWARD_TIMEZONE; unless a test passes timezone, it isn't counted as set here."""
    s = books.settings.model_copy(update=env)
    if "timezone" not in env:
        s.__pydantic_fields_set__.discard("timezone")      # model_copy gave the copy its own set
    return AppSettings(s, books.directory, books.master)


@pytest.mark.parametrize("key,field,saved,body,group,default", [
    ("email.host", "smtp_host", "smtp.example.com", EMAIL, "email", ""),
    ("backup.at", "backup_at", "04:30", {"at": "04:30"}, "backups", "03:00"),
    ("general.timezone", "timezone", "America/Chicago", {"timezone": "America/Chicago"}, "general", ""),
    ("general.gateway_name", "gateway_name", "Den PC", {"gateway_name": "Den PC"}, "general", "the gateway"),
])
def test_env_then_app_then_default(books, key, field, saved, body, group, default):
    st = store_for(books)
    assert (st.effective()[key].value, st.effective()[key].source) == (default, "default")
    st.save(group, body, **BY)
    assert (st.effective()[key].value, st.effective()[key].source) == (saved, "app")
    env_value = "smtp.env.example" if key == "email.host" else {"backup_at": "05:00", "timezone": "UTC",
                                                                 "gateway_name": "Attic"}[field]
    owned = store_for(books, **{field: env_value}).effective()[key]
    assert (owned.value, owned.source) == (env_value, "env")


def test_an_empty_env_value_counts_as_set_so_backups_stay_off(books, monkeypatch, tmp_path):
    monkeypatch.setenv("STEWARD_BACKUP_AT", "")
    from steward.settings import Settings
    s = Settings(_env_file=None)
    assert "backup_at" in s.model_fields_set
    st = AppSettings(s, books.directory, books.master)
    assert (st.value("backup.at"), st.effective()["backup.at"].source) == ("", "env")
    with pytest.raises(SettingRefused) as e:
        st.save("backups", {"at": "03:00"}, **BY)
    assert (e.value.status, e.value.message) == (409, "This is set in your settings file (STEWARD_BACKUP_AT).")


def test_a_dotenv_line_counts_as_set(books, tmp_path, monkeypatch):
    monkeypatch.delenv("STEWARD_SMTP_HOST", raising=False)
    env = tmp_path / "x.env"
    env.write_text("STEWARD_SMTP_HOST=smtp.example.com\n")
    from steward.settings import Settings
    assert "smtp_host" in Settings(_env_file=env).model_fields_set


def test_the_email_group_comes_from_one_place(books):
    st = store_for(books)
    st.save("email", EMAIL, **BY)
    only_port = store_for(books, smtp_port=587)        # one env line takes the whole group
    eff = only_port.effective()
    assert {eff[k].source for k in EMAIL_KEYS} == {"env"} and eff["email.host"].value == ""
    assert only_port.email() is None and only_port.email_source() == "env"
    with pytest.raises(SettingRefused) as e:
        only_port.save("email", EMAIL, **BY)
    assert (e.value.status, e.value.message) == (409, "This is set in your settings file (STEWARD_SMTP_*).")


PORT_WORDS = "Use port 465 or 587. It's usually 465."


@pytest.mark.parametrize("group,body,words", [
    ("email", {**EMAIL, "host": "smtp://smtp.example.com"}, "Enter the server's name, like smtp.example.com."),
    ("email", {**EMAIL, "host": "smtp.example.com:465"}, "Enter the server's name, like smtp.example.com."),
    ("email", {**EMAIL, "host": "smtp.example.com\r\nX"}, "Enter the server's name, like smtp.example.com."),
    ("email", {**EMAIL, "port": 0}, PORT_WORDS),
    ("email", {**EMAIL, "port": "465"}, PORT_WORDS),
    ("email", {**EMAIL, "port": 22}, PORT_WORDS),         # only mail ports: the test email is no port scanner
    ("email", {**EMAIL, "port": 443}, PORT_WORDS),
    ("email", {**EMAIL, "port": 2525}, PORT_WORDS),
    ("email", {**EMAIL, "port": 25}, PORT_WORDS),         # Steward speaks TLS only: 465 implicit, 587 STARTTLS
    ("email", {**EMAIL, "user": ""}, "Enter the user name the server gave you."),
    ("email", {**EMAIL, "user": "a\nb"}, "Enter the user name the server gave you."),
    ("email", {**EMAIL, "password": "x" * 501}, "Enter the password."),
    ("email", {**EMAIL, "from": "a@b.com\r\nBcc: c@d.com"}, "Enter the address emails come from."),
    ("email", {**EMAIL, "from": "a@b.com, c@d.com"}, "Enter the address emails come from."),
    ("backups", {"at": "25:00"}, "Enter a time like 03:00."),
    ("backups", {"ping_url": "ftp://hc.example/x"}, "Enter the ping URL from your checks service."),
    ("backups", {"ping_url": "https://u:p@hc.example/x"}, "Enter the ping URL from your checks service."),
    ("general", {"gateway_name": "{x}"}, "STEWARD_GATEWAY_NAME must be up to 40 characters, with no braces or control characters."),
    ("general", {"timezone": "Mars/Base"}, "STEWARD_TIMEZONE must be a time zone name like America/Chicago or UTC; Mars/Base isn't one."),
    ("general", {"colour": "x"}, "Unknown field: colour."),
])
def test_each_rule_refuses_with_its_words(books, group, body, words):
    st = store_for(books)
    with pytest.raises(SettingRefused) as e:
        st.save(group, body, **BY)
    assert (e.value.status, e.value.message) == (422, words)
    with Session(books.directory) as s:
        assert s.scalars(select(AppSetting)).all() == []      # nothing half-saved


@pytest.mark.parametrize("port", [465, 587])
def test_each_mail_port_is_taken(books, port):
    st = store_for(books)
    st.save("email", {**EMAIL, "port": port}, **BY)
    assert st.email().port == port


def test_a_first_save_needs_the_password_and_a_later_one_keeps_it(books):
    st = store_for(books)
    no_pw = {k: v for k, v in EMAIL.items() if k != "password"}
    with pytest.raises(SettingRefused, match="Enter the password."):
        st.save("email", no_pw, **BY)
    st.save("email", EMAIL, **BY)
    st.save("email", {**no_pw, "from": "Home <home@example.com>"}, **BY)     # the same server, port and user
    assert st.email().password == SENTINEL and st.email().mail_from == "Home <home@example.com>"
    assert SENTINEL not in repr(st.email())


@pytest.mark.parametrize("field,value", [("host", "smtp.other.example"), ("port", 587), ("user", "other@example.com")])
def test_a_new_server_port_or_user_without_a_password_clears_the_saved_one(books, field, value):
    """A saved password is only ever sent to the server, port and user it was saved for (Nov 8 review): changing any of
    them without typing it again deletes it, and nothing sends until it is entered again."""
    st = store_for(books)
    no_pw = {k: v for k, v in EMAIL.items() if k != "password"}
    st.save("email", EMAIL, **BY)
    st.save("email", {**no_pw, field: value}, **BY)
    assert st.email() is None and st.secret("email.password") is None
    pw = st.effective()["email.password"]
    assert (pw.set, pw.unreadable) == (False, False)
    assert st.value(f"email.{field}") == str(value)                  # the rest of the save stands
    with Session(books.directory) as s:
        assert s.get(AppSetting, "email.password") is None
    with pytest.raises(SettingRefused, match="Enter the password."):  # the next save without it asks for it
        st.save("email", {**no_pw, field: value}, **BY)
    st.save("email", {**EMAIL, field: value}, **BY)
    assert st.email().password == SENTINEL


@pytest.mark.parametrize("key,raced", [("email.host", "smtp.other.example"), ("email.port", "587"),
                                       ("email.user", "other@example.com")])
def test_a_password_saved_for_one_server_never_opens_for_another(books, key, raced, caplog):
    """Nov 9 re-review: _moves_the_password reads cached rows outside the write session, so two saves at once can leave
    a new server, port or user beside the old password. The sealed password names the server, port and user it was
    saved for, so it opens only for them; otherwise it reads as not set and is asked for again."""
    caplog.set_level(logging.DEBUG)
    st = store_for(books)
    st.save("email", EMAIL, **BY)
    assert st.secret("email.password") == SENTINEL
    with Session(books.directory) as s:          # the race: the row changes, the password row stays as it was
        old = s.get(AppSetting, key).value
        s.get(AppSetting, key).value = raced
        s.commit()
    st.reload()
    pw = st.effective()["email.password"]
    assert st.secret("email.password") is None and st.email() is None
    assert (pw.set, pw.unreadable) == (False, True)
    no_pw = {k: v for k, v in EMAIL.items() if k != "password"}
    with pytest.raises(SettingRefused, match="Enter the password."):  # a save without it asks for it
        st.save("email", {**no_pw, key.split(".")[1]: int(raced) if key == "email.port" else raced}, **BY)
    with Session(books.directory) as s:          # the server, port and user it was saved for: it opens again
        s.get(AppSetting, key).value = old
        s.commit()
    st.reload()
    assert st.email().password == SENTINEL
    assert SENTINEL not in caplog.text


def test_env_email_wins_and_never_reads_the_app_password(books):
    """JR's NAS sends with the .env group only: the app's sealed password and what it was saved for change nothing."""
    env_pw = "-".join(["env", "pw", "5c1d" * 3])
    store_for(books).save("email", EMAIL, **BY)
    env = store_for(books, smtp_host="mail.env.example", smtp_port=465, smtp_user="env-user", smtp_password=env_pw,
                    mail_from="Env <env@example.com>")
    cfg = env.email()
    assert (cfg.host, cfg.port, cfg.user, cfg.password) == ("mail.env.example", 465, "env-user", env_pw)
    assert env.secret("email.password") == env_pw and env.effective()["email.password"].set is True


def test_a_wrong_master_key_reads_as_not_set(books):
    st = store_for(books)
    st.save("email", EMAIL, **BY)
    st.save("backups", {"ping_url": "https://hc-ping.example/abcd1234"}, **BY)
    other = AppSettings(st.settings, books.directory, new_key())
    pw = other.effective()["email.password"]
    assert (pw.set, pw.unreadable, pw.value) == (False, True, None)
    assert other.email() is None and other.secret("backup.ping_url") is None


def test_clearing_deletes_the_rows_and_bumps_the_email_version(books):
    st = store_for(books)
    assert st.email_version() == 0
    st.save("email", EMAIL, **BY)
    assert st.email_version() == 1
    st.clear_email(**BY)
    assert st.email_version() == 2 and st.email() is None
    with Session(books.directory) as s:
        assert s.scalars(select(AppSetting.key)).all() == []
    st.save("backups", {"ping_url": "https://hc-ping.example/abcd1234"}, **BY)
    st.save("backups", {"ping_url": None}, **BY)
    assert st.secret("backup.ping_url") is None
    st.save("backups", {"at": None}, **BY)          # Off is a choice: a row holding ""
    assert st.value("backup.at") == ""


def test_saves_log_one_event_each_with_no_values(books, caplog):
    caplog.set_level(logging.DEBUG)
    st = store_for(books)
    st.save("email", EMAIL, **BY)
    st.clear_email(**BY)
    st.save("general", {"gateway_name": "Den PC"}, **BY)
    with Session(books.directory) as s:
        assert [e.message for e in s.scalars(select(DirectoryEvent).where(DirectoryEvent.kind == "settings"))] == [
            "Email settings changed by Pat.", "Email settings removed by Pat.", "Steward's settings changed by Pat."]
    assert SENTINEL not in caplog.text


def test_the_mail_record_carries_the_config_version_and_no_address(books):
    st = store_for(books)
    st.save("email", EMAIL, **BY)
    st.record_mail(False, "auth")
    last = st.last_mail()
    assert set(last) == {"at", "ok", "why", "config"} and (last["ok"], last["why"], last["config"]) == (False, "auth", 1)
    with Session(books.directory) as s:
        assert "example.com" not in s.get(DirectoryMeta, "mail.last").value


def test_a_directory_before_d0007_reads_as_defaults(settings):
    from steward.db.engine import make_engine
    from steward.db.keys import directory_key, ensure_key
    master = ensure_key(settings.key_path)
    eng = make_engine(settings.directory_path, directory_key(master))    # no migrations: no app_setting table
    try:
        st = AppSettings(settings, eng, master)
        assert st.value("backup.at") == "03:00" and st.email() is None and st.last_mail() is None
    finally:
        eng.dispose()


def test_the_ping_url_shows_as_host_and_last_four():
    assert masked_ping("https://hc-ping.com/0a1b2c3d-9f2c") == "hc-ping.com/…9f2c"


@pytest.fixture
def people(client, ddb, books, ours):
    mom = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret"])
    make_person(ddb, "pat", [(ours.id, "manager")])
    make_person(ddb, "vee", [(ours.id, "viewer")])
    make_person(ddb, "momsmgr", [(mom.id, "manager")])
    return client


ROUTES = [("GET", "/api/install/settings", None), ("PUT", "/api/install/settings/email", EMAIL),
          ("DELETE", "/api/install/settings/email", None), ("PUT", "/api/install/settings/backups", {"at": "04:00"}),
          ("PUT", "/api/install/settings/general", {"gateway_name": "Den PC"})]


def test_only_an_install_manager_reaches_the_settings(people):
    for method, path, body in ROUTES:
        people.cookies.clear()
        assert people.request(method, path, json=body).status_code == 401, path
        for who in ("vee", "momsmgr"):                  # a viewer, and a manager of a parent book only
            login(people, who)
            r = people.request(method, path, json=body)
            assert (r.status_code, r.json()) == (404, {"error": "Only a manager of the household can see this."}), (who, path)
        login(people, "pat")
        assert people.request(method, path, json=body).status_code == 200, path


def test_a_manager_of_a_later_household_book_is_not_an_install_manager(people, books, ddb, ours, caplog):
    """An older install might hold two household books (no new one can be made). The lowest id is THE household: a
    manager of the other one gets 404 on every settings route, a warning says why, and the household's own managers
    (as on JR's install, "ours") keep their access."""
    from steward.books.owners import HOUSEHOLD_OWNER_NAMES, to_json
    from steward.db.directory_models import Book
    later = create_book(books, ddb, name="Later", kind="parent", owner_labels=["Lee"])
    row = ddb.get(Book, later.id)
    row.kind, row.owner_names = "household", to_json(HOUSEHOLD_OWNER_NAMES)    # as an older install might hold it
    ddb.commit()
    assert later.id > ours.id
    make_person(ddb, "laterboss", [(later.id, "manager")])
    caplog.set_level(logging.WARNING, logger="steward.books")
    for method, path, body in ROUTES:
        login(people, "laterboss")
        r = people.request(method, path, json=body)
        assert (r.status_code, r.json()) == (404, {"error": "Only a manager of the household can see this."}), path
        login(people, "pat")
        assert people.request(method, path, json=body).status_code == 200, path
    assert f"More than one household book; book {ours.id} counts as the household." in caplog.text


def test_no_answer_or_log_ever_holds_the_email_password(people, books, caplog):
    caplog.set_level(logging.DEBUG)
    login(people, "pat")
    answers = [people.put("/api/install/settings/email", json=EMAIL), people.get("/api/install/settings")]
    with Session(books.directory) as s:
        sealed = s.get(AppSetting, "email.password").sealed
    answers.append(people.put("/api/install/settings/email", json={**EMAIL, "password": None} | {"user": "u2@example.com"}))
    answers.append(people.delete("/api/install/settings/email"))
    assert answers[1].json()["email"]["password_set"] is True
    for r in answers:
        assert SENTINEL not in r.text and base64.b64encode(sealed).decode() not in r.text and sealed.hex() not in r.text
    assert SENTINEL not in caplog.text


def test_the_ping_url_is_never_answered_only_its_host_and_last_four(people, caplog):
    login(people, "pat")
    url = "https://hc-ping.example/" + "-".join(["0a1b2c3d", "9f2c"])
    r = people.put("/api/install/settings/backups", json={"ping_url": url})
    assert r.json()["backups"]["ping_url"] == {"set": True, "shown": "hc-ping.example/…9f2c", "source": "app",
                                               "env": "STEWARD_BACKUP_PING_URL"}
    assert "0a1b2c3d" not in r.text and "0a1b2c3d" not in caplog.text


def test_a_save_env_owns_answers_409_and_shows_the_running_value(people, books, app):
    app.state.app_settings = AppSettings(books.settings.model_copy(update={"gateway_name": "Attic"}),
                                         books.directory, books.master)
    login(people, "pat")
    r = people.put("/api/install/settings/general", json={"gateway_name": "Den PC"})
    assert (r.status_code, r.json()) == (409, {"error": "This is set in your settings file (STEWARD_GATEWAY_NAME)."})
    g = people.get("/api/install/settings").json()["general"]["gateway_name"]
    assert g == {"value": "Attic", "source": "env", "env": "STEWARD_GATEWAY_NAME"}


def test_refused_values_answer_422_with_the_words(people):
    login(people, "pat")
    for port in (70000, 22, 25):
        r = people.put("/api/install/settings/email", json={**EMAIL, "port": port})
        assert (r.status_code, r.json()) == (422, {"error": PORT_WORDS}), port
