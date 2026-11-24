"""SAP2000'in yerel EditGeneral komutlarını çağıran UCS adaptörü."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .errors import InputValidationError, SapApiError
from .geometry import Point3
from .sap import SapConnection, _as_int, _int_list, _string_list, is_disconnected
from .transform import CoordinateSystem, NativeEdit

GLOBAL = "GLOBAL"
FRAME = 2
POINT = 1
_FRAME_TABLE = "Connectivity - Frame"
_UCS_TABLE = "Coordinate Systems"

# eUnits -> aktif uzunluk birimi ve metre karşılığı.
_INCH = ("in", 0.0254)
_FOOT = ("ft", 0.3048)
_MM = ("mm", 0.001)
_CM = ("cm", 0.01)
_M = ("m", 1.0)
_LENGTH_UNITS = (_INCH, _FOOT, _INCH, _FOOT, *(_MM, _M) * 4, *(_CM,) * 4)


def _checked_call(method: Any, label: str, *args: Any, **kwargs: Any) -> Any:
    try:
        return method(*args, **kwargs)
    except Exception as exc:
        raise SapApiError(f"{label}: {exc}") from exc


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
        raise SapApiError(f"{label}: {exc}") from exc
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
        return self.connection.model

    def context(self) -> ModelContext:
        path = self.model.GetModelFilename()
        units = _as_int(self.model.GetPresentUnits())
        if not isinstance(path, str) or units is None or not 1 <= units <= len(_LENGTH_UNITS):
            raise SapApiError("SAP2000 model adı veya uzunluk birimi okunamadı.")
        return ModelContext(path, *_LENGTH_UNITS[units - 1], self.connection.generation)

    def selection(self) -> tuple[tuple[int, str], ...]:
        count, types, names = _read(
            self.model.SelectObj.GetSelected, "SelectObj.GetSelected", (), (0, (), ()),
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
        try:
            method = self.model.DatabaseTables.GetTableForDisplayArray
        except AttributeError as exc:
            raise SapApiError(f"{label}: SAP2000 v23 veya daha yeni bir sürüm gerekli.") from exc

        # FieldKeyList ByRef girdi; comtypes onu da dönüş listesine ekler.
        # Bütün ref parametrelerini açıkça gönder; boş SAFEARRAY yerine null gönderme.
        result = _checked_call(method, label, key, fields, "", 0, (), 0, ())
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
        names = (name.strip() for (name,) in self._display_rows(_UCS_TABLE, ("Name",)))
        return tuple(dict.fromkeys(name for name in names if name and name.upper() != GLOBAL))

    def current_coordinate_system(self) -> str:
        name = self.model.GetPresentCoordSystem()
        if not isinstance(name, str) or not name.strip():
            raise SapApiError("SAP2000'in aktif koordinat sistemi okunamadı.")
        return name

    def named_ucs(self, name: str) -> WorkingUcs:
        if name.upper() == GLOBAL:
            return WorkingUcs()
        context = self.context()
        csys = self.model.CoordSys
        # GetCoordSys: global origin, RZ, RY, RX. Yön için matris kullanılır.
        x, y, z, *_ = _outputs(
            _checked_call(csys.GetCoordSys, "CoordSys.GetCoordSys", name, *((0.0,) * 6)),
            6, "CoordSys.GetCoordSys", lambda v: _vector_values(v, 6) is not None,
        )
        (matrix,) = _outputs(
            _checked_call(csys.GetTransformationMatrix, "CoordSys.GetTransformationMatrix",
                          name, (0.0,) * 9),
            1, "CoordSys.GetTransformationMatrix", lambda v: _vector_values(v[0], 9) is not None,
        )
        system = CoordinateSystem.from_sap((float(x), float(y), float(z)), tuple(matrix))
        if self.context() != context:
            raise SapApiError("UCS okunurken SAP2000 modeli veya birimi değişti.")
        return WorkingUcs(f"UCS: {name}", system, context, name)

    def frame_ucs(self) -> WorkingUcs:
        frames = [name for kind, name in self.selection() if kind == FRAME]
        if len(frames) != 1:
            raise InputValidationError("SAP2000'de referans olarak tek bir frame/profil seçin.")
        context = self.context()
        name = frames[0]
        # Bazı v26.2 kurulumlarında GetPoints, ByRef BSTR dolu olsa da
        # RPC_E_SERVERFAULT döndürüyor. I ucunu salt okunur bağlantı tablosundan al.
        starts = [joint.strip() for frame, joint in self._display_rows(_FRAME_TABLE, ("Frame", "JointI"))
                  if frame.strip() == name]
        if len(starts) != 1 or not starts[0]:
            raise SapApiError(f"Frame '{name}' için bağlantı tablosunda tek bir I ucu bulunamadı.")
        # CSI örneğindeki ReDim Value(8) ile aynı: dokuz Double içeren SAFEARRAY.
        (matrix,) = _outputs(
            _checked_call(self.model.FrameObj.GetTransformationMatrix, "FrameObj.GetTransformationMatrix",
                          name, (0.0,) * 9, True),
            1, "FrameObj.GetTransformationMatrix", lambda v: _vector_values(v[0], 9) is not None,
        )
        origin = self.connection.get_joint_coordinates(starts[0]).xyz
        if self.context() != context:
            raise SapApiError("Profil okunurken SAP2000 modeli veya birimi değişti.")
        return WorkingUcs(f"Frame {name} · Local 1/2/3",
                          CoordinateSystem.from_sap(origin, tuple(matrix)), context, None)

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
            if self.model.GetModelIsLocked() is not False:
                raise SapApiError("SAP2000 modeli kilitli; yeni UCS tanımlanamaz.")
            label = f"CoordSys.SetCoordSys({name})"
            result = _checked_call(self.model.CoordSys.SetCoordSys, label, name,
                                   *expected.origin, *expected.sap_rotations())
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
        if self.model.GetModelIsLocked() is not False:
            raise SapApiError("SAP2000 modeli kilitli veya kilit durumu okunamadı.")
        if edit.method not in {"Move", "ReplicateLinear", "ReplicateRadial", "ReplicateMirror"}:
            raise SapApiError("Desteklenmeyen SAP2000 düzenleme işlemi.")

        previous = self.current_coordinate_system()
        method = getattr(self.model.EditGeneral, edit.method)
        label = f"EditGeneral.{edit.method}"
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
        _check_code(_checked_call(self.model.SetPresentCoordSystem, label, name), label)
