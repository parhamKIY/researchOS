import os
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_auth import account_client as account_client

from researchos.domain.models import (
    AIUsageRecord,
    ModelConfiguration,
    ModelRoutingRule,
    ModelRoutingSettings,
    ProviderConnection,
    User,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RESEARCHOS_RUN_INTEGRATION") != "1", reason="Live PG required"),
]


@pytest.mark.parametrize(
    "case", ["foreign_model_owner", "foreign_route_model", "wrong_usage_provider"]
)
def test_database_rejects_cross_owner_provider_and_model_links(account_client, case):
    _, connection = account_client
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        owner = db.scalar(select(User.id).where(User.email_normalized == "account@example.invalid"))
        provider = ProviderConnection(
            owner_id=owner, adapter="mock", display_name="Explicit schema fixture"
        )
        other_provider = ProviderConnection(
            owner_id=owner, adapter="mock", display_name="Other fixture"
        )
        db.add_all([provider, other_provider])
        db.flush()
        model = ModelConfiguration(
            owner_id=owner, provider_id=provider.id, model_name="fixture", capabilities=["text"]
        )
        db.add(model)
        db.flush()
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                if case == "foreign_model_owner":
                    db.add(
                        ModelConfiguration(
                            owner_id=uuid.uuid4(),
                            provider_id=provider.id,
                            model_name="foreign",
                            capabilities=["text"],
                        )
                    )
                elif case == "foreign_route_model":
                    db.add(ModelRoutingSettings(owner_id=owner))
                    db.flush()
                    db.add(
                        ModelRoutingRule(
                            owner_id=owner,
                            task="paper_summary",
                            primary_model_id=uuid.uuid4(),
                            allowed_provider_ids=[str(provider.id)],
                        )
                    )
                else:
                    db.add(
                        AIUsageRecord(
                            owner_id=owner,
                            provider_id=other_provider.id,
                            model_configuration_id=model.id,
                            provider_name="fixture",
                            model_name="fixture",
                            task="connection_test",
                            attempt=1,
                            execution_mode="mock",
                            state="started",
                        )
                    )
                db.flush()
