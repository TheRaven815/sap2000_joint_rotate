"""Hesaplama ve SAP2000 uygulama akışını birleştiren servis."""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import SapApiError
from .geometry import compute_joint_axes
from .inputs import parse_joint_names
from .models import AxisPlan, JointPoint
from .ordering import order_points_along_curve
from .sap import SapConnection


@dataclass(frozen=True)
class ApplyReport:
    """Local axes yazma işleminin özeti."""

    plan: AxisPlan
    applied: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]
    refresh_warning: str | None = None

    @property
    def summary(self) -> str:
        text = f"{len(self.applied)} joint güncellendi"
        if self.failed:
            text += f", {len(self.failed)} joint hata verdi"
        else:
            text += ", hata yok"
        return text + "."


@dataclass
class JointAxesService:
    """UI ve testlerin kullandığı yüksek seviye servis."""

    connection: SapConnection = field(default_factory=SapConnection)

    def read_points(self, names: list[str]) -> list[JointPoint]:
        points: list[JointPoint] = []
        for name in names:
            points.append(self.connection.get_joint_coordinates(name))
        return points

    def preview(
        self,
        joint_input: str | list[str],
        reverse_normal: bool = False,
        target_axis: str = "x",
        use_3d: bool = False,
    ) -> AxisPlan:
        names = parse_joint_names(joint_input)
        points = self.read_points(names)
        return compute_joint_axes(
            points,
            reverse_normal=reverse_normal,
            target_axis=target_axis,
            use_3d=use_3d,
        )

    def apply(self, plan: AxisPlan) -> ApplyReport:
        applied: list[str] = []
        failed: list[tuple[str, str]] = []

        for result in plan.results:
            if not result.applicable or result.angles is None:
                failed.append((result.joint.name, "Açı hesaplanamadı; joint atlandı."))
                continue
            try:
                angle_a, angle_b, angle_c = result.angles
                self.connection.set_local_axes(
                    result.joint.name, angle_a, angle_b, angle_c
                )
            except Exception as exc:
                failed.append((result.joint.name, str(exc)))
            else:
                applied.append(result.joint.name)

        refresh_warning: str | None = None
        if applied or failed:
            try:
                self.connection.refresh_view()
            except Exception as exc:
                refresh_warning = str(exc)

        return ApplyReport(
            plan=plan,
            applied=tuple(applied),
            failed=tuple(failed),
            refresh_warning=refresh_warning,
        )

    def run(
        self,
        joint_input: str | list[str],
        reverse_normal: bool = False,
        target_axis: str = "x",
        use_3d: bool = False,
    ) -> tuple[AxisPlan, ApplyReport]:
        plan = self.preview(
            joint_input,
            reverse_normal=reverse_normal,
            target_axis=target_axis,
            use_3d=use_3d,
        )
        return plan, self.apply(plan)

    def get_selected_joint_names(self) -> list[str]:
        return self.connection.get_selected_joint_names()

    def get_joint_names(self) -> list[str]:
        return self.connection.get_joint_names()

    def order_along_curve(
        self,
        names: list[str],
        preferred_start: str | None = None,
    ) -> list[str]:
        points = self.read_points(names)
        ordered = order_points_along_curve(points, preferred_start=preferred_start)
        return [point.name for point in ordered]

    def test_connection(self) -> None:
        try:
            self.connection.connect()
        except Exception as exc:
            raise SapApiError(str(exc)) from exc
