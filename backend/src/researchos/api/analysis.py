import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import Field, StrictBool
from sqlalchemy import select

from researchos.api.dependencies import Authenticated, Database, Mutation
from researchos.api.jobs import UploadKey
from researchos.api.providers import page_rows
from researchos.domain.models import AnalysisReport
from researchos.processing.analysis_contracts import StrictModel
from researchos.services.analysis import analysis_plan, owned_report, report_read, request_analysis
from researchos.services.papers import owned_paper

router = APIRouter(prefix="/api/v1", tags=["Paper analysis"])


class AnalysisRequest(StrictModel):
    document_version_id: uuid.UUID
    language: Literal["fa", "en"]
    plan_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    approved_configuration_ids: list[uuid.UUID] = Field(min_length=1, max_length=6)
    acknowledge_external_processing: StrictBool = False
    retry_of_id: uuid.UUID | None = None
    acknowledge_unknown_outcome: StrictBool = False


@router.get("/papers/{paper_id}/analysis-plan")
def plan(
    paper_id: uuid.UUID,
    document_version_id: uuid.UUID,
    db: Database,
    identity: Authenticated,
    request: Request,
    language: Literal["fa", "en"] = "en",
):
    return analysis_plan(
        db, identity.user.id, paper_id, document_version_id, language, request.app.state.settings
    )


@router.post("/papers/{paper_id}/analyses", status_code=202)
def start(
    paper_id: uuid.UUID,
    payload: AnalysisRequest,
    db: Database,
    identity: Mutation,
    request: Request,
    response: Response,
    idempotency_key: UploadKey,
):
    body = request_analysis(
        db, identity.user.id, paper_id, payload, idempotency_key, request.app.state.settings
    )
    response.headers["Location"] = f"/api/v1/analyses/{body['id']}"
    return body


@router.get("/papers/{paper_id}/analyses")
def history(
    paper_id: uuid.UUID,
    db: Database,
    identity: Authenticated,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
):
    owned_paper(db, identity.user.id, paper_id)
    rows, next_cursor = page_rows(
        request,
        db,
        identity.user.id,
        AnalysisReport,
        select(AnalysisReport).where(
            AnalysisReport.owner_id == identity.user.id, AnalysisReport.paper_id == paper_id
        ),
        "analyses",
        {"paper_id": str(paper_id)},
        limit,
        cursor,
    )
    return {"items": [report_read(db, row) for row in rows], "next_cursor": next_cursor}


@router.get("/analyses/{report_id}")
def read(report_id: uuid.UUID, db: Database, identity: Authenticated):
    return report_read(db, owned_report(db, identity.user.id, report_id), detail=True)
