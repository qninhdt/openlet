from pathlib import Path
from typing import cast

import pytest
import yaml
from openlet_sdk.config import Config


@pytest.fixture
def config() -> Config:
    return cast(
        Config, yaml.safe_load(Path("infra/config/openlet.example.yaml").read_text())
    )
