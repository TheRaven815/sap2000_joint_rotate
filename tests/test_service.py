"""Servis katmanı testleri."""

from __future__ import annotations

import pytest

from joint_axes.errors import InputValidationError, JointNotFoundError, SapApiError
from joint_axes.models import JointPoint
from joint_axes.service import JointAxesService


class FakeConnection:
    def __init__(self, points: dict[str, tuple[float, float, float]]) -> None:
        self.points = points
        self.set_calls: list[tuple[str, float, float, float]] = []
        self.refresh_count = 0
        self.fail_names: set[str] = set()
        self.fail_refresh = False

    def get_joint_coordinates(self, name: str) -> JointPoint:
        if name not in self.points:
            raise JointNotFoundError(name)
        x, y, z = self.points[name]
        return JointPoint(name=name, x=x, y=y, z=z)

    def set_local_axes(
        self, name: str, angle_a: float, angle_b: float, angle_c: float
    ) -> None:
        if name in self.fail_names:
            raise SapApiError(f"Joint '{name}' atanamadi")
        self.set_calls.append((name, angle_a, angle_b, angle_c))

    def refresh_view(self) -> None:
        self.refresh_count += 1
        if self.fail_refresh:
            raise SapApiError("refresh hatasi")

    def get_joint_names(self) -> list[str]:
        return sorted(self.points, key=int)


ARCH = {
    "1": (-1.0, 0.0, 0.0),
    "2": (0.0, 1.0, 0.0),
    "3": (1.0, 0.0, 0.0),
}


def test_preview_reads_points_and_computes_plan() -> None:
    service = JointAxesService(connection=FakeConnection(ARCH))

    plan = service.preview("1, 2, 3")

    assert [result.joint.name for result in plan.results] == ["1", "2", "3"]
    assert plan.auto_flip is True
    assert plan.results[1].angle_deg == pytest.approx(90.0)


def test_preview_stops_on_missing_joint() -> None:
    service = JointAxesService(connection=FakeConnection(ARCH))

    with pytest.raises(JointNotFoundError, match="99"):
        service.preview("1, 99, 3")


def test_preview_rejects_bad_input() -> None:
    service = JointAxesService(connection=FakeConnection(ARCH))

    with pytest.raises(InputValidationError):
        service.preview("1")


def test_preview_and_apply_target_axis_z() -> None:
    connection = FakeConnection(ARCH)
    service = JointAxesService(connection=connection)

    plan = service.preview("1, 2, 3", target_axis="z")
    report = service.apply(plan)

    assert plan.target_axis == "z"
    assert plan.results[1].angles == pytest.approx((90.0, 90.0, 0.0))
    assert report.applied == ("1", "2", "3")
    name, angle_a, angle_b, angle_c = connection.set_calls[1]
    assert name == "2"
    assert (angle_a, angle_b, angle_c) == pytest.approx((90.0, 90.0, 0.0))


def test_apply_sets_every_angle_and_refreshes() -> None:
    connection = FakeConnection(ARCH)
    service = JointAxesService(connection=connection)
    plan = service.preview("1, 2, 3", reverse_normal=True)

    report = service.apply(plan)

    assert report.applied == ("1", "2", "3")
    assert report.failed == ()
    assert report.refresh_warning is None
    assert connection.refresh_count == 1
    assert [name for name, *_ in connection.set_calls] == ["1", "2", "3"]
    # Kemer normali otomatik dışa çevrilir; reverse bayrağı içe döndürür.
    name, angle_a, angle_b, angle_c = connection.set_calls[1]
    assert name == "2"
    assert (angle_a, angle_b, angle_c) == pytest.approx((-90.0, 0.0, 0.0))


def test_apply_reports_partial_failure_and_still_refreshes() -> None:
    connection = FakeConnection(ARCH)
    connection.fail_names.add("2")
    service = JointAxesService(connection=connection)
    plan = service.preview("1, 2, 3")

    report = service.apply(plan)

    assert report.applied == ("1", "3")
    assert [name for name, _ in report.failed] == ["2"]
    assert "1 joint hata verdi" in report.summary
    assert connection.refresh_count == 1


def test_apply_keeps_success_when_refresh_fails() -> None:
    connection = FakeConnection(ARCH)
    connection.fail_refresh = True
    service = JointAxesService(connection=connection)
    plan = service.preview("1, 2, 3")

    report = service.apply(plan)

    assert report.applied == ("1", "2", "3")
    assert report.refresh_warning == "refresh hatasi"


def test_get_joint_names_uses_connection_catalog() -> None:
    service = JointAxesService(connection=FakeConnection(ARCH))

    assert service.get_joint_names() == ["1", "2", "3"]


def test_preview_passes_3d_option() -> None:
    service = JointAxesService(connection=FakeConnection(ARCH))

    plan = service.preview("1, 2, 3", use_3d=True)

    assert plan.use_3d is True
    assert plan.results[1].tangent_3d is not None


def test_order_along_curve_reads_points_and_returns_names() -> None:
    points = {
        "1": (-2.0, 0.0, 0.0),
        "2": (0.0, 2.0, 0.0),
        "3": (2.0, 0.0, 0.0),
        "4": (0.0, -2.0, 0.0),
    }
    service = JointAxesService(connection=FakeConnection(points))

    ordered = service.order_along_curve(["3", "1", "4", "2"], preferred_start="1")

    assert ordered[0] == "1"
    assert set(ordered) == set(points)
    assert len(ordered) == 4


def test_run_combines_preview_and_apply() -> None:
    connection = FakeConnection(ARCH)
    service = JointAxesService(connection=connection)

    plan, report = service.run("1 2 3")

    assert plan.applicable_count == 3
    assert report.summary.startswith("3 joint güncellendi")
