"""Explicit administrator roles."""

import sqlalchemy as sa
from alembic import op

revision = "0006_admin"
down_revision = "0005_providers"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users", sa.Column("is_admin", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column("users", sa.Column("revision", sa.Integer(), server_default="1", nullable=False))


def downgrade():
    op.drop_column("users", "revision")
    op.drop_column("users", "is_admin")
