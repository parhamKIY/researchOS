"""Parser child entrypoint: no application settings, database or broker access."""

import argparse
import json
import os
import time
from pathlib import Path


def write_progress(work: Path, current: int, total: int):
    temporary = work / "progress.tmp"
    for _ in range(5):
        try:
            temporary.write_text(json.dumps({"current": current, "total": total}), encoding="utf-8")
            temporary.replace(work / "progress.json")
            return
        except PermissionError:
            # Windows readers can briefly prevent replacement. Progress is best-effort;
            # the validated final result remains authoritative for completion.
            time.sleep(0.01)


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--source", type=Path, required=True)
    cli.add_argument("--work", type=Path, required=True)
    cli.add_argument("--options", type=Path, required=True)
    cli.add_argument("--memory-mb", type=int, required=True)
    cli.add_argument("--cpu-seconds", type=int, required=True)
    args = cli.parse_args()
    if os.name == "posix":
        import resource

        memory = args.memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_CPU, (args.cpu_seconds, args.cpu_seconds + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (20 * 1024 * 1024, 20 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    from researchos.processing.contracts import ParseFailure, ParseLimits
    from researchos.processing.pypdf_adapter import PypdfParser

    def progress(current, total):
        write_progress(args.work, current, total)

    try:
        limits = ParseLimits.model_validate_json(args.options.read_bytes())
        document = PypdfParser().parse(args.source, args.work, limits, progress)
        result = document.model_dump(mode="json")
    except ParseFailure as exc:
        result = {"error": exc.code}
    except MemoryError:
        result = {"error": "parser_resource_limit"}
    except Exception:
        result = {"error": "invalid_pdf"}
    (args.work / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
