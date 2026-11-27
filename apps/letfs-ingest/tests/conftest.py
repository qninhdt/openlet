from pathlib import Path

import pytest
from openlet_sdk.config import Config, load_path


@pytest.fixture
def config() -> Config:
    return load_path(Path("infra/config/openlet.example.yaml"))
