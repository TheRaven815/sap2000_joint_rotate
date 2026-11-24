from types import SimpleNamespace

import pytest

from joint_axes.errors import InputValidationError, SapApiError
from joint_axes.sap import SapConnection, is_array_locked, is_disconnected
from joint_axes.sap_edits import SapEdits, WorkingUcs
from joint_axes.transform import mirror, radial, translation

MATRIX = (0, 0, 1, 1, 0, 0, 0, 1, 0)
ROTATIONS = (90.0, 90.0, 0.0)


class DemoModel:
    def __init__(self):
        self.path = "C:/model.sdb"
        self.units = 6
        self.present = "OTHER"
        self.selected = [(2, "F1"), (1, "J1")]
        self.locked = False
        self.events = []
        self.edit_status = 0
        self.system_status = {}
        self.frame_joints = {"F1": "J1"}
        self.systems = {"OTHER": ((10.0, 20.0, 30.0), ROTATIONS), "SLOPE": ((20.0, 30.0, 40.0), ROTATIONS)}
        self.EditGeneral = SimpleNamespace(Move=self._move)
        for name in ("ReplicateLinear", "ReplicateRadial", "ReplicateMirror"):
            setattr(self.EditGeneral, name, self._replicator(name))
        self.SelectObj = SimpleNamespace(GetSelected=self._selection)
        self.FrameObj = SimpleNamespace(
            GetTransformationMatrix=self._frame_matrix,
            GetPoints=lambda *args: pytest.fail("FrameObj.GetPoints is not safe on SAP2000 v26.2"),
        )
        self.PointObj = SimpleNamespace(GetCoordCartesian=lambda name: (5.0, 6.0, 7.0, 0))
        self.DatabaseTables = SimpleNamespace(GetTableForDisplayArray=self._display_table)
        self.CoordSys = SimpleNamespace(
            GetNameList=lambda *args: pytest.fail("UCS list must come from the display table"),
            GetCoordSys=self._get_coordinate_system,
            GetTransformationMatrix=lambda *args: pytest.fail("Named UCS uses scalar rotations"),
            SetCoordSys=self._create_system,
        )
        self.View = SimpleNamespace(RefreshView=self._refresh)

    def _selection(self):
        return len(self.selected), tuple(x[0] for x in self.selected), tuple(x[1] for x in self.selected), 0

    def _display_table(self, key, fields, group, version, included, count, data):
        assert (group, version, included, count, data) == ("", 0, (), 0, ())
        if key == "Connectivity - Frame":
            assert fields == ("Frame", "JointI")
            # Column order in SAP2000 output can differ from the requested order.
            headers = ("JointI", "Frame")
            values = tuple(cell for frame, joint in self.frame_joints.items() for cell in (joint, frame))
        else:
            assert key == "Coordinate Systems" and fields == ("Name",)
            headers = fields
            values = ("GLOBAL", *self.systems)
        return fields, 1, headers, len(values) // len(headers), values, 0

    def _get_coordinate_system(self, name, *values):
        assert values == (0.0,) * 6
        origin, rotations = self.systems[name]
        return *origin, *rotations, 0

    def _frame_matrix(self, name, values=None, IsGlobal=True):
        if values is not None:
            raise OSError(-2147352563, "Array is locked")
        assert IsGlobal is True
        assert name == "F1"
        return MATRIX, 0

    def GetModelFilename(self):
        return self.path

    def GetPresentUnits(self):
        return self.units

    def GetModelIsLocked(self):
        return self.locked

    def GetPresentCoordSystem(self):
        return self.present

    def SetPresentCoordSystem(self, name):
        self.events.append(("system", name))
        status = self.system_status.get(name, 0)
        if status == 0:
            self.present = name
        return status

    def _create_system(self, name, x, y, z, rz, ry, rx):
        self.events.append(("create", name, (x, y, z), (rz, ry, rx)))
        self.systems[name] = ((x, y, z), (rz, ry, rx))
        return 0

    def _move(self, *args):
        self.events.append(("Move", self.present, args))
        return self.edit_status

    def _replicator(self, name):
        def call(*args, Remove):
            self.events.append((name, self.present, args, Remove))
            return 2, ("J2", "F2"), (1, 2), self.edit_status
        return call

    def _refresh(self, window, zoom):
        self.events.append(("refresh", self.present))
        return 0


@pytest.fixture
def sap():
    model = DemoModel()
    return SapEdits(SapConnection(model=model))


class MissingDatabaseTables(DemoModel):
    @property
    def DatabaseTables(self):
        raise OSError(-2147467262, "No such interface supported")

    @DatabaseTables.setter
    def DatabaseTables(self, _value):
        pass


def test_no_database_interface_uses_point_connectivity_not_get_points():
    model = MissingDatabaseTables()
    model.selected = [(1, "J2"), (2, "F1"), (1, "J1")]
    origins = []

    def connectivity(name, count, kinds, names, positions):
        assert (count, kinds, names, positions) == (0, (0,), ("",), (0,))
        return (1, (2,), ("F1",), (1 if name == "J1" else 2,), 0)

    def coords(name):
        origins.append(name)
        return (5, 6, 7, 0)

    model.PointObj.GetConnectivity = connectivity
    model.PointObj.GetCoordCartesian = coords
    sap = SapEdits(SapConnection(model=model))
    assert sap.frame_ucs().system.origin == (5, 6, 7)
    assert origins == ["J1"]
    assert model.events == []


def test_no_table_and_no_joint_reports_required_i_end():
    model = MissingDatabaseTables()
    model.selected = [(2, "F1")]
    with pytest.raises(SapApiError, match="I ucundaki jointi seçin") as caught:
        SapEdits(SapConnection(model=model)).frame_ucs()
    assert "SapModel.DatabaseTables: E_NOINTERFACE (0x80004002)" in str(caught.value)


def test_no_database_interface_reads_named_systems_through_explicit_ref_args():
    model = MissingDatabaseTables()

    def name_list(count, names):
        assert (count, names) == (0, ("",))
        return 3, ("Global", "Slope", "Grid"), 0

    model.CoordSys.GetNameList = name_list
    assert SapEdits(SapConnection(model=model)).coordinate_system_names() == ("Slope", "Grid")


def test_table_method_no_interface_also_uses_ucs_name_fallback(sap):
    def fail(*args):
        raise OSError(-2147467262, "No such interface supported")

    sap.model.DatabaseTables.GetTableForDisplayArray = fail
    sap.model.CoordSys.GetNameList = lambda *args: (1, ("Grid",), 0)
    assert sap.coordinate_system_names() == ("Grid",)


def test_table_server_fault_is_not_mistaken_for_unsupported_interface(sap):
    def fail(*args):
        raise OSError(-2147417851, "The server threw an exception")

    sap.model.DatabaseTables.GetTableForDisplayArray = fail
    with pytest.raises(SapApiError, match=r"Coordinate Systems.*0x80010105"):
        sap.coordinate_system_names()


def test_unlabeled_com_error_from_selection_property_gets_operation_name():
    class BadSelect(DemoModel):
        @property
        def SelectObj(self):
            raise OSError(-2147467262, "No such interface supported")

        @SelectObj.setter
        def SelectObj(self, _value):
            pass

    sap = SapEdits(SapConnection(model=BadSelect()))
    with pytest.raises(SapApiError, match=r"SapModel.SelectObj: E_NOINTERFACE \(0x80004002\)"):
        sap.frame_ucs()


def test_read_only_diagnostics_distinguishes_table_access_from_base_connection(sap):
    report = sap.diagnostics()
    assert "Bağlantı: Hazır SapModel" in report
    assert "SelectObj.GetSelected: 2 nesne" in report
    assert "SapModel.DatabaseTables: erişilebilir" in report
    assert "SapModel.EditGeneral: erişilebilir (çağrılmadı)" in report
    assert not sap.model.events


def test_frame_reference_is_read_only_and_remains_fixed_after_selection_changes(sap):
    reference = sap.frame_ucs()
    assert reference.label == "Frame F1 · Local 1/2/3"
    assert reference.system.origin == (5, 6, 7)
    assert reference.system.global_vector((2, 3, 4)) == (4, 2, 3)
    assert not sap.model.events
    sap.model.selected = [(5, "Area1")]
    context = sap.context()
    report = sap.apply(translation(reference.in_context(context), (2, 0, 0)), context, sap.selection())
    assert report.created is None
    assert sap.model.events == [
        ("system", "GLOBAL"), ("Move", "GLOBAL", (0, 2, 0)),
        ("system", "OTHER"), ("refresh", "OTHER"),
    ]


def test_named_ucs_and_present_ucs_are_read_without_mutations(sap):
    assert sap.coordinate_system_names() == ("OTHER", "SLOPE")
    assert sap.current_coordinate_system() == "OTHER"
    ref = sap.named_ucs("SLOPE")
    assert ref.label == "UCS: SLOPE"
    assert ref.system.global_point((1, 2, 3)) == (23, 31, 42)
    assert not sap.model.events


def test_reference_origin_scales_when_sap_present_units_change(sap):
    reference = sap.frame_ucs()
    sap.model.units = 5  # m -> mm
    system = reference.in_context(sap.context())
    assert system.global_point((1, 2, 3)) == (5003, 6001, 7002)


@pytest.mark.parametrize("mode", ["linear", "radial", "mirror"])
def test_native_replication_call_once_in_global_and_returns_created_count(sap, mode):
    ucs = sap.frame_ucs().system
    edit = {
        "linear": lambda: translation(ucs, (1, 0, 0), 2),
        "radial": lambda: radial(ucs, (0, 0, 0), (1, 0, 0), 90, 2),
        "mirror": lambda: mirror(ucs, (0, 0, 0), (1, 0, 0), (0, 1, 0), True),
    }[mode]()
    report = sap.apply(edit, sap.context(), sap.selection())
    assert report.created == 2
    assert sap.model.events[1] == (edit.method, "GLOBAL", edit.args, mode == "mirror")
    assert len(sap.model.events) == 4


@pytest.mark.parametrize("issue", ["empty", "changed_selection", "locked", "changed_units", "changed_path"])
def test_no_write_for_invalid_or_changed_context(sap, issue):
    context = sap.context()
    selection = sap.selection()
    if issue == "empty":
        sap.model.selected = []
        selection = ()
    if issue == "changed_selection":
        sap.model.selected = [(7, "Link1")]
    if issue == "locked":
        sap.model.locked = True
    if issue == "changed_units":
        sap.model.units = 1
    if issue == "changed_path":
        sap.model.path = "C:/other.sdb"
    with pytest.raises(SapApiError):
        sap.apply(translation(WorkingUcs().system, (1, 0, 0)), context, selection)
    assert not sap.model.events


def test_failed_edit_restores_original_coordinate_system_without_retry(sap):
    sap.model.edit_status = 13
    edit = translation(WorkingUcs().system, (1, 0, 0), 2)
    with pytest.raises(SapApiError, match=r"13.*Tekrar denemeden önce"):
        sap.apply(edit, sap.context(), sap.selection())
    assert sap.model.events == [
        ("system", "GLOBAL"), ("ReplicateLinear", "GLOBAL", edit.args, False), ("system", "OTHER"),
    ]


def test_failed_global_switch_does_not_edit(sap):
    sap.model.system_status["GLOBAL"] = 1
    with pytest.raises(SapApiError, match="SetPresentCoordSystem"):
        sap.apply(translation(WorkingUcs().system, (1, 0, 0)), sap.context(), sap.selection())
    assert sap.model.events == [("system", "GLOBAL"), ("system", "OTHER")]


def test_selection_changed_on_system_switch_does_not_move_wrong_objects(sap):
    set_system = sap.model.SetPresentCoordSystem

    def switch_and_clear(name):
        sap.model.selected = []
        return set_system(name)

    sap.model.SetPresentCoordSystem = switch_and_clear
    with pytest.raises(SapApiError, match="seçimi değişti"):
        sap.apply(translation(WorkingUcs().system, (1, 0, 0)), sap.context(), sap.selection())
    assert sap.model.events == [("system", "GLOBAL"), ("system", "OTHER")]


def test_failed_restore_after_success_does_not_report_edit_failure(sap):
    sap.model.system_status["OTHER"] = 1
    edit = translation(WorkingUcs().system, (1, 0, 0))
    report = sap.apply(edit, sap.context(), sap.selection())
    assert len(report.warnings) == 1
    assert "geri yüklenemedi" in report.warnings[0]


def test_coordinate_reference_from_different_file_requires_new_selection(sap):
    ref = sap.frame_ucs()
    sap.model.path = "C:/other.sdb"
    with pytest.raises(InputValidationError, match="Model değişti"):
        ref.in_context(sap.context())


def test_frame_origin_comes_from_frame_37_i_end_not_selected_joint(sap):
    origin = (-11885.375, 3429.1864, 0.0)
    sap.model.units = 5
    sap.model.frame_joints = {"99": "OTHER", "37": "33"}
    sap.model.selected = [(1, "33"), (2, "37")]

    def coordinates(name):
        assert name == "33"
        return (*origin, 0)

    def matrix(name, *, IsGlobal):
        assert name == "37" and IsGlobal is True
        return (0, 1, 0, 0, 0, 1, 1, 0, 0), 0

    sap.model.PointObj.GetCoordCartesian = coordinates
    sap.model.FrameObj.GetTransformationMatrix = matrix
    for picked in (sap.model.selected, [(1, "OTHER"), (2, "37")], [(2, "37")]):
        sap.model.selected = picked
        ucs = sap.frame_ucs()
        assert ucs.label == "Frame 37 · Local 1/2/3"
        assert ucs.system.origin == origin
        assert translation(ucs.system, (500, 0, 0)).args == (0, 0, 500)
    assert not sap.model.events


def test_locked_com_array_does_not_retry_or_invent_frame_axes(sap):
    calls = []

    def matrix(name, *, IsGlobal):
        calls.append((name, IsGlobal))
        raise OSError(-2147352563, "Array is locked")

    sap.model.FrameObj.GetTransformationMatrix = matrix
    with pytest.raises(SapApiError, match="DISP_E_ARRAYISLOCKED") as caught:
        sap.frame_ucs()
    assert is_array_locked(caught.value)
    assert calls == [("F1", True)]
    assert not sap.model.events


def _vertical_frame_with_failed_matrix(sap, *, curved="No", advanced=False,
                                       offsets=("0",) * 6, angle=30.0):
    model = sap.model
    model.units = 5
    model.selected = [(1, "33"), (2, "37")]
    model.frame_joints = {"37": "33"}
    calls = []
    origin = (-11885.375, 3429.1864, 0.0)
    model.PointObj.GetCoordCartesian = lambda joint: (
        *origin[:2], {"33": 0.0, "34": 3100.0}[joint], 0,
    )

    def broken_matrix(name, *, IsGlobal):
        calls.append((name, IsGlobal))
        raise OSError(-2147467261, "Object reference not set to an instance of an object")

    def display_table(key, fields, *args):
        if key == "Connectivity - Frame" and len(fields) == 4:
            assert fields == ("Frame", "JointI", "JointJ", "IsCurved")
            return fields, 1, fields, 1, ("37", "33", "34", curved), 0
        if key == "Frame Insertion Point Assignments":
            assert fields == ("Frame", "JtOffsetXI", "JtOffsetYI", "JtOffsetZI",
                              "JtOffsetXJ", "JtOffsetYJ", "JtOffsetZJ")
            return fields, 1, fields, 1, ("37", *offsets), 0
        return model._display_table(key, fields, *args)

    def local_axes(name, default_angle, default_advanced):
        assert (name, default_angle, default_advanced) == ("37", 0.0, False)
        return angle, advanced, 0

    model.FrameObj.GetTransformationMatrix = broken_matrix
    model.FrameObj.GetLocalAxes = local_axes
    model.DatabaseTables.GetTableForDisplayArray = display_table
    return origin, calls


def test_invalid_pointer_uses_verified_frame_ij_and_scalar_angle(sap):
    origin, calls = _vertical_frame_with_failed_matrix(sap)
    ref = sap.frame_ucs()
    assert ref.label == "Frame 37 · Local 1/2/3 (I/J + açı)"
    assert ref.system.origin == origin
    assert ref.system.global_vector((500, 0, 0)) == (0, 0, 500)
    assert ref.system.global_vector((0, 1, 0)) == pytest.approx((0.8660254038, 0.5, 0))
    assert ref.system.global_vector((0, 0, 1)) == pytest.approx((-0.5, 0.8660254038, 0))
    assert calls == [("37", True)]
    assert not sap.model.events


@pytest.mark.parametrize(("kwargs", "reason"), [
    ({"advanced": True}, "İleri yerel eksen"),
    ({"curved": "Yes"}, "düz olduğu doğrulanamadı"),
    ({"curved": ""}, "düz olduğu doğrulanamadı"),
    ({"offsets": ("0", "0", "0", "0", "0,5", "0")}, "Joint offsetleri"),
    ({"offsets": ("0", "0", "0", "0", "", "0")}, "Joint offsetleri"),
])
def test_invalid_pointer_refuses_unverified_typical_frame(sap, kwargs, reason):
    _vertical_frame_with_failed_matrix(sap, **kwargs)
    with pytest.raises(SapApiError, match=reason) as caught:
        sap.frame_ucs()
    assert "0x80004003" in str(caught.value)
    assert "Çalışma UCS'si değişmedi" in str(caught.value)
    assert not sap.model.events


def test_invalid_pointer_can_use_frame_with_no_insertion_assignment(sap):
    _vertical_frame_with_failed_matrix(sap, angle=0.0)
    display_table = sap.model.DatabaseTables.GetTableForDisplayArray

    def absent_insertion(key, *args):
        if key == "Frame Insertion Point Assignments":
            return 0, None, 0, None, 0
        return display_table(key, *args)

    sap.model.DatabaseTables.GetTableForDisplayArray = absent_insertion
    assert sap.frame_ucs().system.global_vector((0, 1, 0)) == (1, 0, 0)


def test_frame_not_found_in_table_does_not_guess_i_end_from_selected_joint(sap):
    sap.model.frame_joints.clear()
    sap.model.PointObj.GetCoordCartesian = lambda *args: pytest.fail("Do not use selected joint as fallback")
    with pytest.raises(SapApiError, match="tek bir I ucu"):
        sap.frame_ucs()


def test_ucs_list_accepts_empty_table_result_without_field_keys_echo(sap):
    sap.model.DatabaseTables.GetTableForDisplayArray = lambda *args: (0, None, 0, None, 0)
    assert sap.coordinate_system_names() == ()


def test_ucs_list_reports_bad_table_return_rather_than_showing_empty_list(sap):
    sap.model.DatabaseTables.GetTableForDisplayArray = lambda *args: (0, None, 0, None, 52)
    with pytest.raises(SapApiError, match=r"Coordinate Systems.*52"):
        sap.coordinate_system_names()


def test_malformed_connectivity_table_cannot_supply_a_frame_origin(sap):
    sap.model.DatabaseTables.GetTableForDisplayArray = lambda *args: (
        1, ("Frame", "JointJ"), 1, ("F1", "J2"), 0,
    )
    with pytest.raises(SapApiError, match="jointi"):
        sap.frame_ucs()
    assert not sap.model.events


def test_table_rpc_failure_does_not_retry_or_continue_to_matrix(sap):
    calls = []

    def fail(*args):
        calls.append(args)
        raise OSError(-2147023170, "Remote procedure call failed")

    sap.model.DatabaseTables.GetTableForDisplayArray = fail
    sap.model.FrameObj.GetTransformationMatrix = lambda *args: pytest.fail("COM read after RPC failure")
    with pytest.raises(SapApiError, match="Connectivity - Frame") as exc:
        sap.frame_ucs()
    assert is_disconnected(exc.value)
    assert calls == [("Connectivity - Frame", ("Frame", "JointI"), "", 0, (), 0, ())]


def test_frame_snapshot_is_rejected_after_reconnecting_to_same_file(sap):
    ref = sap.frame_ucs()
    assert ref.captured_in is not None
    model = sap.model
    sap.connection.invalidate()
    # Simulate the same file reopened on a fresh server.
    sap.connection._model = model
    with pytest.raises(InputValidationError, match="yeniden bağlandı"):
        ref.in_context(sap.context())


def test_rpc_failure_on_edit_does_not_restore_or_refresh_dead_server(sap):
    def fail(*args):
        sap.model.events.append(("failed", *args))
        raise OSError(-2147023170, "Remote procedure call failed")

    sap.model.EditGeneral.Move = fail
    with pytest.raises(SapApiError, match="Tekrar denemeden önce") as exc:
        sap.apply(translation(WorkingUcs().system, (1, 0, 0)), sap.context(), sap.selection())
    assert is_disconnected(exc.value)
    assert sap.model.events == [("system", "GLOBAL"), ("failed", 1, 0, 0)]


def test_activate_frame_defines_and_verifies_unique_ucs(sap):
    ref = sap.frame_ucs()
    with pytest.raises(InputValidationError, match="benzersiz"):
        sap.activate_in_sap(ref, sap.context(), "other")
    assert not sap.model.events
    name, report = sap.activate_in_sap(ref, sap.context(), "FRAME_UCS")
    assert name == "FRAME_UCS" and not report.warnings
    assert sap.model.events == [
        ("create", "FRAME_UCS", (5, 6, 7), (90, 90, 0)),
        ("system", "FRAME_UCS"), ("refresh", "FRAME_UCS"),
    ]


def test_activate_existing_ucs_does_not_redefine_it(sap):
    ref = sap.named_ucs("SLOPE")
    name, report = sap.activate_in_sap(ref, sap.context())
    assert name == "SLOPE" and not report.warnings
    assert sap.model.events == [("system", "SLOPE"), ("refresh", "SLOPE")]
