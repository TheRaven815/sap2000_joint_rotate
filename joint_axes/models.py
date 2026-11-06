"""Temel veri yapıları ve 2B vektör matematiği."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Plan gereksinimi: teğet/eğrilik sıfır kabul eşiği.
ZERO_TOLERANCE = 1e-6


@dataclass(frozen=True)
class Vector2:
    """XY düzleminde değişmez iki boyutlu vektör."""

    x: float
    y: float

    def __add__(self, other: Vector2) -> Vector2:
        return Vector2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Vector2) -> Vector2:
        return Vector2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> Vector2:
        return Vector2(self.x * scalar, self.y * scalar)

    def __rmul__(self, scalar: float) -> Vector2:
        return self.__mul__(scalar)

    def __neg__(self) -> Vector2:
        return Vector2(-self.x, -self.y)

    def dot(self, other: Vector2) -> float:
        return self.x * other.x + self.y * other.y

    def norm(self) -> float:
        return math.hypot(self.x, self.y)

    def normalized(self) -> Vector2 | None:
        length = self.norm()
        if length < ZERO_TOLERANCE:
            return None
        return Vector2(self.x / length, self.y / length)

    def is_zero(self, tolerance: float = ZERO_TOLERANCE) -> bool:
        return self.norm() < tolerance

    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)


@dataclass(frozen=True)
class JointPoint:
    """SAP2000 joint adı ve global koordinatları."""

    name: str
    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Joint adı boş olamaz.")
        if not all(math.isfinite(value) for value in (self.x, self.y, self.z)):
            raise ValueError(f"Joint '{self.name}' koordinatları sonlu değil.")

    @property
    def xy(self) -> Vector2:
        return Vector2(self.x, self.y)

    @property
    def xyz(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)


@dataclass(frozen=True)
class JointAxisResult:
    """Tek bir joint için teğet, normal ve atanacak A/B/C açıları."""

    joint: JointPoint
    tangent: Vector2 | None
    normal: Vector2 | None
    angle_deg: float | None
    angles: tuple[float, float, float] | None = None
    curvature: Vector2 | None = None
    curvature_dot: float | None = None
    tangent_3d: tuple[float, float, float] | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def applicable(self) -> bool:
        return (
            self.normal is not None
            and self.angle_deg is not None
            and self.angles is not None
        )


@dataclass(frozen=True)
class AxisPlan:
    """Tüm joint listesi için hesaplama sonucu."""

    results: tuple[JointAxisResult, ...]
    auto_flip: bool
    manual_flip: bool
    positive_votes: int
    negative_votes: int
    warnings: tuple[str, ...] = field(default_factory=tuple)
    target_axis: str = "x"
    use_3d: bool = False

    @property
    def flipped(self) -> bool:
        return self.auto_flip != self.manual_flip

    @property
    def applicable_count(self) -> int:
        return sum(1 for result in self.results if result.applicable)
