"""Keep network configuration and shared state isolated between tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def wikidata_api_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    monkeypatch.setenv("WIKIDATA_PILOT_CONTACT", "https://example.org/operator")
    monkeypatch.setenv(
        "WIKIDATA_PILOT_STATE_DIR", str(tmp_path_factory.mktemp("wikidata-api-state"))
    )
