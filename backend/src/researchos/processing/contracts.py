from collections.abc import Callable
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ParseLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_pages: int = Field(default=200, ge=1, le=500)
    max_characters: int = Field(default=2_000_000, ge=1000, le=5_000_000)
    max_figures: int = Field(default=100, ge=0, le=200)
    max_image_pixels: int = Field(default=16_000_000, ge=1000, le=32_000_000)


class ExtractedFigure(BaseModel):
    ordinal: int
    filename: str = Field(pattern=r"figure-[0-9]+\.png")
    page_number: int = Field(ge=1)
    caption: str | None = None
    caption_start: int | None = None
    caption_end: int | None = None
    caption_method: str | None = None
    bounding_box: list[float] | None = Field(default=None, min_length=4, max_length=4)
    extraction_method: str = "embedded_raster_decoded"


class ExtractedPage(BaseModel):
    page_number: int = Field(ge=1)
    text: str = Field(max_length=500_000)
    text_status: Literal["available", "no_text", "failed"]
    width: float = Field(gt=0, allow_inf_nan=False)
    height: float = Field(gt=0, allow_inf_nan=False)
    warnings: list[str] = Field(default_factory=list)


class ExtractedSpan(BaseModel):
    page_number: int
    start_offset: int
    end_offset: int


class ExtractedSection(BaseModel):
    ordinal: int
    kind: str
    heading: str | None
    spans: list[ExtractedSpan]
    extraction_method: str = "heading_pattern"


class ParsedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parser_name: str
    parser_version: str
    metadata: dict
    pages: list[ExtractedPage] = Field(max_length=500)
    figures: list[ExtractedFigure] = Field(max_length=200)
    sections: list[ExtractedSection]
    warnings: list[str]
    state: Literal["ready", "partially_ready"]


class ParseFailure(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class DocumentParser(Protocol):
    def parse(
        self, path: Path, output: Path, limits: ParseLimits, progress: Callable[[int, int], None]
    ) -> ParsedDocument: ...
