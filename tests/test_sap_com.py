"""Windows'ta comtypes ile gerçek SAFEARRAY gidiş dönüş testi."""

import sys
from ctypes import POINTER, byref, c_double, c_long, c_void_p, memmove, sizeof
from types import SimpleNamespace

import pytest

from joint_axes.errors import SapApiError
from joint_axes.sap import SapConnection, is_array_locked
from joint_axes.sap_edits import SapEdits

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows COM required")


def test_frame_matrix_lets_com_server_allocate_byref_safearray():
    pytest.importorskip("comtypes")
    from comtypes import BSTR, COMMETHOD, GUID, HRESULT, COMObject, IUnknown
    from comtypes.automation import VARIANT_BOOL
    from comtypes.safearray import _midlSAFEARRAY

    array_type = _midlSAFEARRAY(c_double)
    expected = (0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0)
    calls = []

    class IFrameProbe(IUnknown):
        _iid_ = GUID("{21cb8c3b-d9db-4aba-9ee3-0e342fcd6f77}")
        _methods_ = [
            COMMETHOD(
                [], HRESULT, "GetTransformationMatrix",
                (["in"], BSTR, "Name"),
                (["in", "out"], POINTER(array_type), "Value"),
                (["in"], VARIANT_BOOL, "IsGlobal"),
                (["out", "retval"], POINTER(c_long), "pRetVal"),
            ),
        ]

    class FrameProbe(COMObject):
        _com_interfaces_ = [IFrameProbe]

        def IFrameProbe_GetTransformationMatrix(self, this, name, values, globally, ret):
            calls.append((name, bool(values[0]), bool(globally)))
            if values[0]:
                return -2147352563  # DISP_E_ARRAYISLOCKED
            result = array_type.create(expected)
            # Transfer the SAFEARRAY pointer to the caller, not its Python wrapper.
            memmove(values, byref(result), sizeof(c_void_p))
            ret[0] = 0
            return 0

    server = FrameProbe()
    frame = server.QueryInterface(IFrameProbe)
    sap = SapEdits(SapConnection(model=SimpleNamespace(FrameObj=frame)))

    with pytest.raises(SapApiError) as previous_call:
        sap._call("FrameObj.GetTransformationMatrix", "37", (0.0,) * 9, True)
    assert is_array_locked(previous_call.value)
    assert sap._frame_matrix("37") == expected
    assert calls == [("37", True, True), ("37", False, True)]
