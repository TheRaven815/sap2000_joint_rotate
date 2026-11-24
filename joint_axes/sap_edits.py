"""SAP2000'in yerel EditGeneral komutlarını çağıran UCS adaptörü."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Any

from .errors import InputValidationError, SapApiError, SapConnectionError
from .geometry import Point3
from .sap import (
    SapConnection,
    _as_int,
    _int_list,
    _string_list,
    describe_com_error,
    is_array_locked,
    is_disconnected,
    is_interface_unavailable,
    is_invalid_pointer,
)
from .transform import CoordinateSystem, NativeEdit

GLOBAL = "GLOBAL"
FRAME = 2
POINT = 1
_FRAME_TABLE = "Connectivity - Frame"
_INSERTION_TABLE = "Frame Insertion Point Assignments"
_OFFSET_FIELDS = tuple(f"JtOffset{axis}{end}" for end in "IJ" for axis in "XYZ")
_UCS_TABLE = "Coordinate Systems"

# eUnits -> aktif uzunluk birimi ve metre karşılığı.
_INCH = ("in", 0.0254)
_FOOT = ("ft", 0.3048)
_MM = ("mm", 0.001)
_CM = ("cm", 0.01)
_M = ("m", 1.0)
_LENGTH_UNITS = (_INCH, _FOOT, _INCH, _FOOT, *(_MM, _M) * 4, *(_CM,) * 4)


class _UnavailableMember(SapApiError):
    """Özellik/metot yok; çağrı sırasında oluşan hata değil."""


def _member(obj: Any, name: str, label: str) -> Any:
    try:
        result = getattr(obj, name)
    except Exception as exc:
        error = _UnavailableMember if is_interface_unavailable(exc) else SapApiError
        raise error(f"{label}: {describe_com_error(exc)}") from exc
    if result is None:
        raise _UnavailableMember(f"{label}: SAP2000 boş arabirim döndürdü.")
    return result


def _checked_call(method: Any, label: str, *args: Any, **kwargs: Any) -> Any:
    try:
        return method(*args, **kwargs)
    except Exception as exc:
        raise SapApiError(f"{label}: {describe_com_error(exc)}") from exc


def _check_code(code: Any, label: str) -> None:
    if _as_int(code) != 0:
        raise SapApiError(f"{label}: SAP2000 sonucu {code!r} (beklenen: 0).")


def _outputs(result: Any, count: int, label: str, valid: Any) -> tuple:
    """CSI/comtypes önce out değerlerini, sonra SAP dönüş kodunu verir."""
    if isinstance(result, (tuple, list)) and len(result) == count + 1:
        for values, code in ((result[:-1], result[-1]), (result[1:], result[0])):
            if _as_int(code) is not None and valid(values):
                _check_code(code, label)
                return tuple(values)
        if _as_int(result[-1]) not in (None, 0):
            _check_code(result[-1], label)
    if _as_int(result) not in (None, 0):
        _check_code(result, label)
    raise SapApiError(f"{label}: SAP2000 çıktısı okunamadı.")


def _read(method: Any, label: str, args: tuple, placeholders: tuple,
          valid: Any, **kwargs: Any) -> tuple:
    # Salt okuma: [in,out] parametreleri otomatik oluşturulamıyorsa açıkça ver.
    try:
        result = method(*args, **kwargs)
    except TypeError:
        result = _checked_call(method, label, *args, *placeholders, **kwargs)
    except Exception as exc:
        raise SapApiError(f"{label}: {describe_com_error(exc)}") from exc
    return _outputs(result, len(placeholders), label, valid)


def _names(value: Any) -> list[str] | None:
    return None if isinstance(value, str) else _string_list(value)


def _valid_objects(values: tuple, *, selection: bool) -> bool:
    count = _as_int(values[0])
    types, names = (values[1], values[2]) if selection else (values[2], values[1])
    types = [] if count == 0 and types is None else _int_list(types)
    names = [] if count == 0 and names is None else _names(names)
    return count is not None and types is not None and names is not None and (
        count == len(types) == len(names)
    )


def _vector_values(value: Any, size: int) -> tuple[float, ...] | None:
    try:
        values = tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return None
    return values if len(values) == size else None


@dataclass(frozen=True)
class ModelContext:
    path: str
    length_unit: str
    metres_per_unit: float
    generation: int


@dataclass(frozen=True)
class WorkingUcs:
    label: str = GLOBAL
    system: CoordinateSystem = CoordinateSystem()
    captured_in: ModelContext | None = None
    sap_name: str | None = GLOBAL

    def in_context(self, context: ModelContext) -> CoordinateSystem:
        if self.captured_in is None:
            return self.system
        if (self.captured_in.generation != context.generation or
                self.captured_in.path.casefold() != context.path.casefold()):
            raise InputValidationError("Model değişti veya SAP2000 yeniden bağlandı. Aktif UCS'yi yeniden seçin.")
        ratio = self.captured_in.metres_per_unit / context.metres_per_unit
        x, y, z = self.system.origin
        return CoordinateSystem((x * ratio, y * ratio, z * ratio), self.system.matrix)


@dataclass(frozen=True)
class EditReport:
    created: int | None
    warnings: tuple[str, ...]
    connection_lost: bool = False


class SapEdits:
    def __init__(self, connection: SapConnection) -> None:
        self.connection = connection

    @property
    def model(self) -> Any:
        try:
            return self.connection.model
        except SapConnectionError:
            raise
        except Exception as exc:
            raise SapConnectionError(f"SapModel: {describe_com_error(exc)}") from exc

    def _method(self, path: str) -> Any:
        owner, _, name = path.rpartition(".")
        model = self.model
        obj = _member(model, owner, f"SapModel.{owner}") if owner else model
        return _member(obj, name, path if owner else f"SapModel.{name}")

    def _call(self, path: str, *args: Any, **kwargs: Any) -> Any:
        label = path if "." in path else f"SapModel.{path}"
        return _checked_call(self._method(path), label, *args, **kwargs)

    def diagnostics(self) -> str:
        """Yalnızca bağlantı, seçim ve arabirim erişimini denetle; modele yazma."""
        lines = [f"Eklenti: {struct.calcsize('P') * 8} bit · salt okunur tanı"]

        def probe(label, action) -> bool:
            try:
                value = action()
            except Exception as exc:
                lines.append(f"{label}: HATA · {exc}")
                if is_disconnected(exc):
                    raise
                return False
            lines.append(f"{label}: {value}")
            return True

        if not probe("Bağlantı", lambda: self.connection.connect() is not None and
                     (self.connection.connection_route or "SapModel")):
            return "\n".join(lines)
        probe("SapModel.GetModelIsLocked", lambda: self._call("GetModelIsLocked"))
        probe("SapModel.GetPresentUnits", lambda: self._call("GetPresentUnits"))
        probe("SelectObj.GetSelected", lambda: f"{len(self.selection())} nesne")
        probe("SapModel.DatabaseTables", lambda: self._method("DatabaseTables.GetTableForDisplayArray") and "erişilebilir")
        probe("UCS listesi", lambda: f"{len(self.coordinate_system_names())} kullanıcı UCS'si")
        probe("SapModel.FrameObj", lambda: self._method("FrameObj.GetTransformationMatrix") and "erişilebilir")
        probe("Seçili profilden al", lambda: self.frame_ucs().label)
        probe("SapModel.EditGeneral", lambda: self._method("EditGeneral.Move") and "erişilebilir (çağrılmadı)")
        return "\n".join(lines)

    def context(self) -> ModelContext:
        path = self._call("GetModelFilename")
        units = _as_int(self._call("GetPresentUnits"))
        if not isinstance(path, str) or units is None or not 1 <= units <= len(_LENGTH_UNITS):
            raise SapApiError("SAP2000 model adı veya uzunluk birimi okunamadı.")
        return ModelContext(path, *_LENGTH_UNITS[units - 1], self.connection.generation)

    def selection(self) -> tuple[tuple[int, str], ...]:
        count, types, names = _read(
            self._method("SelectObj.GetSelected"), "SelectObj.GetSelected", (), (0, (), ()),
            lambda values: _valid_objects(values, selection=True),
        )
        if _as_int(count) == 0:
            return ()
        return tuple(zip(_int_list(types) or (), _names(names) or (), strict=True))

    def selected_joint(self, context: ModelContext) -> Point3:
        joints = [name for kind, name in self.selection() if kind == POINT]
        if len(joints) != 1:
            raise InputValidationError("SAP2000'de koordinatı alınacak tek bir joint seçin.")
        xyz = self.connection.get_joint_coordinates(joints[0]).xyz
        if self.context() != context:
            raise SapApiError("Joint okunurken model veya birim değişti. Tekrar deneyin.")
        return xyz

    def _display_rows(self, key: str, fields: tuple[str, ...]) -> list[tuple[str, ...]]:
        """SAP2000 v23+ model tablolarını seçim veya tablo ayarı değiştirmeden oku."""
        label = f'DatabaseTables.GetTableForDisplayArray("{key}")'
        method = self._method("DatabaseTables.GetTableForDisplayArray")

        # FieldKeyList ByRef girdi; comtypes onu da dönüş listesine ekler.
        # Bütün ref parametrelerini açıkça gönder; boş SAFEARRAY yerine null gönderme.
        try:
            result = _checked_call(method, label, key, fields, "", 0, (), 0, ())
        except SapApiError as exc:
            if exc.__cause__ is not None and not is_disconnected(exc) and is_interface_unavailable(exc.__cause__):
                raise _UnavailableMember(str(exc)) from exc
            raise
        if isinstance(result, (tuple, list)) and len(result) in (5, 6):
            version, headers, count, data, code = result[-5:]
            _check_code(code, label)
            count = _as_int(count)
            columns = _names(headers)
            values = _names(data)
            if count == 0 and (data is None or values == []):
                return []
            if (count is not None and count > 0 and columns and values is not None
                    and _as_int(version) is not None and len(values) == count * len(columns)):
                index = {name.strip().casefold(): i for i, name in enumerate(columns)}
                try:
                    order = tuple(index[field.casefold()] for field in fields)
                except KeyError as exc:
                    raise SapApiError(f"{label}: '{exc.args[0]}' alanı dönmedi.") from exc
                return [tuple(values[start + i] for i in order)
                        for start in range(0, len(values), len(columns))]
        if _as_int(result) not in (None, 0):
            _check_code(result, label)
        raise SapApiError(f"{label}: SAP2000 tablo çıktısı okunamadı.")

    def coordinate_system_names(self) -> tuple[str, ...]:
        try:
            names = [name for (name,) in self._display_rows(_UCS_TABLE, ("Name",))]
        except _UnavailableMember as table_error:
            try:
                _, raw_names = _outputs(
                    self._call("CoordSys.GetNameList", 0, ("",)),
                    2, "CoordSys.GetNameList", lambda v: (
                        _as_int(v[0]) == len(_names(v[1]) or ()) and
                        (v[1] is None or _names(v[1]) is not None)
                    ),
                )
            except Exception as fallback_error:
                raise SapApiError(f"{table_error}\nYedek liste okuması: {fallback_error}") from fallback_error
            names = _names(raw_names) or []
        names = (name.strip() for name in names)
        return tuple(dict.fromkeys(name for name in names if name and name.upper() != GLOBAL))

    def current_coordinate_system(self) -> str:
        name = self._call("GetPresentCoordSystem")
        if not isinstance(name, str) or not name.strip():
            raise SapApiError("SAP2000'in aktif koordinat sistemi okunamadı.")
        return name

    def named_ucs(self, name: str) -> WorkingUcs:
        if name.upper() == GLOBAL:
            return WorkingUcs()
        context = self.context()
        # GetCoordSys: global orijin ve üç skaler açı; ayrı bir COM dizisi gerekmez.
        x, y, z, rz, ry, rx = _outputs(
            self._call("CoordSys.GetCoordSys", name, *((0.0,) * 6)),
            6, "CoordSys.GetCoordSys", lambda v: _vector_values(v, 6) is not None,
        )
        system = CoordinateSystem.from_sap_rotations(
            (float(x), float(y), float(z)), float(rz), float(ry), float(rx),
        )
        if self.context() != context:
            raise SapApiError("UCS okunurken SAP2000 modeli veya birimi değişti.")
        return WorkingUcs(f"UCS: {name}", system, context, name)

    def frame_ucs(self) -> WorkingUcs:
        selection = self.selection()
        frames = [name for kind, name in selection if kind == FRAME]
        if len(frames) != 1:
            raise InputValidationError("SAP2000'de referans olarak tek bir frame/profil seçin.")
        context = self.context()
        name = frames[0]
        # Bazı v26.2 kurulumlarında GetPoints, ByRef BSTR dolu olsa da
        # RPC_E_SERVERFAULT döndürüyor. I ucunu salt okunur bağlantı tablosundan al.
        try:
            starts = [joint.strip() for frame, joint in self._display_rows(_FRAME_TABLE, ("Frame", "JointI"))
                      if frame.strip() == name]
            if len(starts) != 1 or not starts[0]:
                raise SapApiError(f"Frame '{name}' için bağlantı tablosunda tek bir I ucu bulunamadı.")
            start = starts[0]
        except _UnavailableMember as table_error:
            try:
                start = self._selected_frame_start(name, selection)
            except Exception as fallback_error:
                raise SapApiError(f"{table_error}\nYedek I ucu okuması: {fallback_error}") from fallback_error
        origin = self.connection.get_joint_coordinates(start).xyz
        label = f"Frame {name} · Local 1/2/3"
        try:
            system = CoordinateSystem.from_sap(origin, self._frame_matrix(name))
        except SapApiError as matrix_error:
            if not (is_invalid_pointer(matrix_error) or is_array_locked(matrix_error)):
                raise
            try:
                system = self._straight_frame_system(name, start, origin)
            except Exception as fallback_error:
                raise SapApiError(
                    f"{matrix_error}\nTipik eksen okuması: {fallback_error}\n"
                    "Çalışma UCS'si değişmedi. Başka bir profil veya kayıtlı UCS seçin."
                ) from fallback_error
            label += " (I/J + açı)"
        if self.context() != context:
            raise SapApiError("Profil okunurken SAP2000 modeli veya birimi değişti.")
        return WorkingUcs(label, system, context, None)

    def _straight_frame_system(self, name: str, start: str, origin: Point3) -> CoordinateSystem:
        """Matris okunmazsa yalnızca doğrulanmış tipik frame'i kullan."""
        label = "FrameObj.GetLocalAxes"
        angle, advanced = _outputs(
            self._call(label, name, 0.0, False), 2, label,
            lambda v: _vector_values(v[:1], 1) is not None and isinstance(v[1], bool),
        )
        if advanced:
            raise InputValidationError("İleri yerel eksen ataması var; SAP2000 matrisi gerekli.")

        rows = [(joint_i.strip(), joint_j.strip(), curved.strip().casefold())
                for frame, joint_i, joint_j, curved in self._display_rows(
                    _FRAME_TABLE, ("Frame", "JointI", "JointJ", "IsCurved"),
                ) if frame.strip() == name]
        if len(rows) != 1 or rows[0][0] != start or not rows[0][1]:
            raise SapApiError(f"Frame '{name}' I/J uçları doğrulanamadı.")
        if rows[0][2] not in {"no", "false", "0"}:
            raise InputValidationError("Frame'in düz olduğu doğrulanamadı; SAP2000 matrisi gerekli.")

        for frame, *offsets in self._display_rows(_INSERTION_TABLE, ("Frame", *_OFFSET_FIELDS)):
            if frame.strip() != name:
                continue
            try:
                zero_offsets = all(float(value.strip().replace(",", ".")) == 0.0 for value in offsets)
            except ValueError:
                zero_offsets = False
            if not zero_offsets:
                raise InputValidationError("Joint offsetleri sıfır değil veya okunamadı; SAP2000 matrisi gerekli.")

        end = self.connection.get_joint_coordinates(rows[0][1]).xyz
        return CoordinateSystem.from_straight_frame(origin, end, float(angle))

    def _frame_matrix(self, name: str) -> tuple[float, ...]:
        label = "FrameObj.GetTransformationMatrix"
        method = self._method(label)
        # Value is [in,out] in CSI's type library. Omitting it lets comtypes
        # supply a pointer to a null SAFEARRAY: the server allocates the result.
        # A Python tuple preallocates the array, which can cause ARRAYISLOCKED
        # when SAP2000 replaces/resizes it across COM. Never pass that tuple.
        result = _checked_call(method, label, name, IsGlobal=True)
        (matrix,) = _outputs(result, 1, label, lambda v: _vector_values(v[0], 9) is not None)
        return tuple(float(value) for value in matrix)

    def _selected_frame_start(self, frame: str, selection: tuple[tuple[int, str], ...]) -> str:
        joints = [name for kind, name in selection if kind == POINT]
        if not joints:
            raise InputValidationError(f"Frame '{frame}' ile birlikte I ucundaki jointi seçin.")
        label = "PointObj.GetConnectivity"

        def valid(v: tuple) -> bool:
            return (_valid_objects(v[:3], selection=True) and
                    _as_int(v[0]) == len(_int_list(v[3]) or ()))

        for joint in joints:
            _, types, names, numbers = _outputs(
                self._call(label, joint, 0, (0,), ("",), (0,)), 4, label, valid,
            )
            for kind, name, number in zip(_int_list(types) or (), _names(names) or (),
                                          _int_list(numbers) or (), strict=True):
                if kind == FRAME and name == frame and number == 1:
                    return joint
        raise InputValidationError(f"Seçili jointler arasında Frame '{frame}' I ucu doğrulanamadı.")

    def activate_in_sap(self, ucs: WorkingUcs, context: ModelContext,
                        new_name: str | None = None) -> tuple[str, EditReport]:
        """İsteğe bağlıdır. Mevcut bir UCS'yi ezmez; frame için yeni tanım ekler."""
        if self.context() != context:
            raise SapApiError("SAP2000 modeli veya birimi değişti. Tekrar deneyin.")
        expected = ucs.in_context(context)
        name = ucs.sap_name
        created = name is None
        if created:
            name = (new_name or "").strip()
            if not name or name.casefold() in {GLOBAL.casefold(), "local"} or any(
                item.casefold() == name.casefold() for item in self.coordinate_system_names()
            ):
                raise InputValidationError("Yeni ve benzersiz bir UCS adı girin.")
            if self._call("GetModelIsLocked") is not False:
                raise SapApiError("SAP2000 modeli kilitli; yeni UCS tanımlanamaz.")
            label = f"CoordSys.SetCoordSys({name})"
            result = self._call("CoordSys.SetCoordSys", name, *expected.origin, *expected.sap_rotations())
            _check_code(result, label)
        assert name is not None
        try:
            actual = self.named_ucs(name).in_context(context)
            origin_matches = all(math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-8)
                                 for a, b in zip(expected.origin, actual.origin))
            axes_match = all(math.isclose(a, b, abs_tol=1e-7)
                             for row, target in zip(expected.matrix, actual.matrix)
                             for a, b in zip(row, target))
            if not origin_matches or not axes_match:
                raise SapApiError("SAP2000'deki UCS ile çalışma UCS'si eşleşmiyor.")
            self._set_present_system(name)
        except Exception as exc:
            extra = f" '{name}' tanımı eklendi; gerekirse SAP2000'de kaldırın." if created else ""
            raise SapApiError(f"UCS SAP2000'de etkinleştirilemedi: {exc}.{extra}") from exc

        return name, self._refresh_report(None, [])

    def apply(self, edit: NativeEdit, context: ModelContext,
              selection: tuple[tuple[int, str], ...]) -> EditReport:
        if context != self.context():
            raise SapApiError("SAP2000 modeli veya birimi değişti. İşlemi yeniden önizleyin.")
        if not selection or set(selection) != set(self.selection()):
            raise SapApiError("SAP2000 seçimi boş veya değişti. Nesneleri seçip tekrar deneyin.")
        if self._call("GetModelIsLocked") is not False:
            raise SapApiError("SAP2000 modeli kilitli veya kilit durumu okunamadı.")
        if edit.method not in {"Move", "ReplicateLinear", "ReplicateRadial", "ReplicateMirror"}:
            raise SapApiError("Desteklenmeyen SAP2000 düzenleme işlemi.")

        previous = self.current_coordinate_system()
        label = f"EditGeneral.{edit.method}"
        method = self._method(label)
        needs_global = previous.upper() != GLOBAL
        created = None
        warnings: list[str] = []
        failure: Exception | None = None
        connection_lost = False
        started = False
        try:
            if needs_global:
                self._set_present_system(GLOBAL)
                if context != self.context():
                    raise SapApiError("Koordinat sistemi geçişinde model veya birim değişti; işlem iptal edildi.")
                if set(selection) != set(self.selection()):
                    raise SapApiError("Koordinat sistemi geçişinde SAP2000 seçimi değişti; işlem iptal edildi.")
            started = True
            # Geometriyi değiştiren komut tam bir kez çağrılır; fallback/retry yok.
            if edit.method == "Move":
                _check_code(_checked_call(method, label, *edit.args), label)
            else:
                result = _checked_call(method, label, *edit.args, Remove=edit.remove)
                count, _, _ = _outputs(result, 3, label,
                                       lambda v: _valid_objects(v, selection=False))
                created = _as_int(count)
        except Exception as exc:
            failure = exc
        finally:
            if needs_global and not is_disconnected(failure):
                try:
                    if self.context().path.casefold() != context.path.casefold():
                        raise SapApiError("Aktif model değişti.")
                    self._set_present_system(previous)
                except Exception as exc:
                    connection_lost = is_disconnected(exc)
                    if failure is not None and connection_lost:
                        failure = exc
                    warnings.append(f"Önceki SAP2000 koordinat sistemi ({previous}) geri yüklenemedi: {exc}")

        if failure is not None:
            message = str(failure)
            if started:
                message += " Tekrar denemeden önce modelde değişiklik olup olmadığını kontrol edin."
            raise SapApiError(" ".join((message, *warnings))) from failure
        if connection_lost:
            return EditReport(created, tuple(warnings), True)
        return self._refresh_report(created, warnings)

    def _refresh_report(self, created: int | None, warnings: list[str]) -> EditReport:
        try:
            self.connection.refresh_view()
        except Exception as exc:
            warnings.append(str(exc))
            return EditReport(created, tuple(warnings), is_disconnected(exc))
        return EditReport(created, tuple(warnings))

    def _set_present_system(self, name: str) -> None:
        label = f"SetPresentCoordSystem({name})"
        _check_code(self._call("SetPresentCoordSystem", name), label)
