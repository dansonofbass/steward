from steward import clock, gateway_name
import os
from pathlib import Path

import typer
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from steward.app_settings import AppSettings, apply_effective, zone_needed
from steward.auth import reset, users
from steward.books.registry import BookRegistry, DirectoryUnavailable
from steward.books.service import BookRefused, add_membership, create_book
from steward.db.engine import WrongKey, check_key
from steward.db.keys import KeyMissing, ensure_key, ensure_key_file, new_key
from steward.services import restore_check
from steward.settings import Settings

app = typer.Typer(no_args_is_help=True, help="Steward household finance vault")


OWN_SETTINGS = {"env", "allowed_hosts", "gateway_name", "timezone", "backup_at", "backup_ping_url"}     # settings whose refusal is one plain line, not a traceback (spec 2026-11-05, s. 7)


def _settings() -> Settings:
    """Settings, with the gateway's name and the time zone in effect for this command."""
    try:
        s = Settings()
    except ValidationError as e:
        mine = [x for x in e.errors() if x["loc"] and x["loc"][0] in OWN_SETTINGS]
        if not mine:
            raise
        typer.echo(mine[0]["msg"].removeprefix("Value error, "))
        raise typer.Exit(1)
    gateway_name.configure(s.gateway_name)
    clock.configure(s.timezone)
    return s


def _books(s: Settings, require_db: bool = True, prepare: bool = True) -> BookRegistry:
    """The open books. prepare=False skips start-up's Alembic runs and backfills, so nothing is written: the
    directory must already exist and open with the key, and each book is opened when first asked for."""
    try:
        books = BookRegistry(s)
    except KeyMissing as e:
        typer.echo(str(e))
        raise typer.Exit(1)
    if require_db and not (s.directory_path.exists() or s.db_path.exists()):
        typer.echo(f"No database at {s.db_path}. Run `steward migrate` first.")
        raise typer.Exit(1)
    if not prepare:
        if not s.directory_path.exists():  # opening it would make an empty file in its place
            typer.echo(f"No directory at {s.directory_path}. Start Steward or run `steward migrate` first.")
            raise typer.Exit(1)
        try:
            check_key(books.directory)
        except WrongKey:
            books.dispose()
            typer.echo(f"The key at {s.key_path} doesn't open {s.directory_path}.")
            raise typer.Exit(1)
        apply_effective(AppSettings(s, books.directory, books.master))
        return books
    try:
        books.prepare()
    except DirectoryUnavailable as e:
        typer.echo(str(e))
        raise typer.Exit(1)
    apply_effective(AppSettings(s, books.directory, books.master))
    return books


def _ours(books: BookRegistry):
    return books.engine_for(books.book("ours"))


def _limits_warning() -> None:
    """Investment views spec: when this year's contribution limits aren't in Steward yet, say so where the household will see it."""
    from steward.deps import today
    from steward.services.limits import cli_warning
    msg = cli_warning(today())
    if msg:
        typer.echo(msg)


def _key(s: Settings) -> str:
    """The key, made if it isn't there: in STEWARD_KEY_FILE when that's set (refused when others can read it, and
    explained when it can't be written), else <data dir>/steward.key. Never printed."""
    try:
        return ensure_key_file(s.key_path) if s.key_file is not None else ensure_key(s.key_path)
    except KeyMissing as e:
        typer.echo(str(e))
        raise typer.Exit(1)


@app.command()
def init_key():
    """Create the database encryption key if it doesn't exist."""
    s = _settings()
    _key(s)
    typer.echo(f"Key ready at {s.key_path}")


@app.command()
def keygen():
    """Print a new encryption key for STEWARD_KEY_FILE (a Docker secret, say). Writes nothing."""
    typer.echo(new_key())


@app.command()
def migrate():
    """Create or upgrade the directory and every book."""
    books = _books(_settings(), require_db=False)
    try:
        bad = [(b.slug, books.unavailable[b.id]) for b in books.books(include_samples=True) if b.id in books.unavailable]
    finally:
        books.dispose()
    for slug, reason in bad:
        typer.echo(f"Book {slug} couldn't be opened or upgraded: {reason}")
    if bad:
        raise typer.Exit(1)
    typer.echo("Database is up to date.")
    _limits_warning()


@app.command()
def setup():
    """First run: make the key (in STEWARD_KEY_FILE if set), set up the database, and print a one-time link to make
    the first account. The link works once, for 30 minutes; running this again closes it. Refuses once anyone has an
    account."""
    from steward.auth import setup_link
    s = _settings()
    _key(s)
    books = _books(s, require_db=False)
    try:
        with Session(books.directory) as ddb:
            try:
                token = setup_link.issue(ddb, clock.now())
            except setup_link.AlreadySetUp:
                typer.echo(setup_link.ALREADY_CLI)
                raise typer.Exit(1)
        unset = zone_needed(AppSettings(s, books.directory, books.master))
    finally:
        books.dispose()
    typer.echo(setup_link.ZONE_NOT_SET if unset else f"Time zone: {clock.household_tz().key}")
    typer.echo(f"Open this within {setup_link.TTL_MINUTES} minutes to make the first account:\n\n"
               f"    {s.base_url.rstrip('/')}/setup#{token}\n\n"
               "It works once. Run the same command again for a new link.")


@app.command()
def create_user(username: str, email: str, display_name: str,
                password: str = typer.Option(None, prompt=True, hide_input=True, confirmation_prompt=True),
                book: str = typer.Option("ours", "--book", help="Book to add them to"),
                role: str = typer.Option("manager", "--role", help="manager or viewer")):
    """Add a household member."""
    if role not in ("manager", "viewer"):
        typer.echo("Choose manager or viewer.")
        raise typer.Exit(1)
    books = _books(_settings())
    try:
        target = books.book(book)
        if target is None:
            typer.echo(f"No book {book}.")
            raise typer.Exit(1)
        with Session(books.directory) as db:
            try:
                u = users.create_user(db, username, email, display_name, password)
            except users.UserExists:
                typer.echo(f"{username} already exists.")
                raise typer.Exit(1)
            except users.WeakPassword as e:
                typer.echo(str(e))
                raise typer.Exit(1)
            add_membership(db, u.id, target.id, role, by=None, note="steward create-user", welcomed=True)
            db.commit()
    finally:
        books.dispose()
    typer.echo(f"Created {username.lower()}")


@app.command()
def reset_password(username: str,
                   password: str = typer.Option(None, prompt=True, hide_input=True, confirmation_prompt=True)):
    """Set a new password for a member, remove their passkeys and sign them out everywhere (last resort if both are
    locked out)."""
    books = _books(_settings())
    try:
        with Session(books.directory) as db:
            u = users.find_user(db, username)
            if u is None:
                typer.echo(f"No user {username}.")
                raise typer.Exit(1)
            try:
                users.set_password(db, u, password)
            except users.WeakPassword as e:
                typer.echo(str(e))
                raise typer.Exit(1)
            gone = reset.start_clean(db, u.id, clock.now())
    finally:
        books.dispose()
    typer.echo(f"Password updated. Signed out everywhere, and {gone} passkey{'' if gone == 1 else 's'} removed.")


@app.command()
def serve():
    """Run the web app."""
    import uvicorn
    from steward import logs
    from steward.app import create_app
    from steward.services import scheduled_backup
    s = _settings()
    books = _books(s)   # the key, the database and the directory are there and open (or a plain error)
    try:
        backup_line = scheduled_backup.backup_line(s, AppSettings(s, books.directory, books.master))
        if s.env == "prod":
            from steward.auth.demo_guard import REFUSED, demo_login_left
            with Session(books.directory) as ddb:
                left = demo_login_left(ddb)
            if left is not None:
                typer.echo(REFUSED.format(username=left))
                raise typer.Exit(1)
    finally:
        books.dispose()
    _limits_warning()
    typer.echo(f"Gateway name: {gateway_name.current()}")
    typer.echo(f"Time zone: {clock.household_tz().key}")
    typer.echo(backup_line)
    logs.configure()
    uvicorn.run(create_app(s), host=s.host, port=s.port, proxy_headers=True, forwarded_allow_ips=s.trusted_proxies,
                access_log=False, log_config=None)


@app.command()
def seed_demo(years: int = 2, seed: int = 7, force: bool = False):
    """Load the fake demo household. Never run this against real data."""
    from sqlalchemy import func, select
    from steward.db.models import Transaction
    from steward.demo import mark_profiles_seen, seed as do_seed, seed_people
    s = _settings()
    if s.env == "prod" and os.environ.get("STEWARD_ALLOW_DEMO") != "1":
        typer.echo("Refusing to seed demo data into a production vault. "
                   "Set STEWARD_ALLOW_DEMO=1 on a throwaway database to override.")
        raise typer.Exit(1)
    books = _books(s)
    try:
        with Session(_ours(books)) as db:
            if not force and db.scalar(select(func.count()).select_from(Transaction)):
                typer.echo("Database already has transactions. Use --force on a throwaway database only.")
                raise typer.Exit(1)
            try:
                counts = do_seed(db, years=years, seed=seed)
            except (users.UserExists, IntegrityError) as e:
                db.rollback()
                typer.echo(f"Could not seed: {e}. Use a fresh database.")
                raise typer.Exit(1)
        with Session(books.directory) as ddb:
            people = seed_people(ddb, books.book("ours").id)
        with Session(_ours(books)) as db:
            mark_profiles_seen(db, people)
    finally:
        books.dispose()
    typer.echo(f"Seeded demo household: {counts}")


@app.command()
def backup(dir: Path = typer.Option(None, "--dir", help="Where to write copies (default: STEWARD_BACKUP_DIR, else <data dir>/backups)")):
    """Write an encrypted copy of the directory and of every book, keeping the 14 newest of each."""
    from steward.services import backup as svc
    s = _settings()
    books = _books(s)
    try:
        written, skipped = svc.backup_all(books, (dir if dir is not None else s.backups_dir).resolve())
    except ValueError as e:
        typer.echo(str(e))
        raise typer.Exit(1)
    finally:
        books.dispose()
    for p in written:
        typer.echo(str(p))
    for line in skipped:
        typer.echo(line)


@app.command("restore-check")
def restore_check_cmd(
    dir: Path = typer.Option(None, "--dir", help="The backups folder to check (default: STEWARD_BACKUP_DIR, else <data dir>/backups)"),
    max_age_hours: int = typer.Option(restore_check.MAX_AGE_HOURS, "--max-age-hours", min=1,
                                      help="Fail when the newest backup is older"),
):
    """Prove last night's backup restores: every copy opens with its key, is whole, current and not empty, and every
    uploaded file decrypts. Exit 0 when it all passed, 1 when anything failed. The live books are opened only to
    count their transactions: no migrations or backfills run, so the check never writes to them."""
    s = _settings()
    books = _books(s, prepare=False)
    try:
        result = restore_check.restore_check(books, (dir if dir is not None else s.backups_dir).resolve(),
                                             max_age_hours=max_age_hours)
    finally:
        books.dispose()
    for line in result.lines:
        typer.echo(line)
    raise typer.Exit(0 if result.ok else 1)


@app.command("restore-from-export")
def restore_from_export(file: Path,
                        name: str = typer.Option(None, "--name", help="The new book's name (default: \"{old name} (restored)\")"),
                        manager: list[str] = typer.Option(..., "--manager", help="Username of a manager of the new book (repeat)")):
    """Make a new book from an encrypted backup made in Settings, Export. Asks for its passphrase at a prompt. Never
    overwrites a book: the new one has a new id and a key from this NAS's steward.key."""
    import getpass

    from steward.deps import now
    from steward.services import book_restore
    books = _books(_settings())
    try:
        with Session(books.directory) as ddb:
            ids = []
            for username in manager:
                u = users.find_user(ddb, username)
                if u is None:
                    typer.echo(f"No user {username}.")
                    raise typer.Exit(1)
                ids.append(u.id)
        passphrase = getpass.getpass("Passphrase for this backup: ")
        try:
            info, counts = book_restore.restore(books, file.resolve(), passphrase, name, ids, now())
        except book_restore.RestoreRefused as e:
            typer.echo(e.message)
            raise typer.Exit(1)
        finally:
            passphrase = None
    finally:
        books.dispose()
    typer.echo(f"Restored book {info.slug}: {counts['transactions']:,} transactions, {counts['files']:,} files")


@app.command()
def sync(book: str = typer.Option(None, "--book", help="Only this book (default: every book with a link)")):
    """Pull the latest accounts and transactions from SimpleFIN now."""
    import httpx2
    from steward.books.jobs import sync_all_books
    from steward.deps import now
    from steward.services.categorizer_client import client_for
    s = _settings()
    books = _books(s)
    model = client_for(s)
    try:
        with httpx2.Client(timeout=60) as http:
            results = sync_all_books(books, http, model, now(), s.simplefin_allowed_hosts, only=book)
    finally:
        model.close()
        books.dispose()
    if book is not None and not results:
        typer.echo(f"No book {book}.")
        raise typer.Exit(1)
    if results and all(r == "not linked" for r in results.values()):
        typer.echo("SimpleFIN isn't linked yet.")
        raise typer.Exit(1)
    failed = False
    for slug, res in results.items():
        if isinstance(res, str):
            typer.echo(f"{slug}: {res}")
            failed = failed or res == "failed" or (book is not None and res == "not linked")
            continue
        typer.echo(f"{slug}: {res.institutions_ok} ok, {res.institutions_failed} failed, {res.accounts_new} new "
                   f"accounts, {res.transactions_new} new transactions")
        for e in res.errors:
            typer.echo(f"{slug}: {e}")
        failed = failed or bool(res.errors and res.institutions_ok == 0)
    if failed:
        raise typer.Exit(1)


@app.command("same-accounts")
def same_accounts(check: bool = typer.Option(False, "--check",
                                             help="Look again for accounts already in each household book that look "
                                                  "like the same account")):
    """Accounts that look like one account under two logins: the questions open in each household book, or with
    --check, look again for pairs already in the book (they go on Home)."""
    from steward.deps import now
    from steward.services.same_account.apart import check_book
    from steward.services.same_account.questions import open_count
    books = _books(_settings())
    try:
        for b in books.books():
            if b.kind != "household" or b.id in books.unavailable:
                continue
            with Session(books.engine_for(b)) as db:
                if check:
                    n = check_book(db, now())
                    db.commit()
                    line = (f"{b.slug}: nothing looks like the same account." if n == 0 else
                            f"{b.slug}: 1 pair looks like the same account. It's on Home." if n == 1 else
                            f"{b.slug}: {n} pairs look like the same account. They're on Home.")
                else:
                    n = open_count(db)
                    line = (f"{b.slug}: no questions open." if n == 0 else
                            f"{b.slug}: 1 question open." if n == 1 else f"{b.slug}: {n} questions open.")
            typer.echo(line)
    finally:
        books.dispose()


book_app = typer.Typer(no_args_is_help=True, help="Books: one family's finances each")
app.add_typer(book_app, name="book")


@book_app.command("create")
def book_create(name: str,
                kind: str = typer.Option("parent", "--kind", help="household or parent"),
                owner: list[str] = typer.Option(None, "--owner", help="An owner name, for a parent book (repeat)"),
                manager: list[str] = typer.Option(..., "--manager", help="Username of a first manager (repeat)")):
    """Make a book, for when nobody can sign in to do it from Settings, Books."""
    books = _books(_settings())
    try:
        with Session(books.directory) as ddb:
            ids = []
            for username in manager:
                u = users.find_user(ddb, username)
                if u is None:
                    typer.echo(f"No user {username}.")
                    raise typer.Exit(1)
                ids.append(u.id)
            try:
                info = create_book(books, ddb, name=name, kind=kind, owner_labels=list(owner or []), managers=ids,
                                   allow_household=True)   # only while none exists
            except BookRefused as e:
                typer.echo(str(e))
                raise typer.Exit(1)
    finally:
        books.dispose()
    typer.echo(f"Created book {info.slug} ({info.name})")


@book_app.command("list")
def book_list():
    """Every book: slug, kind and name, and why it can't be opened if it can't."""
    books = _books(_settings())
    try:
        for b in books.books(include_samples=True):
            line = f"{b.slug}\t{b.kind}\t{b.name}"
            if b.id in books.unavailable:
                line += f"\tcan't be opened: {books.unavailable[b.id]}"
            typer.echo(line)
    finally:
        books.dispose()


@book_app.command("people")
def book_people(slug: str = typer.Argument("ours", help="The book's slug")):
    """Who is in a book, oldest first, and who a household calls Person 1 and Person 2. Changes nothing."""
    from steward.books.people import household_people
    books = _books(_settings(), prepare=False)
    try:
        info = books.book(slug)
        if info is None:
            typer.echo(f"No book {slug}.")
            raise typer.Exit(1)
        people = books.people(info.id)
    finally:
        books.dispose()
    first, second = household_people(people) if info.kind == "household" else (None, None)
    for p in sorted(people, key=lambda p: p.id):
        tag = "Person 1" if p == first else "Person 2" if p == second else "member"
        typer.echo(f"{tag}\t{p.display_name}\t{p.username}\t{p.role}\tid {p.id}")


@app.command()
def bench(runs: int = typer.Option(5, min=1, help="Timed solves to run"),
          histories: int = typer.Option(2000, help="Simulated histories per solve (the plan uses 2,000)")):
    """Time the retirement engine on this machine against its budgets. Needs no database."""
    from steward.engine.bench import format_bench, run_bench
    res = run_bench(runs=runs, histories=histories)
    typer.echo(format_bench(res))
    if not res.within_budget:
        raise typer.Exit(1)
@app.command()
def ask(question: str,
        book: str = typer.Option(..., "--book", help="The book to ask about"),
        as_: str = typer.Option(..., "--as", help="Username of the member asking"),
        conversation: int = typer.Option(None, "--conversation", help="Continue this conversation")):
    """Ask Claude about a book through the gateway, as a member (ruling 15)."""
    from steward import deps
    from steward.advisor import gateway as gw_mod
    from steward.advisor.state import money
    from steward.advisor.turn import AskEnv, ChatRefused, is_member, run_turn, start_turn
    from steward.books.registry import household_name
    from steward.books.sample_guard import SAMPLE_REFUSED, SampleRefused
    from steward.inventory.present import size_label
    from steward_boundary.protocol import LINES
    s = _settings()
    books = _books(s)
    client = None
    try:
        info = books.book(book)
        if info is None:
            typer.echo(f"No book {book}.")
            raise typer.Exit(1)
        with Session(books.directory) as ddb:
            u = users.find_user(ddb, as_)
        if u is None or not is_member(books.directory, info.id, u.id):
            typer.echo(f"{as_} isn't a member of {book}.")
            raise typer.Exit(1)
        client = gw_mod.client_from_settings(s)
        if client is None:
            typer.echo(f"{gateway_name.fill(LINES['not_set_up'])} Run steward advisor pair first.")
            raise typer.Exit(1)
        with Session(books.directory) as ddb:
            household = household_name(ddb)
        try:
            env = AskEnv(bind=books.engine_for(info).execution_options(immediate=True), directory=books.directory,
                         book=info, user_id=u.id, people=lambda: books.people(info.id),
                         plan_cache=books.plan_cache(info.id), gateway=client, now=deps.now, today=deps.today,
                         household_name=household)
        except SampleRefused:
            typer.echo(SAMPLE_REFUSED)
            raise typer.Exit(1)
        try:
            prep = start_turn(env, question, conversation)
        except ChatRefused as e:
            typer.echo(e.message)
            raise typer.Exit(1)
        final = None
        for event in run_turn(env, prep):
            if event["type"] == "conversation" and event["note"]:
                typer.echo(event["note"], err=True)
            elif event["type"] == "redacted":
                typer.echo(f"Will send: {event['text']}", err=True)
            elif event["type"] == "status":
                typer.echo(f"… {event['text']}", err=True)
            elif event["type"] == "done":
                final = event
        if final["answer"]:
            typer.echo(final["answer"])
        for line in (final["line"], final["long_line"]):
            if line:
                typer.echo(line)
        typer.echo(f"Sent: {final['parts']} parts, {size_label(final['bytes'])} · cost {money(final['cost_cents'])} "
                   f"· conversation {final['conversation_id']}", err=True)
        if final["stop"] not in ("end_turn", "max_tokens"):
            raise typer.Exit(1)
    finally:
        if client is not None:
            client.close()
        books.dispose()


advisor_app = typer.Typer(no_args_is_help=True, help="Chat's link to the gateway")
app.add_typer(advisor_app, name="advisor")


@advisor_app.command("pair")
def advisor_pair(gateway: str = typer.Option(None, "--gateway", help="The gateway's address, if STEWARD_GATEWAY_URL isn't set")):
    """Pair with the gateway: prints a code to give to `steward-gateway pair` on the gateway's machine, then waits for it."""
    import httpx2
    from steward.advisor.gateway import new_code, pair
    s = _settings()
    url = gateway or s.gateway_url
    if not url:
        typer.echo(gateway_name.fill("Set STEWARD_GATEWAY_URL ({gateway}'s Tailscale address, for example "
                                     "http://100.x.y.z:8430) or pass --gateway."))
        raise typer.Exit(1)
    code = new_code()
    typer.echo(gateway_name.fill(f"On {{gateway}}, within 10 minutes, run:\n\n    steward-gateway pair {code}\n\nWaiting…"))
    with httpx2.Client(timeout=5) as http:
        result = pair(s.advisor_token_path, url, code, http=http)
    if result != "paired":
        typer.echo("The gateway refused the code." if result == "refused" else "Nothing answered in 10 minutes.")
        raise typer.Exit(1)
    typer.echo("Paired.")
    if s.gateway_url != url:
        typer.echo(f"Add STEWARD_GATEWAY_URL={url} to Steward's settings file and restart Steward.")


@advisor_app.command("check")
def advisor_check():
    """Show whether the gateway answers, and this month's spending."""
    from steward.advisor import gateway as gw_mod
    from steward.advisor.state import budget_lines, gateway_line, gateway_state
    from steward.deps import today
    s = _settings()
    client = gw_mod.client_from_settings(s)
    try:
        h = client.health() if client is not None else None
    except (gw_mod.GatewayUnavailable, gw_mod.GatewayRefused):
        h = None
    finally:
        if client is not None:
            client.close()
    state = gateway_state(h, client is not None)
    typer.echo(gateway_line(state))
    if h and h.get("budget"):
        typer.echo(budget_lines(h["budget"], "the household book", today())["line"])
    if state != "ok":
        raise typer.Exit(1)


@advisor_app.command("log")
def advisor_log(book: str = typer.Option(..., "--book"), limit: int = typer.Option(20, "--limit", min=1, max=50),
                as_json: bool = typer.Option(False, "--json", help="Every row with its exact JSON")):
    """What was sent to Anthropic from a book, newest first (spec 4.6)."""
    import json as _json
    from steward.advisor.outgoing import export, requests_page
    from steward.deps import today
    books = _books(_settings())
    try:
        info = books.book(book)
        if info is None:
            typer.echo(f"No book {book}.")
            raise typer.Exit(1)
        with Session(books.engine_for(info)) as db:
            if as_json:
                typer.echo(_json.dumps(export(db), ensure_ascii=False, indent=2))
                return
            for r in requests_page(db, books.directory, offset=0, today=today())["requests"][:limit]:
                typer.echo(f"{r['when']}\t{r['who']}\t{r['channel']}\t{r['what']}\t{r['size']}")
    finally:
        books.dispose()
