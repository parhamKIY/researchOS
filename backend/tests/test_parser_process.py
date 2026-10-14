import json
from pathlib import Path

import pytest
from pdf_fixtures import scientific_fixture

from researchos.processing.child import write_progress
from researchos.processing.contracts import ParseFailure, ParseLimits
from researchos.processing.runner import parse_in_process


def test_real_child_extracts_text_without_app_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCHOS_DATABASE_URL", "fixture secret not required by child")
    monkeypatch.setenv("RESEARCHOS_SESSION_SECRET", "fixture secret not required by child")
    source = tmp_path / "source.pdf"
    scientific_fixture(source)
    progress = []
    result = parse_in_process(
        source,
        tmp_path / "output",
        ParseLimits(),
        heartbeat=lambda a, b: progress.append((a, b)) or True,
    )
    assert len(result.pages) == 2 and len(result.figures) == 2
    assert (2, 2) in progress
    assert "fixture secret" not in (tmp_path / "output" / "result.json").read_text()


def test_malformed_pdf_failure_does_not_echo_document_content(tmp_path):
    source = tmp_path / "bad.pdf"
    source.write_bytes(b"%PDF-1.7\nprivate document fixture data\n%%EOF")
    with pytest.raises(ParseFailure) as error:
        parse_in_process(source, tmp_path / "output", ParseLimits())
    assert error.value.code == "invalid_pdf"
    assert "private document" not in (tmp_path / "output" / "result.json").read_text()


def test_lost_lease_stops_the_child_process(tmp_path):
    source = tmp_path / "source.pdf"
    scientific_fixture(source)
    with pytest.raises(ParseFailure) as error:
        parse_in_process(source, tmp_path / "output", ParseLimits(), heartbeat=lambda *_: False)
    assert error.value.code == "lease_lost"


def test_transient_progress_file_lock_does_not_fail_valid_extraction(tmp_path, monkeypatch):
    original = Path.replace
    attempts = []

    def briefly_locked(path, target):
        attempts.append(path)
        if len(attempts) == 1:
            raise PermissionError("Explicit Windows reader-lock fixture")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", briefly_locked)
    write_progress(tmp_path, 2, 2)
    assert json.loads((tmp_path / "progress.json").read_text()) == {"current": 2, "total": 2}
    assert len(attempts) == 2


def test_locked_progress_preserves_last_known_count_without_false_completion(tmp_path, monkeypatch):
    (tmp_path / "progress.json").write_text('{"current":1,"total":2}')

    def locked(*_):
        raise PermissionError("Explicit persistent reader-lock fixture")

    monkeypatch.setattr(Path, "replace", locked)
    write_progress(tmp_path, 2, 2)
    assert json.loads((tmp_path / "progress.json").read_text()) == {"current": 1, "total": 2}
