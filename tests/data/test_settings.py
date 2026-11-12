from datetime import date, time
from pathlib import Path

import pydantic
import pytest
import yaml

from minibook.config.settings import Settings, load_settings


def test_settings_file_loads(settings: Settings) -> None:
    assert settings.data.history_start == date(2023, 6, 1)
    assert settings.equities.close_cutoff_local == time(18, 30)
    assert set(settings.ecb.fx.keys) == {"USD", "JPY"}
    assert len(settings.fred.series) == 9


def test_settings_are_frozen(settings: Settings) -> None:
    with pytest.raises(pydantic.ValidationError):
        settings.http.timeout_s = 1.0  # type: ignore[misc]


def test_unknown_keys_rejected(tmp_path: Path, settings: Settings) -> None:
    raw = settings.model_dump(mode="json")
    raw["http"]["surprise"] = 1
    path = tmp_path / "s.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(pydantic.ValidationError):
        load_settings(path)
