"""SAP2000 OAPI adaptörünün sahte model ile testleri."""

from __future__ import annotations

import pytest

from joint_axes.errors import JointNotFoundError, SapApiError
from joint_axes.sap import SapConnection


class FakePointObj:
    def __init__(self) -> None:
        self.coords = {
            "1": (0.0, 0.0, 0.0),
            "2": (1.0, 1.0, 0.0),
            "3": (2.0, 0.0, 0.0),
        }
        self.names = ["1", "2", "3"]
        self.selected = {"1", "3"}
        self.set_calls: list[tuple[str, float, float, float]] = []
        self.fail_set_for: set[str] = set()

    def GetCoordCartesian(self, name: str, *args: object):
        if len(args) != 3 or not all(isinstance(value, float) for value in args):
            raise TypeError("fake yalnizca deger tabanli cagriyi destekler")
        if name not in self.coords:
            return 1, 0.0, 0.0, 0.0
        x, y, z = self.coords[name]
        return 0, x, y, z

    def GetNameList(self, *args: object):
        if args:
            raise TypeError("fake cikis parametresi desteklemez")
        return 0, len(self.names), list(self.names)

    def GetSelected(self, *args: object):
        if args:
            raise TypeError("fake cikis parametresi desteklemez")
        return 0, len(self.names), [1, 1, 1], list(self.names)

    def SetLocalAxes(self, name: str, a: float, b: float, c: float):
        if name in self.fail_set_for:
            return 1
        self.set_calls.append((name, a, b, c))
        return 0


class FakeSelectObj:
    def __init__(self, point_obj: FakePointObj) -> None:
        self.point_obj = point_obj

    def GetSelected(self, *args: object):
        if args:
            raise TypeError("fake cikis parametresi desteklemez")
        names = [
            name for name in self.point_obj.names if name in self.point_obj.selected
        ]
        types = [1] * len(names)
        return 0, len(names), types, names


class FakeView:
    def __init__(self) -> None:
        self.refresh_calls = 0

    def RefreshView(self, window: int, zoom: bool):
        self.refresh_calls += 1
        return 0


class FakeModel:
    def __init__(self) -> None:
        self.PointObj = FakePointObj()
        self.SelectObj = FakeSelectObj(self.PointObj)
        self.View = FakeView()


class OutParamNamePointObj(FakePointObj):
    """GetNameList cikis dizisini yerinde dolduran sahte API."""

    def GetNameList(self, count: int, names: list[str]):
        names.extend(self.names)
        return 0


class OutParamSelectObj:
    def GetSelected(self, count: int, types: list[int], names: list[str]):
        selected = ["1", "3"]
        types.extend([1, 2])
        names.extend(selected)
        return 0


class OutParamModel:
    def __init__(self) -> None:
        self.PointObj = OutParamNamePointObj()
        self.SelectObj = OutParamSelectObj()
        self.View = FakeView()


class ReturningPointObj(FakePointObj):
    """comtypes ref dönüşlerini [değerler..., ret] olarak veren sahte API."""

    def GetCoordCartesian(self, name: str, *args: object):
        if args:
            raise TypeError("ref argumani beklenmiyor")
        if name not in self.coords:
            return [0, 0, 0, 1]
        x, y, z = self.coords[name]
        return [x, y, z, 0]

    def GetNameList(self, *args: object):
        if args:
            raise TypeError("ref argumani beklenmiyor")
        return [len(self.names), list(self.names), 0]


class ReturningSelectObj:
    def GetSelected(self, *args: object):
        if args:
            raise TypeError("ref argumani beklenmiyor")
        types = [1, 1]
        names = ["1", "3"]
        return [len(names), types, names, 0]


class ReturningModel:
    def __init__(self) -> None:
        self.PointObj = ReturningPointObj()
        self.SelectObj = ReturningSelectObj()
        self.View = FakeView()


def test_reads_coordinates_through_value_call_style() -> None:
    model = FakeModel()
    connection = SapConnection(model=model)

    point = connection.get_joint_coordinates("2")

    assert point.name == "2"
    assert (point.x, point.y, point.z) == (1.0, 1.0, 0.0)


def test_reads_coordinates_from_comtypes_return_list() -> None:
    connection = SapConnection(model=ReturningModel())

    point = connection.get_joint_coordinates("2")

    assert (point.x, point.y, point.z) == (1.0, 1.0, 0.0)


def test_missing_joint_raises_joint_not_found() -> None:
    connection = SapConnection(model=FakeModel())

    with pytest.raises(JointNotFoundError, match="99"):
        connection.get_joint_coordinates("99")


def test_missing_joint_with_return_list_code() -> None:
    connection = SapConnection(model=ReturningModel())

    with pytest.raises(JointNotFoundError, match="99"):
        connection.get_joint_coordinates("99")


def test_names_and_selection_from_comtypes_return_lists() -> None:
    connection = SapConnection(model=ReturningModel())

    assert connection.get_joint_names() == ["1", "2", "3"]
    assert connection.get_selected_joint_names() == ["1", "3"]


def test_joint_names() -> None:
    connection = SapConnection(model=FakeModel())
    assert connection.get_joint_names() == ["1", "2", "3"]


def test_joint_names_from_in_place_out_parameters() -> None:
    connection = SapConnection(model=OutParamModel())
    assert connection.get_joint_names() == ["1", "2", "3"]


def test_selected_joints_are_filtered_by_object_type() -> None:
    connection = SapConnection(model=FakeModel())
    assert connection.get_selected_joint_names() == ["1", "3"]


def test_selected_joints_from_in_place_out_parameters() -> None:
    connection = SapConnection(model=OutParamModel())
    assert connection.get_selected_joint_names() == ["1"]


def test_selected_joints_fallback_to_point_flags() -> None:
    model = FakeModel()

    class BrokenSelect:
        def GetSelected(self, *args: object):
            raise TypeError("secim listesi okunamaz")

    def point_selected(name: str):
        return name in model.PointObj.selected

    model.SelectObj = BrokenSelect()
    model.PointObj.GetSelected = point_selected  # type: ignore[method-assign]

    connection = SapConnection(model=model)
    assert connection.get_selected_joint_names() == ["1", "3"]


def test_set_local_axes_uses_a_angle_and_zero_b_c() -> None:
    model = FakeModel()
    connection = SapConnection(model=model)

    connection.set_local_axes("2", 45.25)

    assert model.PointObj.set_calls == [("2", 45.25, 0.0, 0.0)]


def test_set_local_axes_sends_all_three_angles() -> None:
    model = FakeModel()
    connection = SapConnection(model=model)

    connection.set_local_axes("2", 90.0, 90.0, 0.0)

    assert model.PointObj.set_calls == [("2", 90.0, 90.0, 0.0)]


def test_set_local_axes_error_code_is_reported() -> None:
    model = FakeModel()
    model.PointObj.fail_set_for.add("2")
    connection = SapConnection(model=model)

    with pytest.raises(SapApiError, match="hata kodu 1"):
        connection.set_local_axes("2", 45.0)


def test_refresh_view() -> None:
    model = FakeModel()
    connection = SapConnection(model=model)

    connection.refresh_view()

    assert model.View.refresh_calls == 1
