"""provider_management"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_providers"
down_revision = "0004_ingestion"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "model_routing_settings",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_model_routing_settings_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("owner_id", name=op.f("pk_model_routing_settings")),
    )
    op.create_table(
        "provider_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("adapter", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("encrypted_credential", sa.Text(), nullable=True),
        sa.Column("credential_revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "adapter IN ('gemini','mock')", name=op.f("ck_provider_connections_valid_adapter")
        ),
        sa.CheckConstraint(
            "length(trim(display_name)) > 0", name=op.f("ck_provider_connections_nonempty_name")
        ),
        sa.CheckConstraint(
            "revision > 0 AND credential_revision > 0",
            name=op.f("ck_provider_connections_positive_revisions"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_provider_connections_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_connections")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_provider_connections_owner_id")),
    )
    op.create_index(
        op.f("ix_provider_connections_owner_id"), "provider_connections", ["owner_id"], unique=False
    )
    op.create_table(
        "model_configurations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "capability_source", sa.String(length=32), server_default="manual", nullable=False
        ),
        sa.Column(
            "parameters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "capability_source = 'manual'", name=op.f("ck_model_configurations_manual_capabilities")
        ),
        sa.CheckConstraint("revision > 0", name=op.f("ck_model_configurations_positive_revision")),
        sa.ForeignKeyConstraint(
            ["owner_id", "provider_id"],
            ["provider_connections.owner_id", "provider_connections.id"],
            name=op.f("fk_model_configurations_owner_id_provider_connections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_configurations")),
        sa.UniqueConstraint("owner_id", "id", name=op.f("uq_model_configurations_owner_id")),
        sa.UniqueConstraint(
            "owner_id", "provider_id", "id", name="uq_model_configurations_owner_provider_id"
        ),
        sa.UniqueConstraint(
            "owner_id",
            "provider_id",
            "model_name",
            name="uq_model_configurations_owner_provider_name",
        ),
    )
    op.create_table(
        "ai_usage_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("model_configuration_id", sa.Uuid(), nullable=False),
        sa.Column("provider_name", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("task", sa.String(length=64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("thought_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cost_amount", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("cost_source", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('started','completed','failed','outcome_unknown')",
            name=op.f("ck_ai_usage_records_valid_state"),
        ),
        sa.CheckConstraint("attempt > 0", name=op.f("ck_ai_usage_records_positive_attempt")),
        sa.ForeignKeyConstraint(
            ["owner_id", "provider_id", "model_configuration_id"],
            [
                "model_configurations.owner_id",
                "model_configurations.provider_id",
                "model_configurations.id",
            ],
            name=op.f("fk_ai_usage_records_owner_id_model_configurations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_usage_records")),
    )
    op.create_table(
        "model_routing_rules",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("task", sa.String(length=64), nullable=False),
        sa.Column("primary_model_id", sa.Uuid(), nullable=False),
        sa.Column("fallback_model_id", sa.Uuid(), nullable=True),
        sa.Column("allowed_provider_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "fallback_model_id IS NULL OR fallback_model_id <> primary_model_id",
            name=op.f("ck_model_routing_rules_distinct_fallback"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "fallback_model_id"],
            ["model_configurations.owner_id", "model_configurations.id"],
            name="fk_routing_fallback_model",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "primary_model_id"],
            ["model_configurations.owner_id", "model_configurations.id"],
            name="fk_routing_primary_model",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["model_routing_settings.owner_id"],
            name=op.f("fk_model_routing_rules_owner_id_model_routing_settings"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("owner_id", "task", name=op.f("pk_model_routing_rules")),
    )


def downgrade():
    op.drop_table("model_routing_rules")
    op.drop_table("ai_usage_records")
    op.drop_table("model_configurations")
    op.drop_index(op.f("ix_provider_connections_owner_id"), table_name="provider_connections")
    op.drop_table("provider_connections")
    op.drop_table("model_routing_settings")
