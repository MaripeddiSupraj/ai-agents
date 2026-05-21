import os
import pytest


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch):
    """Set required env vars for agent initialization."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key-for-tests")
