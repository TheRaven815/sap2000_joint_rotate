"""Joint noktalarını hat boyunca pratik biçimde sıralama."""

from __future__ import annotations

from collections.abc import Sequence

from .models import JointPoint

DISTANCE_EPSILON = 1.0e-12


def _distance_sq(first: JointPoint, second: JointPoint) -> float:
    dx = first.x - second.x
    dy = first.y - second.y
    return dx * dx + dy * dy


def _farthest_pair(points: Sequence[JointPoint]) -> tuple[int, int]:
    """Hattın iki ucunu yaklaşık olarak veren en uzak nokta çiftini bulur."""

    best_distance = -1.0
    best_pair = (0, 1)
    for first in range(len(points)):
        for second in range(first + 1, len(points)):
            distance = _distance_sq(points[first], points[second])
            if distance > best_distance:
                best_distance = distance
                best_pair = (first, second)
    return best_pair


def _pick_start(points: Sequence[JointPoint], preferred_start: str | None) -> int:
    first, second = _farthest_pair(points)
    for index in (first, second):
        if preferred_start is not None and points[index].name == preferred_start:
            return index

    # Yön kullanıcıya kalsın diye uçlardan biri koordinatla sabit seçilir.
    return min(
        (first, second),
        key=lambda index: (
            round(points[index].x, 9),
            round(points[index].y, 9),
            points[index].name.casefold(),
        ),
    )


def _nearest_neighbor(points: Sequence[JointPoint], start: int) -> list[int]:
    order = [start]
    unvisited = set(range(len(points)))
    unvisited.remove(start)

    while unvisited:
        current = order[-1]
        following = min(
            unvisited,
            key=lambda index: (
                _distance_sq(points[current], points[index]),
                points[index].name.casefold(),
            ),
        )
        order.append(following)
        unvisited.remove(following)
    return order


def _two_opt(points: Sequence[JointPoint], order: list[int]) -> list[int]:
    """Kesişen/atlayan parçaları düzelterek açık yolu kısaltır."""

    improved = True
    passes = 0
    while improved and passes < 6:
        improved = False
        passes += 1
        for start in range(1, len(order) - 1):
            for end in range(start + 1, len(order)):
                before = order[start - 1]
                first = order[start]
                last = order[end]
                after = order[end + 1] if end + 1 < len(order) else None

                old_cost = _distance_sq(points[before], points[first])
                new_cost = _distance_sq(points[before], points[last])
                if after is not None:
                    old_cost += _distance_sq(points[last], points[after])
                    new_cost += _distance_sq(points[first], points[after])

                if new_cost + DISTANCE_EPSILON < old_cost:
                    order[start : end + 1] = reversed(order[start : end + 1])
                    improved = True
                    break
            if improved:
                break
    return order


def order_points_along_curve(
    points: Sequence[JointPoint],
    preferred_start: str | None = None,
) -> list[JointPoint]:
    """Noktaları en yakın komşu + 2-opt ile hat boyunca sıraya koyar.

    ``preferred_start`` uç noktalardan biriyse başlangıç ondan yapılır.
    Orta nokta verilirse yok sayılır; yön kullanıcı tarafından ters çevrilebilir.
    """

    if len(points) < 2:
        raise ValueError("Yola göre sıralamak için en az 2 joint gerekir.")

    start = _pick_start(points, preferred_start)
    order = _nearest_neighbor(points, start)
    order = _two_opt(points, order)
    return [points[index] for index in order]
