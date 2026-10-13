import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from researchos.api.dependencies import Authenticated, Database
from researchos.api.errors import ApiError
from researchos.domain.models import (
    DocumentPage,
    DocumentVersion,
    PaperFigure,
    PaperSection,
    SectionSpan,
)
from researchos.infrastructure.storage import LocalFileStore
from researchos.services.papers import owned_paper
from researchos.services.resources import cursor_filter, cursor_scope, encode_cursor

router = APIRouter(prefix="/api/v1", tags=["Document extraction"])


def owned_version(db, owner_id, version_id, paper_id=None):
    query = select(DocumentVersion).where(
        DocumentVersion.id == version_id, DocumentVersion.owner_id == owner_id
    )
    if paper_id is not None:
        query = query.where(DocumentVersion.paper_id == paper_id)
    version = db.scalar(query)
    if version is None:
        raise ApiError(404, "document_not_found", "Document version was not found")
    return version


def version_read(db, version):
    counts = {}
    for key, model in [("page_count", DocumentPage), ("figure_count", PaperFigure)]:
        counts[key] = db.scalar(
            select(func.count())
            .select_from(model)
            .where(model.owner_id == version.owner_id, model.document_version_id == version.id)
        )
    return {
        "id": version.id,
        "paper_id": version.paper_id,
        "state": version.state,
        "parser_name": version.parser_name,
        "parser_version": version.parser_version,
        "parser_config": version.parser_config,
        "metadata": version.metadata_json,
        "warnings": version.warnings,
        "created_at": version.created_at,
        **counts,
    }


@router.get("/papers/{paper_id}/document-versions")
def versions(
    paper_id: uuid.UUID,
    request: Request,
    db: Database,
    identity: Authenticated,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
):
    owned_paper(db, identity.user.id, paper_id)
    query = select(DocumentVersion).where(
        DocumentVersion.owner_id == identity.user.id, DocumentVersion.paper_id == paper_id
    )
    scope = cursor_scope(
        identity.user.id, "document_versions", {"paper_id": str(paper_id), "limit": limit}
    )
    secret = request.app.state.settings.session_secret.get_secret_value()
    if cursor:
        query = query.where(cursor_filter(DocumentVersion, cursor, scope, secret))
    rows = list(
        db.scalars(
            query.order_by(DocumentVersion.created_at.desc(), DocumentVersion.id.desc()).limit(
                limit + 1
            )
        )
    )
    return {
        "items": [version_read(db, row) for row in rows[:limit]],
        "next_cursor": encode_cursor(rows[limit - 1], scope, secret) if len(rows) > limit else None,
    }


@router.get("/document-versions/{version_id}")
def version(version_id: uuid.UUID, db: Database, identity: Authenticated):
    return version_read(db, owned_version(db, identity.user.id, version_id))


@router.get("/document-versions/{version_id}/pages/{page_number}")
def page(version_id: uuid.UUID, page_number: int, db: Database, identity: Authenticated):
    owned_version(db, identity.user.id, version_id)
    row = db.scalar(
        select(DocumentPage).where(
            DocumentPage.owner_id == identity.user.id,
            DocumentPage.document_version_id == version_id,
            DocumentPage.page_number == page_number,
        )
    )
    if row is None:
        raise ApiError(404, "page_not_found", "Extracted page was not found")
    return {
        key: getattr(row, key)
        for key in [
            "id",
            "document_version_id",
            "page_number",
            "text",
            "text_status",
            "width",
            "height",
            "warnings",
        ]
    }


@router.get("/document-versions/{version_id}/sections")
def sections(version_id: uuid.UUID, db: Database, identity: Authenticated):
    owned_version(db, identity.user.id, version_id)
    rows = list(
        db.scalars(
            select(PaperSection)
            .where(
                PaperSection.owner_id == identity.user.id,
                PaperSection.document_version_id == version_id,
            )
            .order_by(PaperSection.ordinal)
        )
    )
    spans = db.execute(
        select(SectionSpan, DocumentPage.page_number)
        .join(DocumentPage, DocumentPage.id == SectionSpan.page_id)
        .where(
            SectionSpan.owner_id == identity.user.id, SectionSpan.document_version_id == version_id
        )
        .order_by(DocumentPage.page_number, SectionSpan.start_offset)
    ).all()
    grouped = {}
    for span, number in spans:
        grouped.setdefault(span.section_id, []).append(
            {
                "page_id": span.page_id,
                "page_number": number,
                "start_offset": span.start_offset,
                "end_offset": span.end_offset,
            }
        )
    return {
        "items": [
            {
                "id": row.id,
                "kind": row.kind,
                "heading": row.heading,
                "ordinal": row.ordinal,
                "extraction_method": row.extraction_method,
                "spans": grouped.get(row.id, []),
            }
            for row in rows
        ]
    }


@router.get("/papers/{paper_id}/figures")
def figures(
    paper_id: uuid.UUID,
    document_version_id: uuid.UUID,
    db: Database,
    identity: Authenticated,
    offset: Annotated[int, Query(ge=0, le=200)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    owned_version(db, identity.user.id, document_version_id, paper_id)
    rows = db.execute(
        select(PaperFigure, DocumentPage.page_number)
        .join(DocumentPage, DocumentPage.id == PaperFigure.page_id)
        .where(
            PaperFigure.owner_id == identity.user.id,
            PaperFigure.document_version_id == document_version_id,
        )
        .order_by(PaperFigure.ordinal)
        .offset(offset)
        .limit(limit + 1)
    ).all()
    return {
        "items": [
            {
                **{
                    key: getattr(row, key)
                    for key in [
                        "id",
                        "document_version_id",
                        "page_id",
                        "ordinal",
                        "caption",
                        "caption_start",
                        "caption_end",
                        "caption_method",
                        "bounding_box",
                        "extraction_method",
                    ]
                },
                "page_number": number,
                "file_url": f"/api/v1/figures/{row.id}/file",
            }
            for row, number in rows[:limit]
        ],
        "next_offset": offset + limit if len(rows) > limit else None,
    }


@router.get("/figures/{figure_id}/file", response_class=FileResponse)
def figure_file(figure_id: uuid.UUID, request: Request, db: Database, identity: Authenticated):
    row = db.scalar(
        select(PaperFigure).where(
            PaperFigure.id == figure_id, PaperFigure.owner_id == identity.user.id
        )
    )
    if row is None:
        raise ApiError(404, "figure_not_found", "Extracted figure was not found")
    path = LocalFileStore(request.app.state.settings.storage_root).path(row.storage_key)
    if not path.is_file():
        raise ApiError(503, "figure_unavailable", "Extracted figure is temporarily unavailable")
    return FileResponse(
        path, media_type="image/png", headers={"Cache-Control": "private, no-store"}
    )
