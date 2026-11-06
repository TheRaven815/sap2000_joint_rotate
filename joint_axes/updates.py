"""GitHub Releases üzerinden manuel güncelleme kontrolü."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .meta import APP_NAME, APP_VERSION_NUMBER, PROJECT_URL, RELEASES_URL

REPOSITORY_PATH = PROJECT_URL.removeprefix("https://github.com/").strip("/")
RELEASES_API_URL = (
    f"https://api.github.com/repos/{REPOSITORY_PATH}/releases/latest"
)


class UpdateCheckError(RuntimeError):
    """Güncelleme kontrolü tamamlanamadığında yükseltilir."""


@dataclass(frozen=True)
class ReleaseInfo:
    """GitHub'da yayımlanmış bir sürüm."""

    version: str
    tag: str
    url: str


@dataclass(frozen=True)
class UpdateCheckResult:
    """Mevcut sürüm ile son yayımlanmış sürümün karşılaştırması."""

    current_version: str
    latest: ReleaseInfo | None
    update_available: bool


def parse_version(text: str) -> tuple[int, ...]:
    """``v0.3.1`` gibi bir etiketi sayısal sürüm bileşenlerine ayırır."""

    value = text.strip()
    if value[:1] in {"v", "V"}:
        value = value[1:]
    match = re.match(r"\d+(?:\.\d+)*", value)
    if match is None:
        raise UpdateCheckError(f"Geçersiz sürüm biçimi: {text!r}")
    return tuple(int(part) for part in match.group(0).split("."))


def is_newer_version(candidate: str, current: str) -> bool:
    """``candidate`` sürümü ``current`` sürümünden yeniyse ``True`` döner."""

    candidate_parts = parse_version(candidate)
    current_parts = parse_version(current)
    length = max(len(candidate_parts), len(current_parts))
    candidate_parts += (0,) * (length - len(candidate_parts))
    current_parts += (0,) * (length - len(current_parts))
    return candidate_parts > current_parts


def fetch_latest_release(
    *,
    timeout: float = 8.0,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> ReleaseInfo | None:
    """Son yayımlanmış GitHub sürümünü döndürür.

    Yayımlanmış sürüm yoksa ``None`` döner; ağ veya veri hatasında
    :class:`UpdateCheckError` yükseltir.
    """

    request = urllib.request.Request(
        RELEASES_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{APP_NAME}/{APP_VERSION_NUMBER}",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise UpdateCheckError(
            f"GitHub sürüm isteği başarısız oldu (HTTP {exc.code})."
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise UpdateCheckError(f"GitHub'a ulaşılamadı: {reason}") from exc
    except TimeoutError as exc:
        raise UpdateCheckError("GitHub isteği zaman aşımına uğradı.") from exc
    except (OSError, ValueError, UnicodeError) as exc:
        raise UpdateCheckError("Güncelleme bilgisi okunamadı.") from exc

    if not isinstance(payload, dict):
        raise UpdateCheckError("GitHub yanıtı beklenen biçimde değil.")

    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag.strip():
        raise UpdateCheckError("Yayımlanmış sürüm etiketi bulunamadı.")
    tag = tag.strip()

    version = ".".join(str(part) for part in parse_version(tag))
    url = payload.get("html_url")
    if not isinstance(url, str) or not url.startswith("https://"):
        url = RELEASES_URL

    return ReleaseInfo(version=version, tag=tag, url=url)


def check_for_updates(
    current_version: str = APP_VERSION_NUMBER,
    *,
    fetch_latest: Callable[[], ReleaseInfo | None] = fetch_latest_release,
) -> UpdateCheckResult:
    """Mevcut sürümü son yayımlanmış sürümle karşılaştırır."""

    latest = fetch_latest()
    return UpdateCheckResult(
        current_version=current_version,
        latest=latest,
        update_available=(
            latest is not None
            and is_newer_version(latest.version, current_version)
        ),
    )
