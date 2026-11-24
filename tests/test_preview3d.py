"""3B önizleme projeksiyonu testleri."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from joint_axes.preview3d import Preview3D, camera_basis, fit_view, orbit_view


def test_camera_basis_is_orthonormal() -> None:
    right, up = camera_basis(38.0, 24.0)
    assert math.isclose(sum(value * value for value in right), 1.0, rel_tol=1e-9)
    assert math.isclose(sum(value * value for value in up), 1.0, rel_tol=1e-9)
    assert math.isclose(sum(a * b for a, b in zip(right, up)), 0.0, abs_tol=1e-9)


def test_fit_view_keeps_points_inside_canvas() -> None:
    points = [
        (-2.0, 0.0, 0.0),
        (0.0, 1.5, 0.0),
        (2.0, 0.0, 0.4),
        (3.0, 2.0, 0.0),
    ]
    width, height, padding = 640, 360, 30
    view = fit_view(points, width, height, padding=padding)

    for point in points:
        x, y = view.project(point)
        assert padding - 1 <= x <= width - padding + 1
        assert padding - 1 <= y <= height - padding + 1


def test_fit_view_handles_degenerate_line() -> None:
    view = fit_view([(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)], 400, 200)

    assert math.isfinite(view.scale)
    assert view.scale > 0
    x, y = view.project((0.0, 0.0, 0.0))
    assert (x, y) == (200.0, 100.0)


def test_yaw_rotates_projection() -> None:
    points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    first = fit_view(points, 400, 200, yaw_deg=0.0)
    second = fit_view(points, 400, 200, yaw_deg=90.0)

    assert first.project(points[1]) != second.project(points[1])


@pytest.mark.parametrize(
    ("dx", "dy", "yaw", "pitch"),
    [(20, 0, 27, 24), (-20, 0, 49, 24), (0, 20, 38, 32), (0, -20, 38, 16)],
)
def test_preview_drag_reverses_only_horizontal_orbit(dx, dy, yaw, pitch):
    preview = SimpleNamespace(_yaw=38.0, _pitch=24.0, _drag_origin=(100, 100), _redraw=lambda: None)
    Preview3D._on_drag(preview, SimpleNamespace(x=100 + dx, y=100 + dy))
    assert (preview._yaw, preview._pitch) == pytest.approx((yaw, pitch))
    assert preview._drag_origin == (100 + dx, 100 + dy)


def test_orbit_view_keeps_scale_while_rotating() -> None:
    points = [
        (-2.0, 0.0, 0.0),
        (0.0, 1.5, 0.4),
        (2.0, 0.0, 0.9),
        (3.0, 2.0, 0.0),
    ]
    first = orbit_view(points, 640, 360, yaw_deg=0.0, pitch_deg=0.0)
    second = orbit_view(points, 640, 360, yaw_deg=75.0, pitch_deg=30.0)

    assert math.isclose(first.scale, second.scale, rel_tol=1e-9)
    assert first.project(points[0]) != second.project(points[0])


def test_orbit_view_keeps_points_inside_canvas() -> None:
    points = [(-3.0, -1.0, 0.0), (0.0, 2.0, 1.0), (3.0, -1.0, 0.5)]
    width, height, padding = 640, 360, 26
    for yaw in (0.0, 45.0, 135.0, 260.0):
        for pitch in (-60.0, 0.0, 55.0):
            view = orbit_view(
                points, width, height, yaw_deg=yaw, pitch_deg=pitch, padding=padding
            )
            for point in points:
                x, y = view.project(point)
                assert padding - 1 <= x <= width - padding + 1
                assert padding - 1 <= y <= height - padding + 1


def test_orbit_view_zoom_scales_projection() -> None:
    points = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
    normal = orbit_view(points, 400, 200, yaw_deg=0.0, pitch_deg=0.0, zoom=1.0)
    zoomed = orbit_view(points, 400, 200, yaw_deg=0.0, pitch_deg=0.0, zoom=2.0)

    assert math.isclose(zoomed.scale, normal.scale * 2.0, rel_tol=1e-9)
