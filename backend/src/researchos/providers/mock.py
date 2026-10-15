import json

from pydantic import SecretStr

from researchos.providers.contracts import TextRequest, TextResponse, TokenUsage


class MockProvider:
    async def generate_text(self, request: TextRequest, key: SecretStr | None) -> TextResponse:
        if request.prompt.startswith('{"researchos_analysis": 1,'):
            from researchos.processing.analysis_contracts import SECTION_TOPICS

            envelope = json.loads(request.prompt)
            section = envelope["section"]
            chunk = envelope["document_data"]["chunks"][0]
            quote = chunk["text"][:160]
            persian = envelope["requested_language"] == "fa"
            payload = {
                "section": section,
                "items": [],
                "unavailable_reason": "نمونهٔ آزمایشی؛ منبعی کشف نشده است."
                if persian
                else "MOCK fixture: no resources discovered.",
            }
            if section != "resources":
                payload = {
                    "section": section,
                    "items": [
                        {
                            "kind": "ai_suggestion"
                            if section in {"research_gaps", "future_work"}
                            else "supported_interpretation",
                            "topic": "supported_limitation"
                            if section == "limitations"
                            else "suggested_direction"
                            if section == "future_work"
                            else "implementation"
                            if section == "results"
                            else SECTION_TOPICS[section][0],
                            "text": "خروجی آزمایشی؛ تحلیل علمی واقعی نیست."
                            if persian
                            else "MOCK fixture, not a scientific analysis.",
                            "evidence": [
                                {
                                    "chunk_id": chunk["chunk_id"],
                                    "start": 0,
                                    "end": len(quote),
                                    "quote": quote,
                                }
                            ],
                        }
                    ],
                }
            if section == "research_gaps":
                explanation = (
                    "نمونهٔ آزمایشی؛ ارزیابی علمی نشده است."
                    if persian
                    else "MOCK workflow fixture; no scientific evaluation."
                )
                payload["items"][0]["research"] = {
                    "motivation": explanation,
                    "proposed_approach": explanation,
                    "uncertainty": explanation,
                }
            if section == "overview":
                payload["items"] = [
                    {**payload["items"][0], "topic": topic}
                    for topic in ["short_summary", "detailed_summary", "beginner_explanation"]
                ]
            return TextResponse(
                json.dumps(payload, ensure_ascii=False), TokenUsage(8, 12, 0, 20), "mock"
            )
        return TextResponse(
            "MOCK: ResearchOS connectivity fixture; not a scientific result.",
            TokenUsage(8, 12, 0, 20),
            "mock",
        )
