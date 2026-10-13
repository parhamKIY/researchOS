from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from researchos.domain.models import (
    DocumentPage,
    DocumentVersion,
    PaperFigure,
    PaperSection,
    SectionSpan,
)
from researchos.infrastructure.storage import LocalFileStore
from researchos.processing.contracts import ParsedDocument, ParseFailure, ParseLimits
from researchos.services.ingestion import JobLease, locked_job, owns_lease


def publish_document(
    db: Session, lease: JobLease, parsed: ParsedDocument, work: Path, store: LocalFileStore
) -> bool:
    job = locked_job(db, lease.id)
    if not owns_lease(job, lease):
        db.rollback()
        return False
    if (parsed.parser_name, parsed.parser_version) != (
        lease.snapshot["name"],
        lease.snapshot["version"],
    ):
        raise ParseFailure("parser_version_unavailable")
    limits = ParseLimits.model_validate(lease.snapshot["config"]["limits"])
    numbers = [page.page_number for page in parsed.pages]
    if numbers != list(range(1, len(parsed.pages) + 1)) or len(numbers) > limits.max_pages:
        raise ParseFailure("invalid_parser_result")
    if (
        sum(len(page.text) for page in parsed.pages) > limits.max_characters
        or len(parsed.figures) > limits.max_figures
    ):
        raise ParseFailure("invalid_parser_result")
    pages = {}
    copied = []
    committed = False
    try:
        job.stage = "persisting_results"
        job.progress_percent = 95
        for source in parsed.pages:
            page = DocumentPage(
                owner_id=lease.owner_id,
                document_version_id=lease.version_id,
                page_number=source.page_number,
                text=source.text,
                text_status=source.text_status,
                width=source.width,
                height=source.height,
                warnings=source.warnings,
            )
            db.add(page)
            pages[source.page_number] = page
        db.flush()
        for source in parsed.sections:
            section = PaperSection(
                owner_id=lease.owner_id,
                document_version_id=lease.version_id,
                kind=source.kind,
                heading=source.heading,
                ordinal=source.ordinal,
                extraction_method=source.extraction_method,
            )
            db.add(section)
            db.flush()
            for span in source.spans:
                page = pages.get(span.page_number)
                if page is None or not 0 <= span.start_offset < span.end_offset <= len(page.text):
                    raise ParseFailure("invalid_parser_result")
                db.add(
                    SectionSpan(
                        owner_id=lease.owner_id,
                        document_version_id=lease.version_id,
                        section_id=section.id,
                        page_id=page.id,
                        start_offset=span.start_offset,
                        end_offset=span.end_offset,
                    )
                )
        for source in parsed.figures:
            page = pages.get(source.page_number)
            image = work / source.filename
            if page is None or image.resolve().parent != work.resolve() or image.is_symlink():
                raise ParseFailure("invalid_parser_result")
            if source.caption is not None:
                if (
                    source.caption_start is None
                    or source.caption_end is None
                    or not 0 <= source.caption_start < source.caption_end <= len(page.text)
                ):
                    raise ParseFailure("invalid_parser_result")
                if page.text[source.caption_start : source.caption_end].strip() != source.caption:
                    raise ParseFailure("invalid_parser_result")
            key = store.persist_image(image)
            copied.append(key)
            db.add(
                PaperFigure(
                    owner_id=lease.owner_id,
                    paper_id=lease.paper_id,
                    document_version_id=lease.version_id,
                    page_id=page.id,
                    ordinal=source.ordinal,
                    storage_key=key,
                    caption=source.caption,
                    caption_start=source.caption_start,
                    caption_end=source.caption_end,
                    caption_method=source.caption_method,
                    bounding_box=source.bounding_box,
                    extraction_method=source.extraction_method,
                )
            )
        now = datetime.now(UTC)
        version = db.get(DocumentVersion, lease.version_id)
        version.state = parsed.state
        version.metadata_json = parsed.metadata
        version.warnings = parsed.warnings
        version.completed_at = now
        job.state = "completed" if parsed.state == "ready" else "partially_completed"
        job.stage = None
        job.progress_percent = 100
        job.finished_at = now
        job.lease_token = job.lease_expires_at = None
        db.commit()
        committed = True
        return True
    finally:
        if not committed:
            db.rollback()
            for key in copied:
                try:
                    store.delete(key)
                except OSError:
                    pass
