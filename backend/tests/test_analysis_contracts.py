import json

import pytest

from researchos.processing.analysis_contracts import (
    analysis_prompt,
    document_context,
    validate_section,
)


def fixture():
    context = document_context(
        [{"id": "owned-page", "page_number": 2, "text": "متن 😀 Accuracy 90% on DATA."}]
    )
    output = {
        "section": "overview",
        "items": [
            {
                "kind": "author_claim",
                "topic": "short_summary",
                "text": "Source statement",
                "evidence": [{"chunk_id": "c0", "start": 0, "end": 6, "quote": "متن 😀 "}],
            }
        ],
    }
    return context, output


def test_exact_unicode_offsets_and_page_provenance():
    context, output = fixture()
    result = validate_section(json.dumps(output), "overview", context)
    witness = result["items"][0]["evidence"][0]
    assert witness["page_number"] == 2 and witness["page_id"] == "owned-page"
    assert witness["end_offset"] == 6


@pytest.mark.parametrize("change", ["quote", "page", "offset", "unsupported", "extra"])
def test_invalid_evidence_and_untyped_output_rejected(change):
    context, output = fixture()
    witness = output["items"][0]["evidence"][0]
    if change == "quote":
        witness["quote"] = "invented"
    if change == "page":
        witness["chunk_id"] = "foreign-page"
    if change == "offset":
        witness["end"] = 999
    if change == "unsupported":
        output["items"][0]["evidence"] = []
    if change == "extra":
        output["secret"] = "unexpected"
    with pytest.raises(ValueError):
        validate_section(json.dumps(output), "overview", context)


def test_context_is_bounded_and_sampling_is_disclosed():
    context = document_context([{"id": "p", "page_number": 1, "text": "x" * 100000}])
    assert context["coverage"] == "sampled_extracted_text"
    assert sum(len(chunk["text"]) for chunk in context["chunks"]) <= 24000
    assert context["chunks"][-1]["start"] > 90000


def test_prompt_is_versioned_data_envelope_and_preserves_untrusted_text():
    context, _ = fixture()
    envelope = json.loads(analysis_prompt("overview", "fa", context))
    assert envelope["requested_language"] == "fa" and envelope["document_data"] == context
    assert "untrusted" in envelope["instructions"]


def test_numeric_results_and_resources_cannot_invent_fields():
    context, output = fixture()
    output["section"] = "results"
    item = output["items"][0]
    item["topic"] = "quantitative_result"
    item["evidence"] = [
        {
            "chunk_id": "c0",
            "start": 0,
            "end": len(context["chunks"][0]["text"]),
            "quote": context["chunks"][0]["text"],
        }
    ]
    item["result"] = {"value": "90%", "metric": "Accuracy", "dataset": "DATA"}
    validate_section(json.dumps(output), "results", context)
    item["result"]["value"] = "99%"
    with pytest.raises(ValueError):
        validate_section(json.dumps(output), "results", context)
    output["section"] = "resources"
    item["topic"], item["result"] = "resource", None
    item["resource"] = {"name": "DATA", "url": "https://invented.example.com"}
    with pytest.raises(ValueError):
        validate_section(json.dumps(output), "resources", context)


@pytest.mark.parametrize("text", ["Accuracy is 99%", "See https://invented.example.com"])
def test_claim_prose_cannot_bypass_measurement_or_url_grounding(text):
    context, output = fixture()
    output["items"][0]["text"] = text
    with pytest.raises(ValueError):
        validate_section(json.dumps(output), "overview", context)


def test_research_proposals_require_labeled_suggestions_and_uncertainty():
    context, output = fixture()
    output["section"] = "research_gaps"
    claim = output["items"][0]
    claim["kind"], claim["topic"] = "ai_suggestion", "research_suggestion"
    with pytest.raises(ValueError):
        validate_section(json.dumps(output), "research_gaps", context)
    claim["research"] = {
        "motivation": "Explicit suggestion",
        "proposed_approach": "Evaluate a possible improvement",
        "uncertainty": "Not evaluated; related work unknown",
    }
    result = validate_section(json.dumps(output), "research_gaps", context)
    assert result["items"][0]["research"]["estimated_compute"] is None
    claim["kind"] = "author_claim"
    with pytest.raises(ValueError):
        validate_section(json.dumps(output), "research_gaps", context)
