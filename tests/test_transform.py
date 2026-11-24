import math

import pytest

from joint_axes.errors import InputValidationError
from joint_axes.transform import CoordinateSystem, mirror, radial, translation

# Right-handed SAP matrix with unequal off-diagonal entries to catch transposes.
FRAME = CoordinateSystem.from_sap((10, 20, 30), (0, 0, 1, 1, 0, 0, 0, 1, 0))


def test_sap_matrix_maps_local_displacements_by_rows_without_origin():
    assert translation(FRAME, (2, 3, 4)).args == (4, 2, 3)
    assert translation(FRAME, (2, 3, 4), 3, True).args == (4, 2, 3, 3)
    assert translation(FRAME, (2, 3, 4), 3, True).remove


def test_origin_applies_to_points_only_and_inverse_recovers_local_coordinates():
    global_point = FRAME.global_point((2, 3, 4))
    assert global_point == (14, 22, 33)
    assert FRAME.local_point(global_point) == (2, 3, 4)


def test_radial_axis_maps_both_points_before_native_rotation():
    edit = radial(FRAME, (1, 2, 0), (1, 2, 3), -45, 3)
    assert edit.method == "ReplicateRadial"
    assert edit.args == (4, 10, 21, 32, 13, 21, 32, 3, -45)


def test_mirror_maps_all_plane_points():
    edit = mirror(FRAME, (1, 0, 0), (1, 2, 0), (1, 0, 3))
    assert edit.method == "ReplicateMirror"
    assert edit.args == (4, 10, 21, 30, 10, 21, 32, 13, 21, 30)


def rotated(rz, ry, rx):
    """Independent construction of Rx(Ry(Rz(v))) for CSI's fixed axes."""
    rz, ry, rx = map(math.radians, (rz, ry, rx))
    sz, sy, sx = map(math.sin, (rz, ry, rx))
    cz, cy, cx = map(math.cos, (rz, ry, rx))
    cols = []
    for x, y, z in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
        x, y = cz * x - sz * y, sz * x + cz * y
        x, z = cy * x + sy * z, -sy * x + cy * z
        y, z = cx * y - sx * z, sx * y + cx * z
        cols.append((x, y, z))
    return CoordinateSystem(matrix=tuple(zip(*cols, strict=True)))


@pytest.mark.parametrize("angles", [(23, 41, -56), (90, 0, 0), (28, 90, 46), (28, -90, 46)])
def test_sap_euler_angles_rebuild_original_matrix_at_regular_and_singular_angles(angles):
    system = rotated(*angles)
    rebuilt = rotated(*system.sap_rotations())
    for actual, expected in zip(rebuilt.matrix, system.matrix, strict=True):
        assert actual == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize("count", [0, -1, True, 2.5, 2**31])
def test_invalid_copy_counts_are_rejected(count):
    with pytest.raises(InputValidationError, match="Kopya sayısı"):
        translation(FRAME, (1, 2, 3), count)


@pytest.mark.parametrize("delta", [(0, 0, 0), (math.nan, 0, 0), (math.inf, 0, 0)])
def test_invalid_and_zero_translations_are_rejected(delta):
    with pytest.raises(InputValidationError):
        translation(FRAME, delta)


def test_degenerate_line_and_plane_are_rejected():
    with pytest.raises(InputValidationError, match="farklı noktalar"):
        radial(FRAME, (0, 0, 0), (0, 0, 0), 90, 2)
    with pytest.raises(InputValidationError, match="aynı doğru"):
        mirror(FRAME, (0, 0, 0), (0, 0, 1), (0, 0, 5))
    with pytest.raises(InputValidationError, match="Açı"):
        radial(FRAME, (0, 0, 0), (0, 0, 1), 360, 2)


def test_left_handed_matrix_cannot_be_used():
    with pytest.raises(InputValidationError, match="sağ el"):
        CoordinateSystem.from_sap((0, 0, 0), (0, 1, 0, 1, 0, 0, 0, 0, 1))
