import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA_REVISION = "0004_ingestion"


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email_normalized"),
        CheckConstraint(
            "email_normalized = lower(trim(email_normalized))", name="normalized_email"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email_normalized: Mapped[str] = mapped_column(String(320))
    password_hash: Mapped[str] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        CheckConstraint("length(token_hash) = 64", name="token_hash_length"),
        CheckConstraint("length(csrf_token_hash) = 64", name="csrf_hash_length"),
        CheckConstraint("expires_at > created_at", name="positive_lifetime"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64))
    csrf_token_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("owner_id", "id"),
        CheckConstraint("length(trim(name)) > 0", name="nonempty_name"),
        CheckConstraint("revision > 0", name="positive_revision"),
        Index("ix_projects_owner_created", "owner_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(5000), default="", server_default="")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Paper(Base):
    __tablename__ = "papers"
    __table_args__ = (
        UniqueConstraint("owner_id", "id"),
        CheckConstraint("revision > 0", name="positive_revision"),
        Index("ix_papers_owner_created", "owner_id", "created_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str | None] = mapped_column(String(500))
    external_processing_allowed: Mapped[bool] = mapped_column(Boolean, server_default="false")
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperFile(Base):
    __tablename__ = "paper_files"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "paper_id"], ["papers.owner_id", "papers.id"], ondelete="CASCADE"
        ),
        UniqueConstraint("owner_id", "sha256"),
        UniqueConstraint("owner_id", "paper_id", name="uq_paper_files_owner_paper"),
        UniqueConstraint("storage_key"),
        UniqueConstraint("owner_id", "paper_id", "id", name="uq_paper_files_owner_paper_id"),
        CheckConstraint("byte_size > 0", name="positive_size"),
        CheckConstraint("length(sha256) = 64", name="sha256_length"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column()
    paper_id: Mapped[uuid.UUID] = mapped_column()
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(36))
    original_name: Mapped[str] = mapped_column(String(255))
    byte_size: Mapped[int] = mapped_column(Integer)
    media_type: Mapped[str] = mapped_column(
        String(64), default="application/pdf", server_default="application/pdf"
    )


class PaperProject(Base):
    __tablename__ = "paper_projects"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "paper_id"], ["papers.owner_id", "papers.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["owner_id", "project_id"], ["projects.owner_id", "projects.id"], ondelete="CASCADE"
        ),
        Index("ix_paper_projects_owner_project", "owner_id", "project_id"),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("owner_id", "operation", "key"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    operation: Mapped[str] = mapped_column(String(64))
    key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class StorageCleanup(Base):
    __tablename__ = "storage_cleanup_tasks"
    __table_args__ = (UniqueConstraint("storage_key"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    storage_key: Mapped[str] = mapped_column(String(36))
    attempt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "paper_id", "file_id"],
            ["paper_files.owner_id", "paper_files.paper_id", "paper_files.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("owner_id", "id"),
        UniqueConstraint("owner_id", "paper_id", "id", name="uq_document_versions_owner_paper_id"),
        CheckConstraint(
            "state IN ('queued','processing','ready','partially_ready','failed')",
            name="valid_state",
        ),
        Index("ix_document_versions_owner_paper", "owner_id", "paper_id", "created_at", "id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column()
    paper_id: Mapped[uuid.UUID] = mapped_column()
    file_id: Mapped[uuid.UUID] = mapped_column()
    state: Mapped[str] = mapped_column(String(32), default="queued", server_default="queued")
    parser_name: Mapped[str] = mapped_column(String(100))
    parser_version: Mapped[str] = mapped_column(String(300))
    parser_config: Mapped[dict] = mapped_column(JSONB)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    warnings: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "document_version_id"],
            ["document_versions.owner_id", "document_versions.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "owner_id",
            "document_version_id",
            "page_number",
            name="uq_document_pages_owner_version_number",
        ),
        UniqueConstraint(
            "owner_id", "document_version_id", "id", name="uq_document_pages_owner_version_id"
        ),
        CheckConstraint("page_number > 0 AND width > 0 AND height > 0", name="positive_geometry"),
        CheckConstraint(
            "text_status IN ('available','no_text','failed')", name="valid_text_status"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column()
    document_version_id: Mapped[uuid.UUID] = mapped_column()
    page_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    text_status: Mapped[str] = mapped_column(String(32))
    width: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float)
    warnings: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")


class PaperSection(Base):
    __tablename__ = "paper_sections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "document_version_id"],
            ["document_versions.owner_id", "document_versions.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "owner_id",
            "document_version_id",
            "ordinal",
            name="uq_paper_sections_owner_version_ordinal",
        ),
        UniqueConstraint(
            "owner_id", "document_version_id", "id", name="uq_paper_sections_owner_version_id"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column()
    document_version_id: Mapped[uuid.UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(64))
    heading: Mapped[str | None] = mapped_column(String(160))
    ordinal: Mapped[int] = mapped_column(Integer)
    extraction_method: Mapped[str] = mapped_column(String(64))


class SectionSpan(Base):
    __tablename__ = "section_spans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "document_version_id", "section_id"],
            ["paper_sections.owner_id", "paper_sections.document_version_id", "paper_sections.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_id", "document_version_id", "page_id"],
            ["document_pages.owner_id", "document_pages.document_version_id", "document_pages.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("start_offset >= 0 AND end_offset > start_offset", name="valid_offsets"),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    document_version_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    section_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    page_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    start_offset: Mapped[int] = mapped_column(Integer, primary_key=True)
    end_offset: Mapped[int] = mapped_column(Integer)


class PaperFigure(Base):
    __tablename__ = "paper_figures"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "paper_id", "document_version_id"],
            ["document_versions.owner_id", "document_versions.paper_id", "document_versions.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_id", "document_version_id", "page_id"],
            ["document_pages.owner_id", "document_pages.document_version_id", "document_pages.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("storage_key"),
        UniqueConstraint(
            "owner_id",
            "document_version_id",
            "ordinal",
            name="uq_paper_figures_owner_version_ordinal",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column()
    paper_id: Mapped[uuid.UUID] = mapped_column()
    document_version_id: Mapped[uuid.UUID] = mapped_column()
    page_id: Mapped[uuid.UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(36))
    caption: Mapped[str | None] = mapped_column(String(2000))
    caption_start: Mapped[int | None] = mapped_column(Integer)
    caption_end: Mapped[int | None] = mapped_column(Integer)
    caption_method: Mapped[str | None] = mapped_column(String(64))
    bounding_box: Mapped[list | None] = mapped_column(JSONB)
    extraction_method: Mapped[str] = mapped_column(String(64))


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "paper_id", "document_version_id"],
            ["document_versions.owner_id", "document_versions.paper_id", "document_versions.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_id", "paper_id", "retry_of_job_id"],
            ["processing_jobs.owner_id", "processing_jobs.paper_id", "processing_jobs.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("owner_id", "paper_id", "id", name="uq_processing_jobs_owner_paper_id"),
        CheckConstraint(
            "state IN ('queued','running','completed','partially_completed','failed')",
            name="valid_state",
        ),
        CheckConstraint(
            "progress_percent BETWEEN 0 AND 100 AND attempt >= 0", name="valid_progress"
        ),
        CheckConstraint(
            "progress_percent < 100 OR state IN ('completed','partially_completed')",
            name="terminal_progress",
        ),
        CheckConstraint(
            "state <> 'running' OR (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="running_lease",
        ),
        Index("ix_processing_jobs_dispatch", "state", "dispatch_after"),
        Index("ix_processing_jobs_lease", "state", "lease_expires_at"),
        Index(
            "uq_processing_jobs_active_fingerprint",
            "owner_id",
            "fingerprint",
            unique=True,
            postgresql_where=text("state IN ('queued','running')"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column()
    paper_id: Mapped[uuid.UUID] = mapped_column()
    document_version_id: Mapped[uuid.UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(32), default="ingestion", server_default="ingestion")
    state: Mapped[str] = mapped_column(String(32), default="queued", server_default="queued")
    stage: Mapped[str | None] = mapped_column(String(64))
    progress_percent: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    attempt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    retry_of_job_id: Mapped[uuid.UUID | None] = mapped_column()
    snapshot: Mapped[dict] = mapped_column(JSONB)
    fingerprint: Mapped[str] = mapped_column(String(64))
    dispatch_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    lease_token: Mapped[uuid.UUID | None] = mapped_column()
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
