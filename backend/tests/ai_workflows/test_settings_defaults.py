from datetime import date

import pytest

from app.models.user import UserSettings
from app.modules.ai_workflows.router import _effective_generation_request
from app.modules.ai_workflows.schemas import GenerationJobCreate


DESTINATION = {
    "name": "长沙市",
    "display_address": "中国 · 湖南省 · 长沙市",
    "city_code": "430100",
}


class FakeSession:
    def __init__(self, settings: UserSettings | None = None) -> None:
        self.settings = settings
        self.added: list[object] = []

    async def get(self, model: object, user_id: str) -> UserSettings | None:
        return self.settings

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


def request(**overrides: object) -> GenerationJobCreate:
    values: dict[str, object] = {
        "destination": DESTINATION,
        "start_date": date(2026, 10, 1),
        "end_date": date(2026, 10, 3),
    }
    values.update(overrides)
    return GenerationJobCreate.model_validate(values)


@pytest.mark.anyio
async def test_omitted_preferences_use_saved_settings() -> None:
    settings = UserSettings(
        user_id="00000000-0000-4000-8000-000000000001",
        interest_tags=["吃吃喝喝", "citywalk", "历史古建", "小众探索"],
        travel_pace="relaxed",
        traveler_type="family",
    )

    effective = await _effective_generation_request(
        FakeSession(settings), "00000000-0000-4000-8000-000000000001", request()
    )

    assert effective.preference_tags == ["吃吃喝喝", "citywalk", "历史古建"]
    assert effective.pace == "slow"
    assert effective.traveler_type == "family"
    assert effective.budget_amount is None


@pytest.mark.anyio
async def test_explicit_empty_null_and_values_override_saved_settings() -> None:
    settings = UserSettings(
        user_id="00000000-0000-4000-8000-000000000001",
        interest_tags=["吃吃喝喝"],
        travel_pace="packed",
    )

    effective = await _effective_generation_request(
        FakeSession(settings),
        "00000000-0000-4000-8000-000000000001",
        request(preference_tags=[], pace=None, traveler_type=None),
    )

    assert effective.preference_tags == []
    assert effective.pace is None
    assert effective.traveler_type is None
    assert effective.budget_amount is None


@pytest.mark.anyio
async def test_packed_settings_map_to_fast() -> None:
    settings = UserSettings(user_id="00000000-0000-4000-8000-000000000001", travel_pace="packed")

    effective = await _effective_generation_request(
        FakeSession(settings), "00000000-0000-4000-8000-000000000001", request()
    )

    assert effective.pace == "fast"
