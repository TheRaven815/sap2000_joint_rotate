"""Joint hattı ve local eksenler için hafif 3B önizleme."""

from __future__ import annotations

import math
import tkinter as tk
from dataclasses import dataclass
from typing import Mapping, Sequence

from .models import AxisPlan

Point3D = tuple[float, float, float]


def _dot(a: Point3D, b: Point3D) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Point3D, b: Point3D) -> Point3D:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


@dataclass(frozen=True)
class IsoView:
    """İzometrik/ortografik kamera ve ekran dönüşümü."""

    right: Point3D
    up: Point3D
    center: Point3D
    scale: float
    offset_x: float
    offset_y: float

    def project(self, point: Point3D) -> tuple[float, float]:
        relative = (
            point[0] - self.center[0],
            point[1] - self.center[1],
            point[2] - self.center[2],
        )
        x = _dot(relative, self.right) * self.scale + self.offset_x
        y = -_dot(relative, self.up) * self.scale + self.offset_y
        return x, y


def camera_basis(yaw_deg: float, pitch_deg: float) -> tuple[Point3D, Point3D]:
    """Kamera sağ ve yukarı birim vektörlerini döndürür."""

    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    direction = (
        math.cos(pitch) * math.cos(yaw),
        math.cos(pitch) * math.sin(yaw),
        math.sin(pitch),
    )
    right = (-math.sin(yaw), math.cos(yaw), 0.0)
    up = _cross(direction, right)
    return right, up


def orbit_view(
    points: Sequence[Point3D],
    width: float,
    height: float,
    yaw_deg: float,
    pitch_deg: float,
    zoom: float = 1.0,
    padding: float = 26.0,
) -> IsoView:
    """Döndürmede kaymayan sabit ölçekli kamera üretir.

    Noktaları kapsayan küre kullanıldığı için yaw/pitch değişirken ölçek
    sabit kalır; sürükleme sırasında görüntü zıplamaz.
    """

    right, up = camera_basis(yaw_deg, pitch_deg)
    if points:
        min_x = min(point[0] for point in points)
        max_x = max(point[0] for point in points)
        min_y = min(point[1] for point in points)
        max_y = max(point[1] for point in points)
        min_z = min(point[2] for point in points)
        max_z = max(point[2] for point in points)
        center = (
            (min_x + max_x) * 0.5,
            (min_y + max_y) * 0.5,
            (min_z + max_z) * 0.5,
        )
        radius = max(math.dist(point, center) for point in points)
    else:
        center = (0.0, 0.0, 0.0)
        radius = 0.0

    available = max(1.0, min(width, height) - padding * 2)
    if not math.isfinite(radius) or radius <= 1e-9:
        scale = 1.0
    else:
        scale = available / (radius * 2.0)
    scale *= max(0.05, zoom)

    return IsoView(
        right=right,
        up=up,
        center=center,
        scale=scale,
        offset_x=width * 0.5,
        offset_y=height * 0.5,
    )


def fit_view(
    points: Sequence[Point3D],
    width: float,
    height: float,
    padding: float = 30.0,
    yaw_deg: float = 38.0,
    pitch_deg: float = 24.0,
) -> IsoView:
    """Noktaları verilen alana sığdıran kamera dönüşümünü üretir."""

    right, up = camera_basis(yaw_deg, pitch_deg)
    if points:
        center = (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
            sum(point[2] for point in points) / len(points),
        )
    else:
        center = (0.0, 0.0, 0.0)

    projected: list[tuple[float, float]] = []
    for point in points:
        relative = (
            point[0] - center[0],
            point[1] - center[1],
            point[2] - center[2],
        )
        projected.append((_dot(relative, right), -_dot(relative, up)))

    if projected:
        xs = [item[0] for item in projected]
        ys = [item[1] for item in projected]
        span_x = max(xs) - min(xs)
        span_y = max(ys) - min(ys)
    else:
        xs = ys = [0.0]
        span_x = span_y = 0.0

    available_x = max(1.0, width - padding * 2)
    available_y = max(1.0, height - padding * 2)

    candidates: list[float] = []
    if span_x > 1e-9:
        candidates.append(available_x / span_x)
    if span_y > 1e-9:
        candidates.append(available_y / span_y)
    scale = min(candidates) if candidates else 1.0
    if not math.isfinite(scale) or scale <= 0.0:
        scale = 1.0

    offset_x = width * 0.5 - (min(xs) + max(xs)) * 0.5 * scale
    offset_y = height * 0.5 - (min(ys) + max(ys)) * 0.5 * scale
    return IsoView(
        right=right,
        up=up,
        center=center,
        scale=scale,
        offset_x=offset_x,
        offset_y=offset_y,
    )


class Preview3D(tk.Canvas):
    """Joint hattını, teğetleri ve hedef local ekseni çizen canvas."""

    def __init__(self, master: tk.Misc, palette: Mapping[str, str]) -> None:
        super().__init__(
            master,
            background=palette["panel"],
            highlightthickness=0,
            borderwidth=0,
            cursor="fleur",
        )
        self._palette = dict(palette)
        self._plan: AxisPlan | None = None
        self._message = "Önizleme sonrası 3B görünüm burada görünür."
        self._yaw = 38.0
        self._pitch = 24.0
        self._zoom = 1.0
        self._drag_origin: tuple[int, int] | None = None
        self._last_size = (0, 0)

        self.bind("<Configure>", self._on_configure)
        self.bind("<ButtonPress-1>", self._on_drag_start)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_drag_end)
        self.bind("<MouseWheel>", self._on_wheel)
        self.bind("<Button-4>", lambda _event: self._zoom_by(1.1))
        self.bind("<Button-5>", lambda _event: self._zoom_by(1 / 1.1))

    @property
    def has_plan(self) -> bool:
        return self._plan is not None

    def set_palette(self, palette: Mapping[str, str]) -> None:
        self._palette = dict(palette)
        self.configure(background=palette["panel"])
        self._redraw()

    def show_plan(self, plan: AxisPlan) -> None:
        self._plan = plan
        if self.winfo_width() <= 1 or self.winfo_height() <= 1:
            self.update_idletasks()
        self._redraw()

    def show_message(self, message: str) -> None:
        self._plan = None
        self._message = message
        self._redraw()

    def reset_view(self) -> None:
        self._yaw = 38.0
        self._pitch = 24.0
        self._zoom = 1.0
        self._redraw()

    def _on_configure(self, event: tk.Event) -> None:
        size = (int(event.width), int(event.height))
        if size != self._last_size:
            self._last_size = size
            self._redraw()

    def _on_drag_start(self, event: tk.Event) -> None:
        self._drag_origin = (event.x, event.y)

    def _on_drag(self, event: tk.Event) -> None:
        if self._drag_origin is None:
            return
        last_x, last_y = self._drag_origin
        self._yaw = (self._yaw + (event.x - last_x) * 0.55) % 360.0
        self._pitch = max(-80.0, min(80.0, self._pitch + (event.y - last_y) * 0.4))
        self._drag_origin = (event.x, event.y)
        self._redraw()

    def _on_drag_end(self, _event: tk.Event) -> None:
        self._drag_origin = None

    def _on_wheel(self, event: tk.Event) -> None:
        if not getattr(event, "delta", 0):
            return
        self._zoom_by(1.1 if event.delta > 0 else 1 / 1.1)

    def _zoom_by(self, factor: float) -> None:
        self._zoom = max(0.35, min(4.0, self._zoom * factor))
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 1 or height <= 1:
            return

        palette = self._palette
        if self._plan is None:
            self.create_text(
                width / 2,
                height / 2,
                text=self._message,
                fill=palette["muted"],
                font=("Segoe UI", 9),
                justify="center",
                width=max(160, width - 60),
            )
            return

        points = [result.joint.xyz for result in self._plan.results]
        view = orbit_view(
            points,
            width,
            height,
            yaw_deg=self._yaw,
            pitch_deg=self._pitch,
            zoom=self._zoom,
            padding=26.0,
        )

        def project(point: Point3D) -> tuple[float, float]:
            return view.project(point)

        self._draw_grid(points, project, palette)
        self._draw_line(points, project, palette)
        self._draw_normals(project, palette)
        if self._plan.use_3d:
            self._draw_tangents(project, palette)
        self._draw_joints(points, project, palette)
        self._draw_axes(width, height, view, palette)

    def _draw_grid(self, points, project, palette: Mapping[str, str]) -> None:
        if not points:
            return
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        z = min(point[2] for point in points)
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(max_x - min_x, 1e-6)
        span_y = max(max_y - min_y, 1e-6)
        margin = max(span_x, span_y) * 0.18
        min_x -= margin
        max_x += margin
        min_y -= margin
        max_y += margin

        divisions = 6
        for index in range(divisions + 1):
            ratio = index / divisions
            x = min_x + (max_x - min_x) * ratio
            y = min_y + (max_y - min_y) * ratio
            self.create_line(
                *project((x, min_y, z)),
                *project((x, max_y, z)),
                fill=palette["border"],
                width=1,
            )
            self.create_line(
                *project((min_x, y, z)),
                *project((max_x, y, z)),
                fill=palette["border"],
                width=1,
            )

    def _draw_line(self, points, project, palette: Mapping[str, str]) -> None:
        if len(points) < 2:
            return
        coordinates: list[float] = []
        for point in points:
            coordinates.extend(project(point))
        self.create_line(
            *coordinates,
            fill=palette["accent"],
            width=2,
            smooth=False,
            capstyle="round",
            joinstyle="round",
        )

    def _draw_normals(self, project, palette: Mapping[str, str]) -> None:
        if self._plan is None:
            return
        points = [result.joint.xyz for result in self._plan.results]
        if not points:
            return
        extent = max(
            max(point[0] for point in points) - min(point[0] for point in points),
            max(point[1] for point in points) - min(point[1] for point in points),
            1e-6,
        )
        arrow_length = extent * 0.16

        for result in self._plan.results:
            normal = result.normal
            if normal is None:
                continue
            origin = result.joint.xyz
            tip = (
                origin[0] + normal.x * arrow_length,
                origin[1] + normal.y * arrow_length,
                origin[2],
            )
            self._draw_arrow(
                project(origin),
                project(tip),
                palette["vector"],
                width=2,
            )

    def _draw_tangents(self, project, palette: Mapping[str, str]) -> None:
        if self._plan is None:
            return
        results = self._plan.results
        points = [result.joint.xyz for result in results]
        if not points:
            return
        extent = max(
            max(point[0] for point in points) - min(point[0] for point in points),
            max(point[1] for point in points) - min(point[1] for point in points),
            max(point[2] for point in points) - min(point[2] for point in points),
            1e-6,
        )
        arrow_length = extent * 0.11
        step = max(1, len(results) // 24)

        for index, result in enumerate(results):
            if index % step or result.tangent_3d is None:
                continue
            length = math.sqrt(sum(value * value for value in result.tangent_3d))
            if length < 1e-12:
                continue
            direction = tuple(value / length for value in result.tangent_3d)
            origin = result.joint.xyz
            tip = (
                origin[0] + direction[0] * arrow_length,
                origin[1] + direction[1] * arrow_length,
                origin[2] + direction[2] * arrow_length,
            )
            self._draw_arrow(
                project(origin),
                project(tip),
                palette["axis_y"],
                width=1,
            )

    def _draw_arrow(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        color: str,
        width: int = 2,
    ) -> None:
        self.create_line(
            *start, *end, fill=color, width=width, arrow="last", arrowshape=(8, 10, 4)
        )

    def _draw_joints(self, points, project, palette: Mapping[str, str]) -> None:
        for index, result in enumerate(self._plan.results if self._plan else []):
            x, y = project(result.joint.xyz)
            self.create_oval(
                x - 4,
                y - 4,
                x + 4,
                y + 4,
                fill=palette["panel"],
                outline=palette["accent"],
                width=2,
            )
            self.create_text(
                x + 7,
                y - 7,
                text=f"{index + 1:02d} · {result.joint.name}",
                fill=palette["text"],
                font=("Segoe UI", 8),
                anchor="sw",
            )

    def _draw_axes(
        self,
        width: int,
        height: int,
        view: IsoView,
        palette: Mapping[str, str],
    ) -> None:
        origin_x = 34.0
        origin_y = 38.0
        length = 24.0

        def direction(axis: Point3D) -> tuple[float, float]:
            x = _dot(axis, view.right)
            y = -_dot(axis, view.up)
            norm = math.hypot(x, y)
            if norm < 1e-9:
                return 0.0, -1.0
            return x / norm, y / norm

        for axis, color, label in (
            ((1.0, 0.0, 0.0), palette["axis_x"], "X"),
            ((0.0, 1.0, 0.0), palette["axis_y"], "Y"),
            ((0.0, 0.0, 1.0), palette["axis_z"], "Z"),
        ):
            dx, dy = direction(axis)
            end_x = origin_x + dx * length
            end_y = origin_y + dy * length
            self.create_line(
                origin_x,
                origin_y,
                end_x,
                end_y,
                fill=color,
                width=2,
                arrow="last",
                arrowshape=(7, 8, 3),
            )
            self.create_text(
                end_x + dx * 9,
                end_y + dy * 9,
                text=label,
                fill=color,
                font=("Segoe UI", 8, "bold"),
                anchor="center",
            )
        hint = "sürükle: döndür · tekerlek: yakınlaştır · mavi: normal"
        if self._plan is not None and self._plan.use_3d:
            hint += " · yeşil: 3B teğet"
        self.create_text(
            width - 12,
            height - 12,
            text=hint,
            fill=palette["muted"],
            font=("Segoe UI", 8),
            anchor="se",
        )
