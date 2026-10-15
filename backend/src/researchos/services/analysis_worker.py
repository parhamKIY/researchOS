"""Durable per-section publication. Paid requests are never automatically replayed."""

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from researchos.api.errors import ApiError
from researchos.domain.models import AnalysisAttempt, AnalysisPart, AnalysisReport, User
from researchos.processing.analysis_contracts import (
    SECTION_TASKS,
    analysis_prompt,
    validate_section,
)
from researchos.providers.contracts import ProviderFailure, TextRequest
from researchos.services.analysis import analysis_plan, context_for, target_snapshot
from researchos.services.papers import owned_paper
from researchos.services.system_llm import SAFE_ERRORS
from researchos.services.text_gateway import resolve_text_targets

FALLBACK_ERRORS = {
    "provider_authentication_failed",
    "provider_access_denied",
    "model_unavailable",
    "provider_rate_limited",
    "provider_request_rejected",
    "provider_connection_failed",
}


def locked_report(db, identifier):
    root = db.execute(
        select(AnalysisReport.owner_id, AnalysisReport.paper_id).where(
            AnalysisReport.id == identifier
        )
    ).first()
    if root is None:
        return None
    db.scalar(select(User.id).where(User.id == root.owner_id).with_for_update())
    owned_paper(db, root.owner_id, root.paper_id, lock=True)
    return db.scalar(
        select(AnalysisReport)
        .where(AnalysisReport.id == identifier)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def finish_report(db, report, error=None):
    parts = list(db.scalars(select(AnalysisPart).where(AnalysisPart.report_id == report.id)))
    successful = sum(part.state in {"completed", "unavailable"} for part in parts)
    report.state = (
        "completed"
        if successful == len(SECTION_TASKS)
        else "partially_completed"
        if successful
        else "failed"
    )
    report.error_code = error or (
        "analysis_sections_failed" if report.state != "completed" else None
    )
    report.finished_at, report.progress, report.stage = datetime.now(UTC), 100, None
    report.lease_token = report.lease_expires_at = None


def valid_lease(report, token):
    return (
        report is not None
        and report.state == "running"
        and report.lease_token == token
        and report.lease_expires_at > datetime.now(UTC)
    )


async def bounded_generate(adapter, request, key):
    async with asyncio.timeout(20):
        return await adapter.generate_text(request, key)


def contains_credential(value, secret):
    if isinstance(value, str):
        return secret in value
    if isinstance(value, dict):
        return any(contains_credential(item, secret) for item in value.values())
    if isinstance(value, list):
        return any(contains_credential(item, secret) for item in value)
    return False


def prepare_attempt(db, identifier, token, section, index, settings):
    report = locked_report(db, identifier)
    if not valid_lease(report, token):
        raise ApiError(409, "analysis_lease_lost", "Analysis lease expired")
    plan = analysis_plan(
        db, report.owner_id, report.paper_id, report.document_version_id, report.language, settings
    )
    if plan["fingerprint"] != report.fingerprint:
        raise ApiError(409, "analysis_configuration_changed", "Analysis configuration changed")
    if plan["external_required"] and not (
        plan["external_processing_allowed"] and report.snapshot["external_approved"]
    ):
        raise ApiError(403, "external_processing_forbidden", "Paper privacy was changed")
    task = SECTION_TASKS[section]
    targets = resolve_text_targets(db, report.owner_id, task, settings)
    target = targets[index]
    if target_snapshot(target) != report.snapshot["routes"][task][index]:
        raise ApiError(409, "analysis_configuration_changed", "Analysis configuration changed")
    context = context_for(db, report.owner_id, report.document_version_id)
    parameters = target.parameters.model_copy()
    parameters.max_output_tokens = parameters.max_output_tokens or 4096
    request = TextRequest(
        model_name=target.model_name,
        prompt=analysis_prompt(section, report.language, context),
        parameters=parameters,
    )
    report.stage = section
    report.lease_expires_at = datetime.now(UTC) + timedelta(seconds=settings.job_lease_seconds)
    attempt = AnalysisAttempt(
        owner_id=report.owner_id,
        report_id=report.id,
        section=section,
        configuration_id=uuid.UUID(target.configuration_id),
        model_name=target.model_name,
        execution_mode="mock" if target.adapter_name == "mock" else "live",
    )
    db.add(attempt)
    db.flush()
    attempt_id = attempt.id
    db.commit()
    return target, request, context, attempt_id


def execute_analysis(identifier, settings, session_factory, *, adapter_override=None):
    token = uuid.uuid4()
    with session_factory() as db:
        report = locked_report(db, identifier)
        if report is None or report.state != "queued":
            return {"status": "ignored"}
        report.state, report.lease_token = "running", token
        report.lease_expires_at = datetime.now(UTC) + timedelta(seconds=settings.job_lease_seconds)
        db.commit()
    for section in SECTION_TASKS:
        payload, code, unknown = None, None, False
        stop = False
        for index in range(2):
            with session_factory() as db:
                report = locked_report(db, identifier)
                if not valid_lease(report, token):
                    return {"status": "ignored"}
                if index >= len(report.snapshot["routes"][SECTION_TASKS[section]]):
                    break
                try:
                    target, request, context, attempt_id = prepare_attempt(
                        db, identifier, token, section, index, settings
                    )
                except (ApiError, ValueError) as exc:
                    code = exc.code if isinstance(exc, ApiError) else "analysis_input_invalid"
                    stop = True
                    break
            result, code, unknown = None, None, False
            started = time.monotonic()
            try:
                adapter = (
                    adapter_override(target, section, index) if adapter_override else target.adapter
                )
                result = asyncio.run(bounded_generate(adapter, request, target.key))
                if result.execution_mode != ("mock" if target.adapter_name == "mock" else "live"):
                    raise ValueError("Execution mode mismatch")
                payload = validate_section(result.text, section, context)
                if target.key and contains_credential(payload, target.key.get_secret_value()):
                    payload = None
                    raise ValueError("Sensitive provider output rejected")
                payload["generation"] = {
                    "execution_mode": result.execution_mode,
                    "configuration_id": target.configuration_id,
                    "model_name": target.model_name,
                    "attempt_id": str(attempt_id),
                }
            except ProviderFailure as exc:
                code = exc.code if exc.code in SAFE_ERRORS else "provider_unavailable"
                unknown = exc.outcome_unknown
            except ValueError:
                code = "analysis_output_invalid"
            except Exception:
                code, unknown = "provider_outcome_unknown", True
            with session_factory() as db:
                report = locked_report(db, identifier)
                if not valid_lease(report, token):
                    return {"status": "ignored"}
                attempt = db.get(AnalysisAttempt, attempt_id)
                attempt.latency_ms = int((time.monotonic() - started) * 1000)
                attempt.state = "outcome_unknown" if unknown else "failed" if code else "completed"
                attempt.error_code = code
                if result:
                    for field in [
                        "input_tokens",
                        "output_tokens",
                        "thought_tokens",
                        "total_tokens",
                    ]:
                        setattr(attempt, field, getattr(result.usage, field))
                report.outcome_unknown = report.outcome_unknown or unknown
                # Revalidate configuration/privacy before publishing the response as a report.
                if payload is not None:
                    try:
                        current = analysis_plan(
                            db,
                            report.owner_id,
                            report.paper_id,
                            report.document_version_id,
                            report.language,
                            settings,
                        )
                        if current["fingerprint"] != report.fingerprint or (
                            current["external_required"]
                            and not current["external_processing_allowed"]
                        ):
                            raise ApiError(
                                409, "analysis_configuration_changed", "Settings changed"
                            )
                    except ApiError as exc:
                        payload, code = None, exc.code
                db.commit()
            if payload is not None or unknown or code not in FALLBACK_ERRORS:
                break
        with session_factory() as db:
            report = locked_report(db, identifier)
            if not valid_lease(report, token):
                return {"status": "ignored"}
            db.add(
                AnalysisPart(
                    owner_id=report.owner_id,
                    report_id=identifier,
                    kind=section,
                    state="completed"
                    if payload and payload["items"]
                    else "unavailable"
                    if payload
                    else "failed",
                    payload=payload,
                    error_code=code,
                )
            )
            report.progress = int(
                100 * (list(SECTION_TASKS).index(section) + 1) / len(SECTION_TASKS)
            )
            if (
                stop
                or unknown
                or code
                in {
                    "analysis_configuration_changed",
                    "external_processing_forbidden",
                    "unauthenticated",
                    "model_unusable",
                    "analysis_lease_lost",
                }
            ):
                db.flush()
                finish_report(db, report, code)
                db.commit()
                return {"status": report.state}
            db.commit()
    with session_factory() as db:
        report = locked_report(db, identifier)
        if not valid_lease(report, token):
            return {"status": "ignored"}
        finish_report(db, report)
        db.commit()
        return {"status": report.state}


def recover_analyses(db):
    now = datetime.now(UTC)
    identifiers = list(
        db.scalars(
            select(AnalysisReport.id)
            .where(AnalysisReport.state == "running", AnalysisReport.lease_expires_at <= now)
            .limit(20)
        )
    )
    for identifier in identifiers:
        report = locked_report(db, identifier)
        if report is None or report.state != "running" or report.lease_expires_at > now:
            db.rollback()
            continue
        for attempt in db.scalars(
            select(AnalysisAttempt).where(
                AnalysisAttempt.report_id == identifier, AnalysisAttempt.state == "started"
            )
        ):
            attempt.state, attempt.error_code = "outcome_unknown", "worker_interrupted"
            report.outcome_unknown = True
        finish_report(db, report, "worker_interrupted")
        db.commit()
    return len(identifiers)


def dispatch_analyses(db, publisher):
    now = datetime.now(UTC)
    reports = list(
        db.scalars(
            select(AnalysisReport)
            .where(AnalysisReport.state == "queued", AnalysisReport.dispatch_after <= now)
            .order_by(AnalysisReport.created_at)
            .limit(20)
            .with_for_update(skip_locked=True)
        )
    )
    sent = 0
    for report in reports:
        try:
            publisher.send_task(
                "researchos.analysis.run", args=[str(report.id)], ignore_result=True, retry=False
            )
        except Exception:
            report.dispatch_after = now + timedelta(seconds=10)
            break
        report.dispatch_after = now + timedelta(seconds=60)
        sent += 1
    db.commit()
    return sent
