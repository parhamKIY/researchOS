"""Owned research projects and optimistic revisions."""

import sqlalchemy as sa
from alembic import op

revision = "0002_projects"
down_revision = "0001_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(5000), nullable=False, server_default=""),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("owner_id", "id", name="uq_projects_owner_id"),
        sa.CheckConstraint("length(trim(name)) > 0", name=op.f("ck_projects_nonempty_name")),
        sa.CheckConstraint("revision > 0", name=op.f("ck_projects_positive_revision")),
    )
    op.create_index("ix_projects_owner_created", "projects", ["owner_id", "created_at", "id"])


def downgrade():
    op.drop_table("projects")
