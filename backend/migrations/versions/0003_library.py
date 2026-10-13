"""Private library, owner-constrained memberships, replay and durable cleanup."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_library"
down_revision = "0002_projects"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "papers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("title", sa.String(500)),
        sa.Column(
            "external_processing_allowed", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("owner_id", "id", name="uq_papers_owner_id"),
        sa.CheckConstraint("revision > 0", name=op.f("ck_papers_positive_revision")),
    )
    op.create_index("ix_papers_owner_created", "papers", ["owner_id", "created_at", "id"])
    op.create_table(
        "paper_files",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(36), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(64), nullable=False, server_default="application/pdf"),
        sa.ForeignKeyConstraint(
            ["owner_id", "paper_id"], ["papers.owner_id", "papers.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("owner_id", "sha256", name="uq_paper_files_owner_id"),
        sa.UniqueConstraint("owner_id", "paper_id", name="uq_paper_files_owner_paper"),
        sa.UniqueConstraint("storage_key", name="uq_paper_files_storage_key"),
        sa.CheckConstraint("byte_size > 0", name=op.f("ck_paper_files_positive_size")),
        sa.CheckConstraint("length(sha256) = 64", name=op.f("ck_paper_files_sha256_length")),
    )
    op.create_table(
        "paper_projects",
        sa.Column("owner_id", sa.Uuid(), primary_key=True),
        sa.Column("paper_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), primary_key=True),
        sa.ForeignKeyConstraint(
            ["owner_id", "paper_id"], ["papers.owner_id", "papers.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "project_id"], ["projects.owner_id", "projects.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_paper_projects_owner_project", "paper_projects", ["owner_id", "project_id"])
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "operation", "key", name="uq_idempotency_records_owner_id"),
    )
    op.create_index("ix_idempotency_records_expires_at", "idempotency_records", ["expires_at"])
    op.create_table(
        "storage_cleanup_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("storage_key", sa.String(36), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(64)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("storage_key", name="uq_storage_cleanup_tasks_storage_key"),
    )


def downgrade():
    for name in [
        "storage_cleanup_tasks",
        "idempotency_records",
        "paper_projects",
        "paper_files",
        "papers",
    ]:
        op.drop_table(name)
