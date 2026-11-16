"""user.is_placeholder: an account made by an invite is marked, so cleanup never guesses from the username

Revision ID: d0003
Revises: d0002
"""
import sqlalchemy as sa
from alembic import op

revision = "d0003"
down_revision = "d0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A plain ADD COLUMN: a batch rebuild would drop and recreate "user" while other tables point at it.
    op.add_column("user", sa.Column("is_placeholder", sa.Boolean(), nullable=False, server_default=sa.false()))
    # An invite makes the account with username "invited-" and 12 hex digits (secrets.token_hex(6)). A real account
    # can have such a name only through its email, so mark only one that has never signed in, belongs to no book and
    # still has an open invite or sign-in link.
    op.execute(sa.text(
        "UPDATE \"user\" SET is_placeholder = 1 WHERE length(username) = 20 AND username GLOB 'invited-[0-9a-f]*' "
        "AND substr(username, 9) NOT GLOB '*[^0-9a-f]*' "
        "AND NOT EXISTS (SELECT 1 FROM session WHERE session.user_id = \"user\".id) "
        "AND NOT EXISTS (SELECT 1 FROM membership WHERE membership.user_id = \"user\".id) "
        "AND (EXISTS (SELECT 1 FROM pending_invite WHERE pending_invite.user_id = \"user\".id "
        "AND pending_invite.accepted_at IS NULL AND pending_invite.expires_at > strftime('%Y-%m-%d %H:%M:%f', 'now')) "
        "OR EXISTS (SELECT 1 FROM password_reset WHERE password_reset.user_id = \"user\".id "
        "AND password_reset.used_at IS NULL AND password_reset.expires_at > strftime('%Y-%m-%d %H:%M:%f', 'now')))"))


def downgrade() -> None:
    op.drop_column("user", "is_placeholder")
