import importlib.metadata

PARSER_NAME = "pypdf_raster_v1"


def parser_version() -> str:
    return ";".join(
        f"{name}={importlib.metadata.version(name)}" for name in ["pypdf", "pdfplumber", "pillow"]
    )
