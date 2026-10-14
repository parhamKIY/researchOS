import importlib.util
from pathlib import Path

import pytest

from researchos.core.credentials import decode_key


def test_environment_upgrade_preserves_existing_credentials_and_cipher_key(tmp_path):
    source = Path(__file__).resolve().parents[2] / "scripts" / "bootstrap_env.py"
    if not source.is_file():
        pytest.skip("Repository bootstrap script is outside the backend-only test image")
    spec = importlib.util.spec_from_file_location("bootstrap_fixture", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = "POSTGRES_PASSWORD=existing-fixture\nRESEARCHOS_SESSION_SECRET=existing-session\n"
    target = tmp_path / ".env"
    target.write_text(original)
    message = module.bootstrap(tmp_path)
    upgraded = target.read_text()
    assert upgraded.startswith(original)
    encoded = upgraded.split("RESEARCHOS_CREDENTIAL_ENCRYPTION_KEY=", 1)[1].strip()
    assert len(decode_key(encoded)) == 32
    assert encoded not in message and "existing-fixture" not in message
    module.bootstrap(tmp_path)
    assert target.read_text() == upgraded
