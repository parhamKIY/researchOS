import os
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_auth import PASSWORD
from test_auth import account_client as account_client

from researchos.cli import provision_user
from researchos.domain.models import Paper, PaperFile, PaperProject, Project, User

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RESEARCHOS_RUN_INTEGRATION") != "1", reason="Live PG required"),
]


@pytest.mark.parametrize("case", ["foreign_file", "foreign_membership", "duplicate_hash"])
def test_library_constraints_reject_cross_owner_relations_and_duplicates(account_client, case):
    _, connection = account_client
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        owner = db.scalar(select(User.id))
        other = provision_user(db, "schema-other@example.invalid", PASSWORD)
        paper = Paper(owner_id=owner)
        project = Project(owner_id=other.id, name="Other user's project")
        db.add_all([paper, project])
        db.flush()
        with pytest.raises(IntegrityError), db.begin_nested():
            if case == "foreign_membership":
                db.add(PaperProject(owner_id=owner, paper_id=paper.id, project_id=project.id))
            elif case == "foreign_file":
                db.add(
                    PaperFile(
                        owner_id=other.id,
                        paper_id=paper.id,
                        sha256="a" * 64,
                        storage_key=f"{uuid.uuid4().hex}.pdf",
                        original_name="fixture.pdf",
                        byte_size=10,
                    )
                )
            else:
                second = Paper(owner_id=owner)
                db.add(second)
                db.flush()
                for resource in [paper, second]:
                    db.add(
                        PaperFile(
                            owner_id=owner,
                            paper_id=resource.id,
                            sha256="a" * 64,
                            storage_key=f"{uuid.uuid4().hex}.pdf",
                            original_name="fixture.pdf",
                            byte_size=10,
                        )
                    )
            db.flush()
