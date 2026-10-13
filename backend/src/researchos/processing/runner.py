import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from researchos.processing.contracts import ParsedDocument, ParseFailure, ParseLimits

SAFE_ERRORS = {
    "password_protected",
    "no_pages",
    "page_limit_exceeded",
    "text_limit_exceeded",
    "parser_resource_limit",
    "invalid_pdf",
}


def parse_in_process(
    source: Path,
    work: Path,
    limits: ParseLimits,
    *,
    timeout_seconds: int = 60,
    memory_mb: int = 1024,
    heartbeat: Callable[[int, int], bool] = lambda *_: True,
) -> ParsedDocument:
    source = source.resolve()
    work = work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    options = work / "options.json"
    options.write_text(limits.model_dump_json(), encoding="utf-8")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
    }
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "researchos.processing.child",
            "--source",
            str(source),
            "--work",
            str(work),
            "--options",
            str(options),
            "--memory-mb",
            str(memory_mb),
            "--cpu-seconds",
            str(timeout_seconds),
        ],
        cwd=work,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    started = time.monotonic()
    current = total = 0
    try:
        while process.poll() is None:
            if time.monotonic() - started > timeout_seconds:
                raise ParseFailure("parser_timeout")
            try:
                update = json.loads((work / "progress.json").read_bytes())
                if 0 <= update["current"] <= update["total"] <= limits.max_pages:
                    current, total = update["current"], update["total"]
            except (OSError, ValueError, KeyError, TypeError):
                pass
            if not heartbeat(current, total):
                raise ParseFailure("lease_lost")
            time.sleep(0.25)
        result_path = work / "result.json"
        if process.returncode != 0 or not result_path.is_file():
            raise ParseFailure("parser_resource_limit")
        if result_path.stat().st_size > 20 * 1024 * 1024:
            raise ParseFailure("parser_resource_limit")
        result = json.loads(result_path.read_bytes())
        if "error" in result:
            raise ParseFailure(result["error"] if result["error"] in SAFE_ERRORS else "invalid_pdf")
        parsed = ParsedDocument.model_validate(result)
        if not heartbeat(len(parsed.pages), len(parsed.pages)):
            raise ParseFailure("lease_lost")
        return parsed
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
