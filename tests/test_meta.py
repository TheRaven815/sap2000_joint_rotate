"""Sürüm, geliştirici ve proje bilgileri."""

from __future__ import annotations

from joint_axes import __version__
from joint_axes.meta import (
    APP_VERSION,
    APP_VERSION_NUMBER,
    DEVELOPER,
    PROJECT_URL,
    WEBSITE,
    WEBSITE_URL,
)


def test_version_display() -> None:
    assert APP_VERSION == "v0.3.1"
    assert APP_VERSION_NUMBER == "0.3.1"
    assert __version__ == "0.3.1"


def test_developer_and_website() -> None:
    assert DEVELOPER == "Enes Eliağır"
    assert WEBSITE == "zadax.net"
    assert WEBSITE_URL == "https://zadax.net"


def test_project_url() -> None:
    assert PROJECT_URL == "https://github.com/TheRaven815/sap2000_joint_rotate"
