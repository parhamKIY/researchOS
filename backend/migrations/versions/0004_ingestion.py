"""persist versioned document extraction and durable jobs"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_ingestion"
down_revision = "0003_library"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_paper_files_owner_paper_id", "paper_files", ["owner_id", "paper_id", "id"]
    )
    op.create_table(
        "document_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("parser_name", sa.String(length=100), nullable=False),
        sa.Column("parser_version", sa.String(length=300), nullable=False),
        sa.Column("parser_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "warnings", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('queued','processing','ready','partially_ready','failed')",
            name=op.f("ck_document_versions_valid_state"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "paper_id", "file_id"],
            ["paper_files.owner_id", "paper_files.paper_id", "paper_files.id"],
            name=op.f("fk_document_versions_owner_id_paper_files"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_document_versions_owner_id")),
        sa.UniqueConstraint(
            "owner_id", "paper_id", "id", name="uq_document_versions_owner_paper_id"
        ),
    )
    op.create_index(
        "ix_document_versions_owner_paper",
        "document_versions",
        ["owner_id", "paper_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "document_pages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_status", sa.String(length=32), nullable=False),
        sa.Column("width", sa.Float(), nullable=False),
        sa.Column("height", sa.Float(), nullable=False),
        sa.Column(
            "warnings", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.CheckConstraint(
            "text_status IN ('available','no_text','failed')",
            name=op.f("ck_document_pages_valid_text_status"),
        ),
        sa.CheckConstraint(
            "page_number > 0 AND width > 0 AND height > 0",
            name=op.f("ck_document_pages_positive_geometry"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "document_version_id"],
            ["document_versions.owner_id", "document_versions.id"],
            name=op.f("fk_document_pages_owner_id_document_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_pages")),
        sa.UniqueConstraint(
            "owner_id", "document_version_id", "id", name="uq_document_pages_owner_version_id"
        ),
        sa.UniqueConstraint(
            "owner_id",
            "document_version_id",
            "page_number",
            name="uq_document_pages_owner_version_number",
        ),
    )
    op.create_table(
        "paper_sections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("heading", sa.String(length=160), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("extraction_method", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id", "document_version_id"],
            ["document_versions.owner_id", "document_versions.id"],
            name=op.f("fk_paper_sections_owner_id_document_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_sections")),
        sa.UniqueConstraint(
            "owner_id", "document_version_id", "id", name="uq_paper_sections_owner_version_id"
        ),
        sa.UniqueConstraint(
            "owner_id",
            "document_version_id",
            "ordinal",
            name="uq_paper_sections_owner_version_ordinal",
        ),
    )
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), server_default="ingestion", nullable=False),
        sa.Column("state", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=True),
        sa.Column("progress_percent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retry_of_job_id", sa.Uuid(), nullable=True),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "dispatch_after",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "progress_percent < 100 OR state IN ('completed','partially_completed')",
            name=op.f("ck_processing_jobs_terminal_progress"),
        ),
        sa.CheckConstraint(
            "state <> 'running' OR (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name=op.f("ck_processing_jobs_running_lease"),
        ),
        sa.CheckConstraint(
            "state IN ('queued','running','completed','partially_completed','failed')",
            name=op.f("ck_processing_jobs_valid_state"),
        ),
        sa.CheckConstraint(
            "progress_percent BETWEEN 0 AND 100 AND attempt >= 0",
            name=op.f("ck_processing_jobs_valid_progress"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "paper_id", "document_version_id"],
            ["document_versions.owner_id", "document_versions.paper_id", "document_versions.id"],
            name=op.f("fk_processing_jobs_owner_id_document_versions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "paper_id", "retry_of_job_id"],
            ["processing_jobs.owner_id", "processing_jobs.paper_id", "processing_jobs.id"],
            name=op.f("fk_processing_jobs_owner_id_processing_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processing_jobs")),
        sa.UniqueConstraint("owner_id", "paper_id", "id", name="uq_processing_jobs_owner_paper_id"),
    )
    op.create_index(
        "ix_processing_jobs_dispatch", "processing_jobs", ["state", "dispatch_after"], unique=False
    )
    op.create_index(
        "ix_processing_jobs_lease", "processing_jobs", ["state", "lease_expires_at"], unique=False
    )
    op.create_index(
        "uq_processing_jobs_active_fingerprint",
        "processing_jobs",
        ["owner_id", "fingerprint"],
        unique=True,
        postgresql_where=sa.text("state IN ('queued','running')"),
    )
    op.create_table(
        "paper_figures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=36), nullable=False),
        sa.Column("caption", sa.String(length=2000), nullable=True),
        sa.Column("caption_start", sa.Integer(), nullable=True),
        sa.Column("caption_end", sa.Integer(), nullable=True),
        sa.Column("caption_method", sa.String(length=64), nullable=True),
        sa.Column("bounding_box", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("extraction_method", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id", "document_version_id", "page_id"],
            ["document_pages.owner_id", "document_pages.document_version_id", "document_pages.id"],
            name=op.f("fk_paper_figures_owner_id_document_pages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "paper_id", "document_version_id"],
            ["document_versions.owner_id", "document_versions.paper_id", "document_versions.id"],
            name=op.f("fk_paper_figures_owner_id_document_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_figures")),
        sa.UniqueConstraint(
            "owner_id",
            "document_version_id",
            "ordinal",
            name="uq_paper_figures_owner_version_ordinal",
        ),
        sa.UniqueConstraint("storage_key", name=op.f("uq_paper_figures_storage_key")),
    )
    op.create_table(
        "section_spans",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "start_offset >= 0 AND end_offset > start_offset",
            name=op.f("ck_section_spans_valid_offsets"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "document_version_id", "page_id"],
            ["document_pages.owner_id", "document_pages.document_version_id", "document_pages.id"],
            name=op.f("fk_section_spans_owner_id_document_pages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "document_version_id", "section_id"],
            ["paper_sections.owner_id", "paper_sections.document_version_id", "paper_sections.id"],
            name=op.f("fk_section_spans_owner_id_paper_sections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "owner_id",
            "document_version_id",
            "section_id",
            "page_id",
            "start_offset",
            name=op.f("pk_section_spans"),
        ),
    )


def downgrade():
    op.drop_table("section_spans")
    op.drop_table("paper_figures")
    op.drop_index(
        "uq_processing_jobs_active_fingerprint",
        table_name="processing_jobs",
        postgresql_where=sa.text("state IN ('queued','running')"),
    )
    op.drop_index("ix_processing_jobs_lease", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_dispatch", table_name="processing_jobs")
    op.drop_table("processing_jobs")
    op.drop_table("paper_sections")
    op.drop_table("document_pages")
    op.drop_index("ix_document_versions_owner_paper", table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_constraint("uq_paper_files_owner_paper_id", "paper_files", type_="unique")
