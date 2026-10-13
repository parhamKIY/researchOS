import pytest
from pydantic import ValidationError

from researchos.core.config import Settings


@pytest.mark.parametrize(
    "updates",
    [
        {"database_url": "sqlite:///temporary.db"},
        {"redis_url": "http://localhost:6379"},
        {"session_secret": "short"},
        {"environment": "production", "public_origin": "http://localhost:3000"},
        {"public_origin": "http://remote.example"},
        {"public_origin": "https://example.com/some/path"},
    ],
)
def test_rejects_unsafe_settings(settings, updates):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **(settings.model_dump() | updates))


def test_validation_and_repr_do_not_expose_credentials(settings):
    secret = "private-example-do-not-log-this-value"
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, **(settings.model_dump() | {"database_url": secret}))
    assert secret not in str(error.value)
    assert settings.session_secret.get_secret_value() not in repr(settings)


def test_production_origin_can_use_https(settings):
    configured = Settings(
        _env_file=None,
        **(
            settings.model_dump()
            | {"environment": "production", "public_origin": "https://example.com"}
        ),
    )
    assert configured.public_origin.scheme == "https"
