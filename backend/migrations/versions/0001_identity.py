"""Initial account and session persistence; authentication routes follow in stage 2."""

import sqlalchemy as sa
from alembic import op

revision = "0001_identity"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email_normalized", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("email_normalized", name="uq_users_email_normalized"),
        sa.CheckConstraint(
            "email_normalized = lower(trim(email_normalized))",
            name=op.f("ck_users_normalized_email"),
        ),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        sa.CheckConstraint(
            "length(token_hash) = 64", name=op.f("ck_auth_sessions_token_hash_length")
        ),
        sa.CheckConstraint(
            "length(csrf_token_hash) = 64", name=op.f("ck_auth_sessions_csrf_hash_length")
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_auth_sessions_positive_lifetime")
        ),
    )
    op.create_index("ix_auth_sessions_owner_id", "auth_sessions", ["owner_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])


def downgrade():
    op.drop_table("auth_sessions")
    op.drop_table("users")
