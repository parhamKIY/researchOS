from pydantic import SecretStr

from researchos.providers.contracts import TextRequest, TextResponse, TokenUsage


class MockProvider:
    async def generate_text(self, request: TextRequest, key: SecretStr | None) -> TextResponse:
        return TextResponse(
            "MOCK: ResearchOS connectivity fixture; not a scientific result.",
            TokenUsage(8, 12, 0, 20),
            "mock",
        )
