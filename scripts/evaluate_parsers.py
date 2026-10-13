"""Optional local evaluation; PDFs and extracted text are never printed or committed."""

import argparse
import hashlib
import importlib.metadata
import json
import re
import tempfile
import time
from pathlib import Path


def evaluate(path: Path, parser: str, anchors: list[str]) -> dict:
    started = time.perf_counter()
    extra = {}
    if parser == "pypdf":
        from pypdf import PdfReader

        reader = PdfReader(path)
        text = [page.extract_text() or "" for page in reader.pages]
        images = sum(len(page.images.keys()) for page in reader.pages)
        version = importlib.metadata.version("pypdf")
    elif parser == "pdfplumber":
        import pdfplumber

        text = []
        images = 0
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text.append(page.extract_text(use_text_flow=True) or "")
                images += len(page.images)
                page.close()
        version = importlib.metadata.version("pdfplumber")
    elif parser == "selected":
        from researchos.processing.contracts import ParseLimits
        from researchos.processing.runner import parse_in_process

        with tempfile.TemporaryDirectory(prefix="researchos-evaluation-") as work:
            parsed = parse_in_process(path, Path(work), ParseLimits())
        text = [page.text for page in parsed.pages]
        images = len(parsed.figures)
        version = parsed.parser_version
        extra = {
            "state": parsed.state,
            "warnings": parsed.warnings,
            "sections": len(parsed.sections),
            "pages_with_warnings": sum(bool(page.warnings) for page in parsed.pages),
        }
    else:
        from docling_parse.pdf_parser import DoclingPdfParser

        parsed = DoclingPdfParser().load(path)
        text = [
            "\n".join(cell.text for cell in page.textline_cells)
            for _, page in parsed.iterate_pages()
        ]
        images = None
        version = importlib.metadata.version("docling-parse")
    normalized = re.sub(r"\s+", " ", " ".join(text)).casefold()
    return {
        "parser": parser,
        "version": version,
        "filename": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "pages": len(text),
        "text_characters": sum(map(len, text)),
        "pages_without_text": sum(not page.strip() for page in text),
        "image_objects": images,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "anchors": [
            {"text": anchor, "found": anchor.casefold() in normalized}
            for anchor in anchors
        ],
        **extra,
    }


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument(
        "--parser",
        choices=["pypdf", "pdfplumber", "docling-native", "selected"],
        required=True,
    )
    cli.add_argument("--pdf", type=Path, required=True)
    cli.add_argument("--anchor", action="append", default=[])
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = evaluate(args.pdf, args.parser, args.anchor)
    except Exception as exc:  # noqa: BLE001 - redact failures from optional parser implementations
        result = {
            "parser": args.parser,
            "filename": args.pdf.name,
            "error_type": type(exc).__name__,
        }
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("Evaluation record saved")


if __name__ == "__main__":
    main()
