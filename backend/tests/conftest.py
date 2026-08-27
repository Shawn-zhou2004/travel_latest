"""Shared backend test configuration."""

import os

import pytest

# Test runs must never talk to real infrastructure, so force the test
# environment before any Settings() call reads the development .env file.
os.environ["APP_ENV"] = "test"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
