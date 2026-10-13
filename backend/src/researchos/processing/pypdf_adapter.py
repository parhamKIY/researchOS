import importlib.metadata
import re
import unicodedata
import warnings as python_warnings
from pathlib import Path

import pdfplumber
from PIL import Image
from pypdf import PdfReader

from researchos.processing.contracts import (
    ExtractedFigure,
    ExtractedPage,
    ParsedDocument,
    ParseFailure,
    ParseLimits,
)
from researchos.processing.structure import doi_candidates, sections_from_pages

PARSER_NAME = "pypdf_raster_v1"


def parser_version() -> str:
    return ";".join(
        f"{name}={importlib.metadata.version(name)}" for name in ["pypdf", "pdfplumber", "pillow"]
    )


class PypdfParser:
    def parse(self, path: Path, output: Path, limits: ParseLimits, progress) -> ParsedDocument:
        Image.MAX_IMAGE_PIXELS = limits.max_image_pixels
        python_warnings.filterwarnings("error", category=Image.DecompressionBombWarning)
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted:
            raise ParseFailure("password_protected")
        count = len(reader.pages)
        if not count:
            raise ParseFailure("no_pages")
        if count > limits.max_pages:
            raise ParseFailure("page_limit_exceeded")
        output.mkdir(parents=True, exist_ok=True)
        pages = []
        figures = []
        warnings = [
            "reading_order_unverified",
            "vector_figures_not_extracted",
            "tables_not_structured",
        ]
        consumed = 0
        with pdfplumber.open(path) as layout:
            for index, source in enumerate(reader.pages):
                page_warnings = []
                text_status = "available"
                try:
                    text = unicodedata.normalize(
                        "NFC",
                        (source.extract_text() or "").replace("\x00", "").replace("\r\n", "\n"),
                    )
                    if not text.strip():
                        text_status = "no_text"
                        page_warnings.append("no_text_layer_ocr_unavailable")
                    if len(text) > 500_000 or consumed + len(text) > limits.max_characters:
                        raise ParseFailure("text_limit_exceeded")
                    consumed += len(text)
                except ParseFailure:
                    raise
                except Exception:
                    text = ""
                    text_status = "failed"
                    page_warnings.append("page_text_extraction_failed")
                width, height = float(source.mediabox.width), float(source.mediabox.height)
                boxes = {}
                try:
                    positioned = layout.pages[index]
                    width, height = float(positioned.width), float(positioned.height)
                    boxes = {
                        item["stream"].objid: [item["x0"], item["top"], item["x1"], item["bottom"]]
                        for item in positioned.images
                    }
                    positioned.close()
                except Exception:
                    page_warnings.append("image_positions_unavailable")
                try:
                    keys = list(source.images.keys())
                except Exception:
                    keys = []
                    page_warnings.append("image_extraction_failed")
                captions = list(
                    re.finditer(r"(?im)^\s*(?:Figure|Fig\.)\s+\d+[.:]?[^\n]{0,1500}", text)
                )
                for image_key in keys:
                    if len(figures) >= limits.max_figures:
                        page_warnings.append("image_limit_reached")
                        break
                    try:
                        extracted = source.images[image_key]
                        image = extracted.image
                        if image.width * image.height > limits.max_image_pixels:
                            page_warnings.append("image_pixel_limit_exceeded")
                            continue
                        ordinal = len(figures)
                        filename = f"figure-{ordinal}.png"
                        image.save(output / filename, format="PNG")
                        if (output / filename).stat().st_size > 10 * 1024 * 1024:
                            (output / filename).unlink()
                            page_warnings.append("image_size_limit_exceeded")
                            continue
                        caption = captions[0] if len(keys) == len(captions) == 1 else None
                        reference = extracted.indirect_reference
                        figures.append(
                            ExtractedFigure(
                                ordinal=ordinal,
                                filename=filename,
                                page_number=index + 1,
                                bounding_box=boxes.get(reference.idnum) if reference else None,
                                caption=caption[0].strip() if caption else None,
                                caption_start=caption.start() if caption else None,
                                caption_end=caption.end() if caption else None,
                                caption_method="single_image_single_caption_candidate"
                                if caption
                                else None,
                            )
                        )
                    except Exception:
                        page_warnings.append("image_extraction_failed")
                pages.append(
                    ExtractedPage(
                        page_number=index + 1,
                        text=text,
                        text_status=text_status,
                        width=width,
                        height=height,
                        warnings=sorted(set(page_warnings)),
                    )
                )
                progress(index + 1, count)
        info = reader.metadata or {}
        metadata = {
            name: str(info[key])[:2000] if info.get(key) else None
            for name, key in {
                "title": "/Title",
                "author_text": "/Author",
                "subject": "/Subject",
                "keywords": "/Keywords",
            }.items()
        }
        metadata.update(source="pdf_info_unverified", doi_candidates=doi_candidates(pages))
        warnings.extend(code for page in pages for code in page.warnings)
        incomplete = any(page.text_status != "available" or page.warnings for page in pages)
        if not any(page.text.strip() for page in pages):
            warnings.append("no_usable_text")
        return ParsedDocument(
            parser_name=PARSER_NAME,
            parser_version=parser_version(),
            metadata=metadata,
            pages=pages,
            figures=figures,
            sections=sections_from_pages(pages),
            warnings=sorted(set(warnings)),
            state="partially_ready" if incomplete else "ready",
        )
