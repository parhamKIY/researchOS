import os
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_auth import account_client as account_client

from researchos.domain.models import (
    DocumentPage,
    DocumentVersion,
    Paper,
    PaperFile,
    PaperSection,
    ProcessingJob,
    SectionSpan,
    User,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RESEARCHOS_RUN_INTEGRATION") != "1", reason="Live PG required"),
]


def source_versions(db):
    owner = db.scalar(select(User.id).where(User.email_normalized == "account@example.invalid"))
    paper = Paper(owner_id=owner)
    db.add(paper)
    db.flush()
    file = PaperFile(
        owner_id=owner,
        paper_id=paper.id,
        sha256="a" * 64,
        storage_key=f"{uuid.uuid4().hex}.pdf",
        original_name="fixture.pdf",
        byte_size=1,
    )
    db.add(file)
    db.flush()
    versions = [
        DocumentVersion(
            owner_id=owner,
            paper_id=paper.id,
            file_id=file.id,
            parser_name="schema_fixture",
            parser_version="fixture",
            parser_config={},
        )
        for _ in range(2)
    ]
    db.add_all(versions)
    db.flush()
    return owner, paper, versions


@pytest.mark.parametrize(
    "case",
    [
        "foreign_page",
        "wrong_version_span",
        "duplicate_page",
        "duplicate_active_job",
        "invalid_progress",
    ],
)
def test_ingestion_relations_and_active_job_constraints(account_client, case):
    _, connection = account_client
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        owner, paper, versions = source_versions(db)
        page = DocumentPage(
            owner_id=owner,
            document_version_id=versions[0].id,
            page_number=1,
            text="Fixture text",
            text_status="available",
            width=100,
            height=100,
        )
        section = PaperSection(
            owner_id=owner,
            document_version_id=versions[1].id,
            kind="unclassified",
            heading=None,
            ordinal=0,
            extraction_method="fixture",
        )
        db.add_all([page, section])
        db.flush()
        with pytest.raises(IntegrityError), db.begin_nested():
            if case == "wrong_version_span":
                db.add(
                    SectionSpan(
                        owner_id=owner,
                        document_version_id=versions[1].id,
                        section_id=section.id,
                        page_id=page.id,
                        start_offset=0,
                        end_offset=4,
                    )
                )
            elif case in {"foreign_page", "duplicate_page"}:
                db.add(
                    DocumentPage(
                        owner_id=uuid.uuid4() if case == "foreign_page" else owner,
                        document_version_id=versions[0].id,
                        page_number=1,
                        text="Fixture",
                        text_status="available",
                        width=100,
                        height=100,
                    )
                )
            else:
                for version in versions[: 2 if case == "duplicate_active_job" else 1]:
                    db.add(
                        ProcessingJob(
                            owner_id=owner,
                            paper_id=paper.id,
                            document_version_id=version.id,
                            fingerprint="b" * 64,
                            snapshot={},
                            progress_percent=100 if case == "invalid_progress" else 0,
                        )
                    )
            db.flush()
