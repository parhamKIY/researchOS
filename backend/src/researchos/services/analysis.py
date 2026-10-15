import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from researchos.api.errors import ApiError
from researchos.domain.models import (
    AnalysisAttempt,
    AnalysisPart,
    AnalysisReport,
    DocumentPage,
    DocumentVersion,
    IdempotencyRecord,
    SectionSpan,
    User,
)
from researchos.processing.analysis_contracts import (
    PROMPT_VERSION,
    SCHEMA_VERSION,
    SECTION_TASKS,
    document_context,
)
from researchos.services.papers import owned_paper
from researchos.services.text_gateway import resolve_text_targets


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def owned_report(db, owner, identifier, *, lock=False):
    query = select(AnalysisReport).where(
        AnalysisReport.id == identifier, AnalysisReport.owner_id == owner
    )
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise ApiError(404, "analysis_not_found", "Analysis report was not found")
    return row


def context_for(db, owner, version):
    pages = [
        {"id": str(row.id), "page_number": row.page_number, "text": row.text}
        for row in db.scalars(
            select(DocumentPage)
            .where(
                DocumentPage.owner_id == owner,
                DocumentPage.document_version_id == version,
                DocumentPage.text_status == "available",
            )
            .order_by(DocumentPage.page_number)
        )
    ]
    spans = [
        {
            "section_id": str(row.section_id),
            "page_id": str(row.page_id),
            "start": row.start_offset,
            "end": row.end_offset,
        }
        for row in db.scalars(
            select(SectionSpan)
            .where(SectionSpan.owner_id == owner, SectionSpan.document_version_id == version)
            .order_by(SectionSpan.page_id, SectionSpan.start_offset, SectionSpan.section_id)
        )
    ]
    context = document_context(pages, spans)
    if not context["chunks"]:
        raise ApiError(
            409,
            "analysis_text_unavailable",
            "This extraction has no usable text; OCR is not available",
        )
    return context


def target_snapshot(target):
    return {
        "source": target.source,
        "configuration_id": target.configuration_id,
        "model_name": target.model_name,
        "parameters": target.parameters.model_dump(exclude_none=True),
        "adapter": target.adapter_name,
        "base_url": target.base_url,
        "revision_signature": target.revision_signature,
        "execution_mode": "mock" if target.adapter_name == "mock" else "live",
    }


def analysis_plan(db, owner, paper_id, version_id, language, settings):
    paper = owned_paper(db, owner, paper_id)
    version = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.owner_id == owner,
            DocumentVersion.paper_id == paper_id,
            DocumentVersion.id == version_id,
        )
    )
    if version is None:
        raise ApiError(404, "document_not_found", "Document version was not found")
    if version.state not in {"ready", "partially_ready"}:
        raise ApiError(409, "document_not_ready", "Wait for a usable document extraction")
    context = context_for(db, owner, version.id)
    routes = {
        task: [
            target_snapshot(target) for target in resolve_text_targets(db, owner, task, settings)
        ]
        for task in set(SECTION_TASKS.values())
    }
    snapshot = {
        "document_version_id": str(version.id),
        "language": language,
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "parser_name": version.parser_name,
        "parser_version": version.parser_version,
        "context_sha256": context["sha256"],
        "coverage": context["coverage"],
        "included_chunks": context["included_chunks"],
        "total_chunks": context["total_chunks"],
        "extraction_warnings": version.warnings,
        "routes": routes,
    }
    targets = {item["configuration_id"]: item for route in routes.values() for item in route}
    return {
        "fingerprint": digest(snapshot),
        "snapshot": snapshot,
        "targets": list(targets.values()),
        "external_required": any(item["execution_mode"] == "live" for item in targets.values()),
        "external_processing_allowed": paper.external_processing_allowed,
    }


def report_read(db, report, *, detail=False):
    keys = [
        "id",
        "paper_id",
        "document_version_id",
        "retry_of_id",
        "state",
        "language",
        "progress",
        "stage",
        "error_code",
        "outcome_unknown",
        "created_at",
        "finished_at",
    ]
    result = {key: getattr(report, key) for key in keys}
    result["configuration"] = report.snapshot
    result["scientific_verification"] = "not_evaluated"
    if detail:
        result["sections"] = [
            {
                "kind": part.kind,
                "state": part.state,
                "payload": part.payload,
                "error_code": part.error_code,
            }
            for part in db.scalars(
                select(AnalysisPart).where(
                    AnalysisPart.owner_id == report.owner_id, AnalysisPart.report_id == report.id
                )
            )
        ]
        result["usage"] = [
            {
                key: getattr(row, key)
                for key in [
                    "id",
                    "section",
                    "configuration_id",
                    "model_name",
                    "execution_mode",
                    "state",
                    "error_code",
                    "input_tokens",
                    "output_tokens",
                    "thought_tokens",
                    "total_tokens",
                    "latency_ms",
                    "created_at",
                ]
            }
            for row in db.scalars(
                select(AnalysisAttempt)
                .where(
                    AnalysisAttempt.owner_id == report.owner_id,
                    AnalysisAttempt.report_id == report.id,
                )
                .order_by(AnalysisAttempt.created_at, AnalysisAttempt.id)
            )
        ]
    return result


def request_analysis(db, owner, paper_id, payload, key, settings):
    user = db.scalar(
        select(User).where(User.id == owner, User.is_active.is_(True)).with_for_update()
    )
    if user is None:
        raise ApiError(401, "unauthenticated", "Sign in to continue")
    owned_paper(db, owner, paper_id, lock=True)
    request_hash = digest({"paper": str(paper_id), **payload.model_dump(mode="json")})
    previous = db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.owner_id == owner,
            IdempotencyRecord.operation == "paper_analysis",
            IdempotencyRecord.key == key,
        )
    )
    if previous and previous.expires_at <= datetime.now(UTC):
        db.delete(previous)
        db.flush()
        previous = None
    if previous:
        if previous.request_hash != request_hash:
            raise ApiError(409, "idempotency_conflict", "Request key was used for another analysis")
        return previous.response_body
    plan = analysis_plan(
        db, owner, paper_id, payload.document_version_id, payload.language, settings
    )
    if plan["fingerprint"] != payload.plan_fingerprint:
        raise ApiError(
            412, "analysis_plan_changed", "Model settings changed; review a new analysis plan"
        )
    if set(map(str, payload.approved_configuration_ids)) != {
        row["configuration_id"] for row in plan["targets"]
    }:
        raise ApiError(
            422,
            "provider_consent_mismatch",
            "Approve exactly the model destinations shown in the plan",
        )
    if plan["external_required"] and not (
        plan["external_processing_allowed"] and payload.acknowledge_external_processing
    ):
        raise ApiError(
            403,
            "external_processing_forbidden",
            "Allow external processing for this paper and approve the shown destinations",
        )
    if payload.retry_of_id:
        old = owned_report(db, owner, payload.retry_of_id)
        if old.paper_id != paper_id or old.state not in {"failed", "partially_completed"}:
            raise ApiError(
                409, "analysis_not_retryable", "Only failed or partial analysis can be retried"
            )
        if old.outcome_unknown and not payload.acknowledge_unknown_outcome:
            raise ApiError(
                409,
                "unknown_outcome_ack_required",
                "The previous request may have incurred charges; acknowledge before a full new run",
            )
    if db.scalar(
        select(AnalysisReport.id).where(
            AnalysisReport.owner_id == owner,
            AnalysisReport.paper_id == paper_id,
            AnalysisReport.state.in_(["queued", "running"]),
        )
    ):
        raise ApiError(409, "analysis_active", "An analysis is already active for this paper")
    count = db.scalar(
        select(func.count())
        .select_from(AnalysisReport)
        .where(
            AnalysisReport.owner_id == owner,
            AnalysisReport.created_at > datetime.now(UTC) - timedelta(hours=1),
        )
    )
    if count >= 12:
        raise ApiError(
            429,
            "analysis_rate_limited",
            "Analysis limit reached; try again later",
            {"Retry-After": "3600"},
        )
    report = AnalysisReport(
        owner_id=owner,
        paper_id=paper_id,
        document_version_id=payload.document_version_id,
        language=payload.language,
        fingerprint=plan["fingerprint"],
        snapshot={
            **plan["snapshot"],
            "approved_configuration_ids": sorted(map(str, payload.approved_configuration_ids)),
            "external_approved": payload.acknowledge_external_processing,
        },
        retry_of_id=payload.retry_of_id,
    )
    db.add(report)
    db.flush()
    body = {"id": str(report.id), "state": "queued", "paper_id": str(paper_id)}
    db.add(
        IdempotencyRecord(
            owner_id=owner,
            operation="paper_analysis",
            key=key,
            request_hash=request_hash,
            response_status=202,
            response_body=body,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
    )
    db.commit()
    return body
