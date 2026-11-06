"""2B teğet/normal/açı çekirdek algoritma testleri."""

from __future__ import annotations

import math

import pytest

from joint_axes.geometry import (
    angle_from_normal,
    angles_from_axes,
    compute_joint_axes,
    compute_tangents,
    local_frame_3d,
    normal_from_tangent,
    normalize_angle_deg,
    raw_tangent,
)
from joint_axes.models import JointPoint, Vector2


def make_points(*xy: tuple[float, float], z: float = 0.0) -> list[JointPoint]:
    return [
        JointPoint(name=str(index + 1), x=x, y=y, z=z)
        for index, (x, y) in enumerate(xy)
    ]


def assert_vector(vector: Vector2 | None, x: float, y: float) -> None:
    assert vector is not None
    assert vector.x == pytest.approx(x, abs=1e-12)
    assert vector.y == pytest.approx(y, abs=1e-12)


def test_raw_tangent_first_middle_last() -> None:
    points = make_points((0, 0), (1, 0), (2, 1), (4, 1))
    assert_vector(raw_tangent(points, 0), 1, 0)
    assert_vector(raw_tangent(points, 1), 2, 1)
    assert_vector(raw_tangent(points, 2), 3, 1)
    assert_vector(raw_tangent(points, 3), 2, 0)


def test_normal_is_perpendicular_right_turn() -> None:
    assert_vector(normal_from_tangent(Vector2(1, 0)), 0, -1)
    assert_vector(normal_from_tangent(Vector2(0, 1)), 1, 0)
    assert_vector(normal_from_tangent(Vector2(3, 4)), 0.8, -0.6)
    assert_vector(normal_from_tangent(Vector2(1, 0), reverse=True), 0, 1)
    assert_vector(normal_from_tangent(Vector2(3, 4), reverse=True), -0.8, 0.6)


def test_arch_outward_is_automatically_flipped() -> None:
    points = make_points((-1, 0), (0, 1), (1, 0))
    plan = compute_joint_axes(points)

    assert plan.auto_flip is True
    assert plan.manual_flip is False
    assert plan.flipped is True
    assert plan.positive_votes == 0
    assert plan.negative_votes == 1

    root = math.sqrt(0.5)
    assert_vector(plan.results[0].normal, -root, root)
    assert_vector(plan.results[1].normal, 0, 1)
    assert_vector(plan.results[2].normal, root, root)
    assert plan.results[0].angle_deg == pytest.approx(135.0)
    assert plan.results[1].angle_deg == pytest.approx(90.0)
    assert plan.results[2].angle_deg == pytest.approx(45.0)
    assert plan.target_axis == "x"
    assert plan.results[1].angles == pytest.approx((90.0, 0.0, 0.0))
    assert plan.results[0].curvature_dot is None
    assert plan.results[1].curvature_dot == pytest.approx(1.0)
    assert plan.results[2].curvature_dot is None


@pytest.mark.parametrize("axis", ["x", "y", "z"])
def test_3d_mode_matches_2d_for_flat_points(axis: str) -> None:
    points = make_points((-1, 0), (0, 1), (1, 0))

    flat = compute_joint_axes(points, target_axis=axis)
    three_d = compute_joint_axes(points, target_axis=axis, use_3d=True)

    assert three_d.use_3d is True
    assert three_d.results[1].angles == pytest.approx(flat.results[1].angles)


def test_3d_frame_follows_slope_for_x_axis() -> None:
    points = [
        JointPoint(name="1", x=0.0, y=0.0, z=0.0),
        JointPoint(name="2", x=4.0, y=0.0, z=3.0),
        JointPoint(name="3", x=8.0, y=0.0, z=6.0),
    ]

    plan = compute_joint_axes(points, target_axis="x", use_3d=True)

    assert plan.results[1].tangent_3d == pytest.approx((8.0, 0.0, 6.0))
    assert plan.results[1].angles == pytest.approx((-90.0, 0.0, 36.8698976))
    frame = local_frame_3d(
        plan.results[1].normal,
        plan.results[1].tangent_3d,
        "x",
    )
    assert frame is not None
    assert angles_from_axes(*frame) == pytest.approx(plan.results[1].angles)


@pytest.mark.parametrize(
    ("axis", "expected"),
    [
        ("y", (180.0, 36.8698976, 0.0)),
        ("z", (0.0, 53.1301024, 90.0)),
    ],
)
def test_3d_frame_follows_slope_for_other_axes(
    axis: str, expected: tuple[float, float, float]
) -> None:
    points = [
        JointPoint(name="1", x=0.0, y=0.0, z=0.0),
        JointPoint(name="2", x=4.0, y=0.0, z=3.0),
        JointPoint(name="3", x=8.0, y=0.0, z=6.0),
    ]

    plan = compute_joint_axes(points, target_axis=axis, use_3d=True)

    assert plan.results[1].angles == pytest.approx(expected)


def test_3d_mode_suppresses_xy_projection_warning() -> None:
    points = [
        JointPoint(name="1", x=0.0, y=0.0, z=0.0),
        JointPoint(name="2", x=4.0, y=0.0, z=3.0),
        JointPoint(name="3", x=8.0, y=0.0, z=6.0),
    ]

    flat = compute_joint_axes(points)
    three_d = compute_joint_axes(points, use_3d=True)

    assert any("XY izdüşümü" in warning for warning in flat.warnings)
    assert not any("XY izdüşümü" in warning for warning in three_d.warnings)


def test_valley_outward_needs_no_flip() -> None:
    points = make_points((-1, 0), (0, -1), (1, 0))
    plan = compute_joint_axes(points)

    assert plan.auto_flip is False
    assert plan.flipped is False
    assert plan.positive_votes == 1
    assert plan.negative_votes == 0
    assert_vector(plan.results[1].normal, 0, -1)
    assert plan.results[1].angle_deg == pytest.approx(-90.0)


def test_reverse_normal_inverts_final_direction() -> None:
    points = make_points((-1, 0), (0, -1), (1, 0))
    plan = compute_joint_axes(points, reverse_normal=True)

    assert plan.auto_flip is False
    assert plan.manual_flip is True
    assert plan.flipped is True
    assert_vector(plan.results[1].normal, 0, 1)
    assert plan.results[1].angle_deg == pytest.approx(90.0)


def test_straight_line_keeps_consistent_normal() -> None:
    points = make_points((0, 0), (1, 0), (2, 0), (3, 0))
    plan = compute_joint_axes(points)

    assert plan.auto_flip is False
    assert plan.positive_votes == 0
    assert plan.negative_votes == 0
    assert any("Eğrilik yok" in warning for warning in plan.warnings)
    for result in plan.results:
        assert_vector(result.normal, 0, -1)
        assert result.angle_deg == pytest.approx(-90.0)

    reversed_plan = compute_joint_axes(points, reverse_normal=True)
    for result in reversed_plan.results:
        assert_vector(result.normal, 0, 1)
        assert result.angle_deg == pytest.approx(90.0)


def test_collinear_segments_do_not_flip_180() -> None:
    points = make_points((0, 0), (1, 0), (2, 0), (3, 0), (4, 0))
    plan = compute_joint_axes(points)
    angles = [result.angle_deg for result in plan.results]

    assert angles == pytest.approx([-90.0] * 5)
    assert max(angles) - min(angles) == pytest.approx(0.0)


def test_zero_tangent_uses_neighbor_tangent() -> None:
    points = make_points((0, 0), (0, 0), (1, 0))
    tangents, warnings = compute_tangents(points)

    assert_vector(tangents[0], 1, 0)
    assert_vector(tangents[1], 1, 0)
    assert_vector(tangents[2], 1, 0)
    assert any("Sıfır teğet" in warning for warning in warnings[0])

    plan = compute_joint_axes(points)
    assert all(result.applicable for result in plan.results)
    assert all(result.angle_deg == pytest.approx(-90.0) for result in plan.results)


def test_all_coincident_points_are_not_applicable() -> None:
    points = make_points((2, 2), (2, 2), (2, 2))
    plan = compute_joint_axes(points)

    assert plan.applicable_count == 0
    assert all(result.normal is None for result in plan.results)
    assert all(result.angle_deg is None for result in plan.results)
    assert any("Tüm noktalar çakışık" in warning for warning in plan.warnings)


def test_unit_independence_of_angles() -> None:
    base = compute_joint_axes(make_points((-1, 0), (0, 1), (1, 0)))
    scaled = compute_joint_axes(make_points((-1000, 0), (0, 1000), (1000, 0)))

    base_angles = [result.angle_deg for result in base.results]
    scaled_angles = [result.angle_deg for result in scaled.results]
    assert scaled_angles == pytest.approx(base_angles)


def test_z_plane_warning_but_xy_projection_used() -> None:
    points = [
        JointPoint(name="1", x=0, y=0, z=0),
        JointPoint(name="2", x=0, y=1, z=1),
        JointPoint(name="3", x=1, y=0, z=0),
    ]
    plan = compute_joint_axes(points)
    assert any("XY düzleminde değil" in warning for warning in plan.warnings)
    assert plan.applicable_count == 3


def test_angle_normalization() -> None:
    assert normalize_angle_deg(0.0) == pytest.approx(0.0)
    assert normalize_angle_deg(190.0) == pytest.approx(-170.0)
    assert normalize_angle_deg(-190.0) == pytest.approx(170.0)
    assert normalize_angle_deg(540.0) == pytest.approx(180.0)
    assert normalize_angle_deg(-540.0) == pytest.approx(180.0)
    assert angle_from_normal(Vector2(-1, 0)) == pytest.approx(180.0)
    assert angle_from_normal(Vector2(0, -1)) == pytest.approx(-90.0)


def test_target_axis_y_aligns_local_2() -> None:
    points = make_points((-1, 0), (0, 1), (1, 0))
    plan = compute_joint_axes(points, target_axis="y")

    assert plan.target_axis == "y"
    assert plan.results[1].angles == pytest.approx((0.0, 0.0, 0.0))
    assert plan.results[0].angles == pytest.approx((45.0, 0.0, 0.0))


def test_target_axis_z_aligns_local_3_with_b_rotation() -> None:
    points = make_points((-1, 0), (0, 1), (1, 0))
    plan = compute_joint_axes(points, target_axis="z")

    assert plan.target_axis == "z"
    assert plan.results[1].angles == pytest.approx((90.0, 90.0, 0.0))


def test_invalid_target_axis_rejected() -> None:
    with pytest.raises(ValueError, match="Geçersiz hedef eksen"):
        compute_joint_axes(make_points((0, 0), (1, 1)), target_axis="w")


def test_compute_requires_two_points() -> None:
    with pytest.raises(ValueError, match="En az 2"):
        compute_joint_axes(make_points((0, 0)))
