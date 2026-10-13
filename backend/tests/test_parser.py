import pytest
from pdf_fixtures import scientific_fixture
from pypdf import PdfReader, PdfWriter

from researchos.processing.contracts import ParseFailure, ParseLimits
from researchos.processing.pypdf_adapter import PypdfParser


def test_real_pdf_text_sections_images_and_metadata(tmp_path):
    pdf = tmp_path / "fixture.pdf"
    scientific_fixture(pdf)
    progress = []
    result = PypdfParser().parse(
        pdf,
        tmp_path / "images",
        ParseLimits(),
        lambda current, total: progress.append((current, total)),
    )
    assert result.state == "ready" and len(result.pages) == 2
    assert result.metadata["title"] == "Synthetic document extraction fixture"
    assert result.metadata["author_text"] == "ResearchOS fixture author"
    assert progress == [(1, 2), (2, 2)]
    assert len(result.figures) == 2
    for figure in result.figures:
        assert (tmp_path / "images" / figure.filename).is_file()
        assert figure.bounding_box is not None
        text = result.pages[figure.page_number - 1].text
        assert text[figure.caption_start : figure.caption_end].strip() == figure.caption
    assert [section.kind for section in result.sections] == ["introduction", "methodology"]
    for section in result.sections:
        for span in section.spans:
            assert (
                0
                <= span.start_offset
                < span.end_offset
                <= len(result.pages[span.page_number - 1].text)
            )
    for candidate in result.metadata["doi_candidates"]:
        page = result.pages[candidate["page_number"] - 1]
        assert page.text[candidate["start_offset"] : candidate["end_offset"]] == candidate["value"]
        assert candidate["verified"] is False


def test_scanned_pdf_is_partial_and_ocr_limitation_is_explicit(tmp_path):
    pdf = tmp_path / "scanned.pdf"
    scientific_fixture(pdf, scanned=True)
    result = PypdfParser().parse(pdf, tmp_path / "images", ParseLimits(), lambda *args: None)
    assert result.state == "partially_ready"
    assert "no_usable_text" in result.warnings
    assert all(page.text_status == "no_text" for page in result.pages)
    assert len(result.figures) == 2


@pytest.mark.parametrize(
    "case,code",
    [
        ("encrypted", "password_protected"),
        ("page_limit", "page_limit_exceeded"),
        ("text_limit", "text_limit_exceeded"),
    ],
)
def test_parser_rejects_unsupported_and_bounded_documents(tmp_path, case, code):
    pdf = tmp_path / "fixture.pdf"
    scientific_fixture(pdf)
    limits = ParseLimits()
    if case == "encrypted":
        writer = PdfWriter(clone_from=PdfReader(pdf))
        writer.encrypt("fixture password")
        writer.write(pdf)
    elif case == "page_limit":
        limits.max_pages = 1
    else:
        limits.max_characters = 10
    with pytest.raises(ParseFailure) as error:
        PypdfParser().parse(pdf, tmp_path / "images", limits, lambda *args: None)
    assert error.value.code == code


def test_image_limit_keeps_text_and_reports_partial_result(tmp_path):
    pdf = tmp_path / "fixture.pdf"
    scientific_fixture(pdf)
    result = PypdfParser().parse(
        pdf, tmp_path / "images", ParseLimits(max_figures=0), lambda *args: None
    )
    assert result.state == "partially_ready" and result.figures == []
    assert "image_limit_reached" in result.warnings
    assert all(page.text_status == "available" for page in result.pages)
