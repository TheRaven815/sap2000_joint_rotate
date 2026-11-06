"""GitHub Releases güncelleme kontrolü testleri."""

from __future__ import annotations

import json
import urllib.error

import pytest

from joint_axes.updates import (
    RELEASES_API_URL,
    ReleaseInfo,
    UpdateCheckError,
    check_for_updates,
    fetch_latest_release,
    is_newer_version,
    parse_version,
)


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def test_parse_version_accepts_v_prefix() -> None:
    assert parse_version("v0.3.1") == (0, 3, 1)
    assert parse_version("0.4") == (0, 4)


def test_parse_version_rejects_invalid_text() -> None:
    with pytest.raises(UpdateCheckError):
        parse_version("sürüm")


def test_is_newer_version() -> None:
    assert is_newer_version("0.3.2", "0.3.1")
    assert is_newer_version("0.4", "0.3.9")
    assert not is_newer_version("0.3.1", "0.3.1")
    assert not is_newer_version("0.3.0", "0.3.1")


def test_check_for_updates_detects_newer_release() -> None:
    latest = ReleaseInfo(
        version="0.3.2",
        tag="v0.3.2",
        url="https://github.com/example/releases/tag/v0.3.2",
    )

    result = check_for_updates("0.3.1", fetch_latest=lambda: latest)

    assert result.current_version == "0.3.1"
    assert result.latest == latest
    assert result.update_available


def test_check_for_updates_handles_no_release() -> None:
    result = check_for_updates("0.3.1", fetch_latest=lambda: None)

    assert result.latest is None
    assert not result.update_available


def test_fetch_latest_release_parses_github_response() -> None:
    payload = {
        "tag_name": "v0.3.2",
        "html_url": "https://github.com/example/releases/tag/v0.3.2",
    }

    release = fetch_latest_release(opener=lambda _request, timeout: FakeResponse(payload))

    assert release == ReleaseInfo(
        version="0.3.2",
        tag="v0.3.2",
        url="https://github.com/example/releases/tag/v0.3.2",
    )


def test_fetch_latest_release_returns_none_when_no_release_exists() -> None:
    def opener(_request: object, timeout: float) -> object:
        raise urllib.error.HTTPError(
            RELEASES_API_URL,
            404,
            "Not Found",
            None,
            None,
        )

    assert fetch_latest_release(opener=opener) is None
