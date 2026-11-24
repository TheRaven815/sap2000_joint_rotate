"""SAP2000 OAPI adaptörünün sahte model ile testleri."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from joint_axes.errors import JointNotFoundError, SapApiError, SapConnectionError
from joint_axes.sap import SAP_PROGID, SapConnection, is_disconnected


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


def test_verify_connection_probes_cached_model_instead_of_assuming_it_is_alive():
    class CachedModel:
        calls = 0

        def GetModelIsLocked(self):
            self.calls += 1
            if self.calls > 1:
                raise OSError(-2147023170, "Remote procedure call failed")
            return True  # A locked but responsive model is still connected.

    model = CachedModel()
    connection = SapConnection(model=model, sap_object=object())
    connection.verify_connection()
    with pytest.raises(SapConnectionError, match="GetModelIsLocked") as exc:
        connection.verify_connection()
    assert is_disconnected(exc.value)
    connection.invalidate()
    assert connection._model is None
    assert connection._sap_object is None


def _fake_com_client(monkeypatch, client, interface):
    comtypes_pkg = ModuleType("comtypes")
    comtypes_pkg.client = client
    generated = ModuleType("comtypes.gen")
    generated.SAP2000v1 = SimpleNamespace(cHelper=interface)
    monkeypatch.setitem(sys.modules, "comtypes", comtypes_pkg)
    monkeypatch.setitem(sys.modules, "comtypes.client", client)
    monkeypatch.setitem(sys.modules, "comtypes.gen", generated)


def test_sapmodel_no_interface_tries_typed_helper_without_starting_sap(monkeypatch):
    class BadSapObject:
        @property
        def SapModel(self):
            raise OSError(-2147467262, "No such interface supported")

    interface = object()
    model = SimpleNamespace(GetModelIsLocked=lambda: False)
    typed = SimpleNamespace(GetObject=lambda progid: SimpleNamespace(SapModel=model))
    typed_calls = []

    def query_interface(requested):
        typed_calls.append(requested)
        return typed

    _fake_com_client(monkeypatch, SimpleNamespace(
        GetActiveObject=lambda progid: BadSapObject(),
        CreateObject=lambda progid: SimpleNamespace(QueryInterface=query_interface),
    ), interface)
    connection = SapConnection()
    assert connection.connect() is model
    assert typed_calls == [interface]
    assert connection.connection_route == f"SAP2000v1.Helper.GetObject({SAP_PROGID})"


def test_working_active_object_stays_first_and_is_not_called_as_default_member(monkeypatch):
    class CallableModel:
        def __call__(self):
            pytest.fail("A COM proxy may be callable without being a method")

        def GetModelIsLocked(self):
            return False

    model = CallableModel()
    _fake_com_client(monkeypatch, SimpleNamespace(
        GetActiveObject=lambda progid: SimpleNamespace(SapModel=model),
        CreateObject=lambda progid: pytest.fail("Unnecessary helper lookup"),
    ), object())
    connection = SapConnection()
    connection.verify_connection()
    assert connection.model is model
    assert connection.connection_route == f"GetActiveObject({SAP_PROGID})"


def test_no_interface_reports_failed_routes_and_does_not_cache_dynamic_only_model(monkeypatch):
    def fail(progid):
        raise OSError(-2147467262, "No such interface supported")

    _fake_com_client(monkeypatch, SimpleNamespace(GetActiveObject=fail, CreateObject=fail), object())
    monkeypatch.setattr(SapConnection, "_get_dispatched_object", staticmethod(
        lambda client, progid: SimpleNamespace(SapModel=SimpleNamespace(GetModelIsLocked=lambda: False)),
    ))
    connection = SapConnection()
    with pytest.raises(SapConnectionError, match=r"E_NOINTERFACE .*0x80004002") as caught:
        connection.connect()
    assert "SAP2000v1.Helper.GetObject" in str(caught.value)
    assert "Temel COM erişimi var" in str(caught.value)
    assert connection.connection_route is None


def test_coordinate_reader_stops_after_first_rpc_disconnect():
    model = ReturningModel()
    calls = []

    def disconnected(*args):
        calls.append(args)
        raise OSError(-2147023170, "Remote procedure call failed")

    model.PointObj.GetCoordCartesian = disconnected
    with pytest.raises(SapApiError) as exc:
        SapConnection(model=model).get_joint_coordinates("1")
    assert is_disconnected(exc.value)
    assert calls == [("1",)]


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
