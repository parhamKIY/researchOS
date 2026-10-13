import re

from researchos.processing.contracts import ExtractedPage, ExtractedSection, ExtractedSpan

HEADINGS = {
    "abstract": "abstract",
    "introduction": "introduction",
    "related work": "related_work",
    "background": "background",
    "method": "methodology",
    "methods": "methodology",
    "methodology": "methodology",
    "experiments": "experiments",
    "results": "results",
    "discussion": "discussion",
    "limitations": "limitations",
    "conclusion": "conclusion",
    "conclusions": "conclusion",
    "references": "references",
    "appendix": "appendix",
}
HEADING_PATTERN = re.compile(
    r"^\s*(?:(?:\d+(?:\.\d+)*|[A-Z])\.?\s+)?([A-Za-z][A-Za-z -]{2,110})\s*$"
)


def sections_from_pages(pages: list[ExtractedPage]) -> list[ExtractedSection]:
    sections = []
    current = ExtractedSection(ordinal=0, kind="unclassified", heading=None, spans=[])
    for page in pages:
        begin = 0
        offset = 0
        for line in page.text.splitlines(keepends=True):
            match = HEADING_PATTERN.match(line.rstrip("\n"))
            kind = HEADINGS.get(match[1].strip().casefold()) if match else None
            if kind:
                if offset > begin:
                    current.spans.append(
                        ExtractedSpan(
                            page_number=page.page_number, start_offset=begin, end_offset=offset
                        )
                    )
                if current.spans:
                    sections.append(current)
                current = ExtractedSection(
                    ordinal=len(sections), kind=kind, heading=line.strip(), spans=[]
                )
                begin = offset
            offset += len(line)
        if len(page.text) > begin:
            current.spans.append(
                ExtractedSpan(
                    page_number=page.page_number, start_offset=begin, end_offset=len(page.text)
                )
            )
    if current.spans:
        sections.append(current)
    return sections


def doi_candidates(pages: list[ExtractedPage]) -> list[dict]:
    candidates = []
    for page in pages:
        for match in re.finditer(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", page.text):
            text = match[0].rstrip(".,;:")
            candidates.append(
                {
                    "value": text,
                    "page_number": page.page_number,
                    "start_offset": match.start(),
                    "end_offset": match.start() + len(text),
                    "verified": False,
                }
            )
            if len(candidates) >= 50:
                return candidates
    return candidates
