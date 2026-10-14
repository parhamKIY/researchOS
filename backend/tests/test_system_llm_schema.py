import os
import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_auth import account_client as account_client

from researchos.domain.models import SystemLLMSettings, SystemProviderCandidate

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RESEARCHOS_RUN_INTEGRATION") != "1", reason="Live PG required"),
]


def test_singleton_default_is_unconfigured_and_fk_requires_existing_candidate(account_client):
    _, connection = account_client
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        settings = db.get(SystemLLMSettings, 1)
        assert settings is not None and settings.revision >= 1
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(SystemLLMSettings(id=2))
            db.flush()
        with pytest.raises(IntegrityError), db.begin_nested():
            settings.active_candidate_id = uuid.uuid4()
            db.flush()


def test_invalid_candidate_state_is_rejected(account_client):
    _, connection = account_client
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(
                SystemProviderCandidate(
                    adapter="mock", model_name="fixture", execution_mode="mock", state="invented"
                )
            )
            db.flush()
