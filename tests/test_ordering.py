"""Hat boyunca otomatik sıralama testleri."""

from __future__ import annotations

import itertools
import math

import pytest

from joint_axes.models import JointPoint
from joint_axes.ordering import order_points_along_curve


def _arc() -> list[JointPoint]:
    points = [
        JointPoint(
            name=str(index),
            x=10.0 * math.cos(math.radians(angle)),
            y=10.0 * math.sin(math.radians(angle)),
            z=0.0,
        )
        for index, angle in enumerate(range(10, 171, 10))
    ]
    return points[5:] + points[:5]


def test_orders_arc_points_along_curve() -> None:
    ordered = order_points_along_curve(_arc())

    angles = [math.degrees(math.atan2(point.y, point.x)) for point in ordered]
    steps = [second - first for first, second in itertools.pairwise(angles)]
    assert all(step > 0 for step in steps) or all(step < 0 for step in steps)
    assert {point.name for point in ordered} == {str(index) for index in range(17)}


def test_collinear_points_are_ordered_by_position() -> None:
    points = [
        JointPoint(name=str(index), x=float(index), y=0.0, z=0.0) for index in range(11)
    ]
    shuffled = points[::-2] + points[1::2]

    ordered = order_points_along_curve(shuffled)

    assert [point.name for point in ordered] == [str(index) for index in range(11)]


def test_preferred_endpoint_starts_the_path() -> None:
    points = [
        JointPoint(name=str(index), x=float(index), y=0.0, z=0.0) for index in range(6)
    ]

    ordered = order_points_along_curve(points, preferred_start="5")

    assert ordered[0].name == "5"
    assert [point.name for point in ordered] == ["5", "4", "3", "2", "1", "0"]


def test_middle_preferred_start_is_ignored() -> None:
    points = [
        JointPoint(name=str(index), x=float(index), y=0.0, z=0.0) for index in range(6)
    ]

    ordered = order_points_along_curve(points, preferred_start="2")

    assert ordered[0].name in {"0", "5"}


def test_requires_two_points() -> None:
    with pytest.raises(ValueError, match="en az 2"):
        order_points_along_curve([JointPoint(name="1", x=0.0, y=0.0, z=0.0)])
