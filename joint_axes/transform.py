"""UCS geometrisi ve yerel düzenleme parametrelerinin SAP2000'e dönüşümü."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import InputValidationError
from .geometry import Point3

Matrix3 = tuple[Point3, Point3, Point3]
ZERO: Point3 = (0.0, 0.0, 0.0)
IDENTITY: Matrix3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def _finite(values: Point3) -> Point3:
    if not all(math.isfinite(value) for value in values):
        raise InputValidationError("Koordinatlar sonlu sayı olmalı.")
    return values


def _cross(a: Point3, b: Point3) -> Point3:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _line_direction(a: Point3, b: Point3) -> Point3:
    delta = _finite((b[0] - a[0], b[1] - a[1], b[2] - a[2]))
    length = math.hypot(*delta)
    if not math.isfinite(length) or length == 0.0:
        raise InputValidationError("Eksen/düzlem için birbirinden farklı noktalar girin.")
    return (delta[0] / length, delta[1] / length, delta[2] / length)


@dataclass(frozen=True)
class CoordinateSystem:
    """OAPI'nin satır sıralı matrisi: global = M @ local + origin."""

    origin: Point3 = ZERO
    matrix: Matrix3 = IDENTITY

    def __post_init__(self) -> None:
        _finite(self.origin)
        for row in self.matrix:
            _finite(row)
        a, b, c = self.matrix
        if any(
            not math.isclose(sum(x * y for x, y in zip(row, target)), float(i == j), abs_tol=1e-7)
            for i, row in enumerate(self.matrix)
            for j, target in enumerate(self.matrix)
        ) or not math.isclose(sum(x * y for x, y in zip(_cross(a, b), c)), 1.0, abs_tol=1e-7):
            raise InputValidationError("UCS matrisi geçerli bir sağ el eksen takımı değil.")

    @classmethod
    def from_sap(cls, origin: Point3, values: tuple[float, ...]) -> CoordinateSystem:
        if len(values) != 9:
            raise InputValidationError("SAP2000 UCS matrisi 9 bileşen içermeli.")
        a, b, c, d, e, f, g, h, i = values
        return cls(origin, ((a, b, c), (d, e, f), (g, h, i)))

    def global_vector(self, local: Point3) -> Point3:
        x, y, z = _finite(local)
        a, b, c = (row[0] * x + row[1] * y + row[2] * z for row in self.matrix)
        return _finite((a, b, c))

    def global_point(self, local: Point3) -> Point3:
        x, y, z = self.global_vector(local)
        a, b, c = self.origin
        return _finite((x + a, y + b, z + c))

    def local_point(self, point: Point3) -> Point3:
        u, v, w = (a - b for a, b in zip(point, self.origin))
        x, y, z = _finite((u, v, w))
        a, b, c = self.matrix
        local_x, local_y, local_z = (u * x + v * y + w * z for u, v, w in zip(a, b, c))
        return _finite((local_x, local_y, local_z))

    def sap_rotations(self) -> Point3:
        """SetCoordSys sırası: sabit global Z, Y, X etrafında döndür."""
        a, b, c = self.matrix
        cy = math.hypot(a[0], a[1])
        ry = math.atan2(a[2], cy)
        if cy > 1e-10:
            rz = math.atan2(-a[1], a[0])
            rx = math.atan2(-b[2], c[2])
        else:
            rz = math.atan2(b[0], b[1])
            rx = 0.0
        return math.degrees(rz), math.degrees(ry), math.degrees(rx)


@dataclass(frozen=True)
class NativeEdit:
    method: str
    args: tuple[float | int, ...]
    remove: bool = False


def _count(number: int) -> int:
    if type(number) is not int or not 1 <= number <= 2_147_483_647:
        raise InputValidationError("Kopya sayısı 1 ile 2147483647 arasında tam sayı olmalı.")
    return number


def translation(
    ucs: CoordinateSystem, delta: Point3, copies: int | None = None, remove: bool = False
) -> NativeEdit:
    offset = ucs.global_vector(delta)
    if offset == ZERO:
        raise InputValidationError("En az bir öteleme bileşeni sıfırdan farklı olmalı.")
    if copies is None:
        return NativeEdit("Move", offset)
    return NativeEdit("ReplicateLinear", (*offset, _count(copies)), remove)


def radial(
    ucs: CoordinateSystem, first: Point3, second: Point3, angle: float,
    copies: int, remove: bool = False,
) -> NativeEdit:
    if not math.isfinite(angle) or angle % 360 == 0.0:
        raise InputValidationError("Açı sonlu olmalı ve 360°'nin tam katı olmamalı.")
    a, b = ucs.global_point(first), ucs.global_point(second)
    _line_direction(a, b)
    return NativeEdit("ReplicateRadial", (4, *a, *b, _count(copies), angle), remove)


def mirror(
    ucs: CoordinateSystem, first: Point3, second: Point3, third: Point3,
    remove: bool = False,
) -> NativeEdit:
    a, b, c = ucs.global_point(first), ucs.global_point(second), ucs.global_point(third)
    if math.hypot(*_cross(_line_direction(a, b), _line_direction(a, c))) < 1e-10:
        raise InputValidationError("Ayna düzleminin üç noktası aynı doğru üzerinde olamaz.")
    return NativeEdit("ReplicateMirror", (4, *a, *b, *c), remove)
