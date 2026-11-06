"""Joint listesi ayrıştırma testleri."""

from __future__ import annotations

import pytest

from joint_axes.errors import InputValidationError
from joint_axes.inputs import parse_joint_names, split_joint_tokens


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1, 2, 3", ["1", "2", "3"]),
        ("J1,J2,J3", ["J1", "J2", "J3"]),
        ("1; 2; 3", ["1", "2", "3"]),
        ("1\n2\n3\n", ["1", "2", "3"]),
        ("[1, 2, 3]", ["1", "2", "3"]),
        ("('A', 'B')", ["A", "B"]),
        (" 1  2  3 ", ["1", "2", "3"]),
    ],
)
def test_parse_text_formats(text: str, expected: list[str]) -> None:
    assert parse_joint_names(text) == expected


def test_parse_list_input() -> None:
    assert parse_joint_names(["1", "2", "3"]) == ["1", "2", "3"]
    assert parse_joint_names([1, 2, 3]) == ["1", "2", "3"]


def test_quotes_are_stripped() -> None:
    assert parse_joint_names('"J1", "J2", "J3"') == ["J1", "J2", "J3"]


def test_split_tokens_allows_single_joint() -> None:
    assert split_joint_tokens(" 12 ") == ["12"]
    assert split_joint_tokens("10, 11; 12") == ["10", "11", "12"]
    assert split_joint_tokens("") == []


def test_at_least_two_joints_required() -> None:
    with pytest.raises(InputValidationError, match="En az 2"):
        parse_joint_names("1")
    with pytest.raises(InputValidationError, match="En az 2"):
        parse_joint_names("")


def test_duplicate_joint_rejected() -> None:
    with pytest.raises(InputValidationError, match="birden fazla"):
        parse_joint_names("1, 2, 3, 2")
