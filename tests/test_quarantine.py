"""Tests for Provider Auto-Quarantine mechanism."""

from pydantic import BaseModel, ValidationError

from collectibles.providers.base import BaseProvider


class DummySchema(BaseModel):
    required_num: int


class DummyProvider(BaseProvider):
    async def fetch_listings(self, limit: int = 100):
        return []

    async def health_check(self) -> bool:
        return not self.is_quarantined


def test_provider_auto_quarantine_trigger() -> None:
    provider = DummyProvider(provider_id="test_market", max_consecutive_validation_errors=3)
    assert not provider.is_quarantined

    # Simulate 2 validation failures (below threshold)
    for _ in range(2):
        try:
            DummySchema.model_validate({"required_num": "not_an_int"})
        except ValidationError as e:
            provider.record_validation_error(e)

    assert not provider.is_quarantined

    # 3rd validation failure hits threshold -> Quarantined
    try:
        DummySchema.model_validate({"required_num": "still_bad"})
    except ValidationError as e:
        provider.record_validation_error(e)

    assert provider.is_quarantined is True


def test_provider_success_resets_error_counter() -> None:
    provider = DummyProvider(provider_id="test_market", max_consecutive_validation_errors=3)

    # 2 errors
    for _ in range(2):
        try:
            DummySchema.model_validate({"invalid": True})
        except ValidationError as e:
            provider.record_validation_error(e)

    assert provider._consecutive_errors == 2

    # 1 success
    provider.record_validation_success()
    assert provider._consecutive_errors == 0
    assert not provider.is_quarantined
