"""profile: kids' college share, living costs and soft removal; setup steps become Profile's five sections with a
resume point; Home's line is hidden for a week, not for good; the home is linked to the book's only mortgage

Revision ID: 0030
Revises: 0029

Profile and the household spec, Data and migration. child gains share_pct (0-100 in tens, default 100), covers_living
(default true) and removed_at (a kid removed, kept until the undo window passes); its cost_level may also be two_year
or not_sure. Existing kids get 100% with living costs, so every plan is unchanged. setup_step's keys become the five
sections (you, kids, home, benefits, banks); its status may be NULL (a resume point with no answer yet) and it gains
resume_step. Old rows merge: about/pay -> you and health/earnings -> benefits, skipped if either was, otherwise done;
children -> kids and banks -> banks as they were; home skipped stays skipped, and home doesn't apply becomes the fact
home.owns = no (no row). A merged row keeps the newest row's user_id and at. user_setup's home_hidden_at (Hide, for
good) becomes later_until, a week from now. Where the home (the newest home.account_id fact) is an active property with
no loan and the book has exactly one active mortgage, the home links it (account.loan_id): it is the mortgage the Plan
already models. Both tables are rebuilt by hand (create, copy, drop, rename) so their CHECK constraints are replaced
exactly; nothing points at either. Downgrade maps the sections back (you -> about, kids -> children, benefits ->
health), sets two_year and not_sure to in_state_public, deletes removed kids and drops the new columns, turns
later_until into home_hidden_at, deletes the home.owns facts written here and clears every property's loan_id. It is
lossy for share and living costs.
"""
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

NO_HOME_NOTE = "From setup's Doesn't apply"
LEVELS_NEW = ("two_year", "in_state_public", "out_of_state_public", "private", "not_sure")
LEVELS_OLD = ("in_state_public", "out_of_state_public", "private")
SECTIONS = ("you", "kids", "home", "benefits", "banks")
STEPS_OLD = ("about", "banks", "home", "pay", "children", "health", "earnings")
SECTION_OF = {"about": "you", "pay": "you", "children": "kids", "home": "home", "health": "benefits",
              "earnings": "benefits", "banks": "banks"}
OLD_OF = {"you": "about", "kids": "children", "home": "home", "benefits": "health", "banks": "banks"}
STAMP = "%Y-%m-%d %H:%M:%S.%f"


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _child_table(name: str, levels: tuple[str, ...], new: bool) -> None:
    cols = [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(length=40), nullable=False),
        sa.Column("birth_year", sa.Integer(), nullable=False),
        sa.Column("cost_level", sa.String(length=20), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id"), nullable=True),
        sa.Column("monthly_contribution_cents", sa.Integer(), nullable=False),
    ]
    checks = [sa.CheckConstraint(f"cost_level IN ({_in(levels)})", name="ck_child_cost_level")]
    if new:
        cols += [sa.Column("share_pct", sa.Integer(), nullable=False, server_default=sa.text("100")),
                 sa.Column("covers_living", sa.Boolean(), nullable=False, server_default=sa.text("1")),
                 sa.Column("removed_at", sa.DateTime(), nullable=True)]
        checks.append(sa.CheckConstraint("share_pct BETWEEN 0 AND 100 AND share_pct % 10 = 0", name="ck_child_share_pct"))
    op.create_table(name, *cols, sa.UniqueConstraint("account_id", name="uq_child_account"), *checks)


def _setup_table(name: str, steps: tuple[str, ...], new: bool) -> None:
    cols = [sa.Column("step", sa.String(length=10), primary_key=True),
            sa.Column("status", sa.String(length=12), nullable=new),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("at", sa.DateTime(), nullable=False)]
    if new:
        cols.append(sa.Column("resume_step", sa.String(length=20), nullable=True))
    op.create_table(name, *cols,
                    sa.CheckConstraint(f"step IN ({_in(steps)})", name="ck_setup_step_step"),
                    sa.CheckConstraint("status IN ('done', 'skipped', 'doesnt_apply')", name="ck_setup_step_status"))


def _swap(old: str, new: str) -> None:
    op.drop_table(old)
    op.rename_table(new, old)


def upgrade() -> None:
    c = op.get_bind()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    _child_table("child_new", LEVELS_NEW, new=True)
    c.execute(sa.text("INSERT INTO child_new (id, label, birth_year, cost_level, account_id, monthly_contribution_cents) "
                      "SELECT id, label, birth_year, cost_level, account_id, monthly_contribution_cents FROM child"))
    _swap("child", "child_new")

    rows = c.execute(sa.text("SELECT step, status, user_id, at FROM setup_step ORDER BY at, step")).all()
    merged: dict[str, dict] = {}
    for step, status, uid, at in rows:
        if step == "home" and status == "doesnt_apply":
            c.execute(sa.text("INSERT INTO fact (key, value, as_of, note, created_at) VALUES ('home.owns', 'no', :d, :n, :at)"),
                      {"d": now.date().isoformat(), "n": NO_HOME_NOTE, "at": now.strftime(STAMP)})
            continue
        m = merged.setdefault(SECTION_OF[step], {"statuses": set()})
        m["statuses"].add(status)
        m["user_id"], m["at"] = uid, at                    # ordered by at: the newest row wins
    _setup_table("setup_step_new", SECTIONS, new=True)
    for section, m in merged.items():
        s = m["statuses"]
        status = "skipped" if "skipped" in s else "doesnt_apply" if "doesnt_apply" in s else "done"
        c.execute(sa.text("INSERT INTO setup_step_new (step, status, user_id, at) VALUES (:s, :st, :u, :at)"),
                  {"s": section, "st": status, "u": m["user_id"], "at": m["at"]})
    _swap("setup_step", "setup_step_new")

    with op.batch_alter_table("user_setup") as b:
        b.add_column(sa.Column("later_until", sa.DateTime(), nullable=True))
    c.execute(sa.text("UPDATE user_setup SET later_until = :w WHERE home_hidden_at IS NOT NULL"),
              {"w": (now + timedelta(days=7)).strftime(STAMP)})
    with op.batch_alter_table("user_setup") as b:
        b.drop_column("home_hidden_at")

    link = c.execute(sa.text("SELECT value FROM fact WHERE key = 'home.account_id' ORDER BY as_of DESC, id DESC LIMIT 1")).scalar()
    if link is not None and str(link).isdigit():
        home = c.execute(sa.text("SELECT id FROM account WHERE id = :id AND type = 'property' AND is_active = 1 "
                                 "AND loan_id IS NULL"), {"id": int(link)}).scalar()
        mortgages = c.execute(sa.text("SELECT id FROM account WHERE type = 'mortgage' AND is_active = 1")).scalars().all()
        if home is not None and len(mortgages) == 1:
            c.execute(sa.text("UPDATE account SET loan_id = :m WHERE id = :h"), {"m": mortgages[0], "h": home})


def downgrade() -> None:
    c = op.get_bind()
    c.execute(sa.text("UPDATE account SET loan_id = NULL WHERE type = 'property'"))
    c.execute(sa.text("DELETE FROM fact WHERE key = 'home.owns' AND note = :n"), {"n": NO_HOME_NOTE})
    with op.batch_alter_table("user_setup") as b:
        b.add_column(sa.Column("home_hidden_at", sa.DateTime(), nullable=True))
    c.execute(sa.text("UPDATE user_setup SET home_hidden_at = later_until WHERE later_until IS NOT NULL"))
    with op.batch_alter_table("user_setup") as b:
        b.drop_column("later_until")

    _setup_table("setup_step_new", STEPS_OLD, new=False)
    c.execute(sa.text("INSERT INTO setup_step_new (step, status, user_id, at) SELECT CASE step "
                      + " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in OLD_OF.items())
                      + " END, status, user_id, at FROM setup_step WHERE status IS NOT NULL"))
    _swap("setup_step", "setup_step_new")

    c.execute(sa.text("DELETE FROM child WHERE removed_at IS NOT NULL"))
    c.execute(sa.text("UPDATE child SET cost_level = 'in_state_public' WHERE cost_level IN ('two_year', 'not_sure')"))
    _child_table("child_new", LEVELS_OLD, new=False)
    c.execute(sa.text("INSERT INTO child_new (id, label, birth_year, cost_level, account_id, monthly_contribution_cents) "
                      "SELECT id, label, birth_year, cost_level, account_id, monthly_contribution_cents FROM child"))
    _swap("child", "child_new")
