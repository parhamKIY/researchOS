import os
import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_auth import account_client as account_client

from researchos.domain.models import AnalysisPart, AnalysisReport

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RESEARCHOS_RUN_INTEGRATION") != "1", reason="Live PG required"),
]


def test_report_and_section_foreign_keys_cannot_cross_ownership(account_client):
    _, connection = account_client
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(
                AnalysisReport(
                    owner_id=uuid.uuid4(),
                    paper_id=uuid.uuid4(),
                    document_version_id=uuid.uuid4(),
                    language="fa",
                    fingerprint="0" * 64,
                    snapshot={},
                )
            )
            db.flush()
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(
                AnalysisPart(
                    owner_id=uuid.uuid4(),
                    report_id=uuid.uuid4(),
                    kind="overview",
                    state="completed",
                    payload={},
                )
            )
            db.flush()
