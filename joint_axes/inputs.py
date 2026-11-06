"""Kullanıcı joint listesi girdisinin ayrıştırılması."""

from __future__ import annotations

import re
from collections.abc import Iterable

from .errors import InputValidationError

_SEPARATOR = re.compile(r"[,;\s]+")
_BRACKETS = "[]()"


def split_joint_tokens(value: str) -> list[str]:
    """Metni doğrulama yapmadan joint adı parçalarına ayırır."""

    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]

    names: list[str] = []
    for raw in _SEPARATOR.split(text):
        token = raw.strip().strip("\"'")
        token = token.strip(_BRACKETS)
        token = token.strip().strip("\"'")
        if token:
            names.append(token)
    return names


def parse_joint_names(value: str | Iterable[str]) -> list[str]:
    """Virgül, noktalı virgül, boşluk veya satırla ayrılmış joint adlarını döndürür."""

    if isinstance(value, str):
        names = split_joint_tokens(value)
    else:
        names = []
        for item in value:
            token = str(item).strip().strip("\"'")
            token = token.strip(_BRACKETS).strip().strip("\"'")
            if token:
                names.append(token)

    if len(names) < 2:
        raise InputValidationError("En az 2 joint adı girin. Örnek: 1, 2, 3, 4")

    seen: set[str] = set()
    duplicates: list[str] = []
    for name in names:
        if name in seen and name not in duplicates:
            duplicates.append(name)
        seen.add(name)
    if duplicates:
        duplicate_text = ", ".join(f"'{name}'" for name in duplicates)
        raise InputValidationError(
            f"Aynı joint birden fazla kez girilemez: {duplicate_text}. "
            "Sıralı liste her jointi bir kez içermelidir."
        )

    return names
