"""system_llm"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_system_llm"
down_revision = "0006_admin"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "system_provider_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("adapter", sa.String(length=30), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("encrypted_credential", sa.Text(), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("outcome_unknown", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("execution_mode", sa.String(length=10), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "adapter IN ('gemini', 'openai_compatible', 'mock')",
            name=op.f("ck_system_provider_candidates_supported_adapter"),
        ),
        sa.CheckConstraint(
            "state IN ('testing', 'failed', 'applied', 'superseded', 'stale')",
            name=op.f("ck_system_provider_candidates_valid_state"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_system_provider_candidates_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_provider_candidates")),
    )
    op.create_index(
        op.f("ix_system_provider_candidates_created_at"),
        "system_provider_candidates",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_system_provider_candidates_created_by"),
        "system_provider_candidates",
        ["created_by"],
        unique=False,
    )
    op.create_table(
        "system_llm_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("active_candidate_id", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name=op.f("ck_system_llm_settings_singleton")),
        sa.CheckConstraint("revision > 0", name=op.f("ck_system_llm_settings_positive_revision")),
        sa.ForeignKeyConstraint(
            ["active_candidate_id"],
            ["system_provider_candidates.id"],
            name=op.f("fk_system_llm_settings_active_candidate_id_system_provider_candidates"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_llm_settings")),
    )
    op.execute(sa.text("INSERT INTO system_llm_settings (id) VALUES (1)"))


def downgrade():
    op.drop_table("system_llm_settings")
    op.drop_index(
        op.f("ix_system_provider_candidates_created_by"), table_name="system_provider_candidates"
    )
    op.drop_index(
        op.f("ix_system_provider_candidates_created_at"), table_name="system_provider_candidates"
    )
    op.drop_table("system_provider_candidates")
