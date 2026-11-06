"""SAP2000 OAPI bağlantısı ve API adaptörü.

SAP2000 OAPI metotları sürüme ve comtypes üretimine göre ``[in, out]``
parametrelerini farklı biçimlerde bekleyebilir. Bu modül koordinat okuma ve
seçim okuma çağrılarında bilinen çağrı biçimlerini sırayla dener.
"""

from __future__ import annotations

import math
from ctypes import byref, c_double, c_long, pointer
from typing import Any

from .errors import JointNotFoundError, SapApiError, SapConnectionError
from .models import JointPoint

SAP_PROGID = "CSI.SAP2000.API.SapObject"
SAP_OBJECT_PROGIDS = (SAP_PROGID, "SAP2000.SapObject")
HELPER_PROGIDS = ("SAP2000v1.Helper", "SAP2000.Helper")

# eObjectType: 1 = Point. Seçim listesindeki diğer nesneler yok sayılır.
POINT_OBJECT_TYPE = 1


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, c_long):
        return int(value.value)
    return None


def _result_code(result: Any) -> int | None:
    """SAP API dönüş kodunu (0 = başarılı) çıkarır."""

    if isinstance(result, (tuple, list)):
        return _as_int(result[0]) if result else None
    return _as_int(result)


def _parse_xyz_result(
    result: Any, ret_last: bool = False
) -> tuple[int | None, tuple[float, float, float] | None]:
    """Koordinat dönüşünü çözer.

    comtypes ``ref`` parametrelerini dönüş listesine ekler. CSI Python
    örneklerinde sıra ``[X, Y, Z, ret]`` biçimindedir. Doğrudan out parametreli
    çağrılarda ise ``[ret, X, Y, Z]`` görülebilir. İki sıra da desteklenir.
    """

    if not isinstance(result, (tuple, list)):
        return None, None

    items = list(result)
    ret: int | None = None
    values: list[Any]

    if len(items) >= 4:
        if ret_last:
            ret = _as_int(items[-1])
            values = items[0:3]
        else:
            first_code = _as_int(items[0])
            if first_code is not None:
                ret = first_code
                values = items[1:4]
            else:
                ret = _as_int(items[-1])
                values = items[0:3]
    elif len(items) == 3:
        values = items
    else:
        return None, None

    try:
        xyz = (float(values[0]), float(values[1]), float(values[2]))
    except (TypeError, ValueError):
        return ret, None
    return ret, xyz


def _string_list(value: Any) -> list[str] | None:
    """Bir değeri string listesine çevirir; string dizisi değilse ``None``."""

    if isinstance(value, str):
        return [value]
    if value is None:
        return None

    inner = getattr(value, "value", None)
    if (
        inner is not None
        and inner is not value
        and not isinstance(inner, (int, float, bool, str))
    ):
        nested = _string_list(inner)
        if nested is not None:
            return nested

    if isinstance(value, (list, tuple)):
        if not value:
            return []
        if all(isinstance(item, str) for item in value):
            return list(value)
        return None

    try:
        sequence = list(value)
    except TypeError:
        return None
    if not sequence:
        return []
    if all(isinstance(item, str) for item in sequence):
        return sequence
    return None


def _int_list(value: Any) -> list[int] | None:
    """Bir değeri int listesine çevirir; int dizisi değilse ``None``."""

    if isinstance(value, (int, float, bool, str)):
        return None

    inner = getattr(value, "value", None)
    if inner is not None and inner is not value:
        nested = _int_list(inner)
        if nested is not None:
            return nested

    if isinstance(value, (list, tuple)):
        if not value:
            return []
        converted = [_as_int(item) for item in value]
        if all(item is not None for item in converted):
            return [int(item) for item in converted if item is not None]
        return None

    try:
        sequence = list(value)
    except TypeError:
        return None
    if not sequence:
        return []
    converted = [_as_int(item) for item in sequence]
    if all(item is not None for item in converted):
        return [int(item) for item in converted if item is not None]
    return None


def _extract_string_array(result: Any) -> list[str] | None:
    if isinstance(result, (tuple, list)):
        if result and all(isinstance(item, str) for item in result):
            return list(result)
        for item in reversed(result):
            names = _string_list(item)
            if names is not None:
                return names
        return None
    return _string_list(result)


def _extract_parallel_arrays(result: Any) -> tuple[list[str] | None, list[int] | None]:
    """Sonuçtan isim ve nesne tipi dizilerini çıkarır."""

    if not isinstance(result, (tuple, list)):
        return None, None

    direct_names = _string_list(result)
    if direct_names is not None:
        return direct_names, None

    direct_types = _int_list(result)
    if direct_types is not None:
        return None, direct_types

    names: list[str] | None = None
    types: list[int] | None = None
    for item in result:
        candidate_names = _string_list(item)
        if candidate_names is not None and (
            names is None or (not names and candidate_names)
        ):
            names = candidate_names
        candidate_types = _int_list(item)
        if candidate_types is not None and (
            types is None or (not types and candidate_types)
        ):
            types = candidate_types
    return names, types


def _bool_from_result(result: Any) -> bool | None:
    if isinstance(result, bool):
        return result
    inner = getattr(result, "value", None)
    if isinstance(inner, bool):
        return inner
    if isinstance(result, (tuple, list)):
        for item in reversed(result):
            if isinstance(item, bool):
                return item
    return None


def _variant() -> Any:
    from comtypes.automation import VARIANT

    return VARIANT()


class SapConnection:
    """Aktif SAP2000 modeline bağlanan ince OAPI sarmalayıcısı."""

    def __init__(self, model: Any | None = None, sap_object: Any | None = None) -> None:
        self._model = model
        self._sap_object = sap_object

    @property
    def model(self) -> Any:
        if self._model is None:
            self.connect()
        return self._model

    def connect(self) -> Any:
        """Aktif SAP2000 örneğine bağlanır ve ``SapModel`` döndürür."""

        if self._model is not None:
            return self._model

        try:
            import comtypes.client as comtypes_client
        except ImportError as exc:  # pragma: no cover - Windows dışı ortam
            raise SapConnectionError(
                "comtypes paketi bulunamadı. 'pip install -r requirements.txt' çalıştırın."
            ) from exc

        last_error: Exception | None = None
        sap_object = self._sap_object

        if sap_object is None:
            try:
                sap_object = comtypes_client.GetActiveObject(SAP_PROGID)
            except Exception as exc:
                last_error = exc

        if sap_object is None:
            for helper_progid in HELPER_PROGIDS:
                try:
                    helper = comtypes_client.CreateObject(helper_progid)
                except Exception as exc:
                    last_error = exc
                    continue
                for progid in SAP_OBJECT_PROGIDS:
                    try:
                        sap_object = helper.GetObject(progid)
                        break
                    except Exception as exc:
                        last_error = exc
                if sap_object is not None:
                    break

        if sap_object is None:
            for progid in SAP_OBJECT_PROGIDS:
                try:
                    sap_object = comtypes_client.GetActiveObject(progid)
                    break
                except Exception as exc:
                    last_error = exc

        if sap_object is None:
            detail = f" Son hata: {last_error}" if last_error else ""
            raise SapConnectionError(
                "Aktif SAP2000 örneğine bağlanılamadı. SAP2000'i açın, modeli yükleyin "
                "ve OAPI erişiminin etkin olduğundan emin olun." + detail
            )

        try:
            model = sap_object.SapModel
            if callable(model):
                model = model()
        except Exception as exc:
            raise SapConnectionError(
                f"SAP2000 SapModel nesnesine erişilemedi: {exc}"
            ) from exc

        if model is None:
            raise SapConnectionError("SAP2000 SapModel nesnesi boş döndü.")

        self._sap_object = sap_object
        self._model = model
        return model

    def get_joint_coordinates(self, name: str) -> JointPoint:
        """Joint koordinatlarını ``PointObj.GetCoordCartesian`` ile okur."""

        x, y, z = self._read_coordinates(name)
        return JointPoint(name=name, x=x, y=y, z=z)

    def _read_coordinates(self, name: str) -> tuple[float, float, float]:
        try:
            method = self.model.PointObj.GetCoordCartesian
        except Exception as exc:
            raise SapApiError(f"PointObj.GetCoordCartesian erişilemedi: {exc}") from exc

        attempts: list[str] = []
        error_codes: list[int] = []

        for mode in ("returns", "pointer", "byref", "plain", "values"):
            try:
                ret, values = self._read_xyz_once(method, name, mode)
            except Exception as exc:
                attempts.append(f"{mode}: {exc}")
                continue

            if ret not in (None, 0):
                error_codes.append(ret)
                attempts.append(f"{mode}: SAP hata kodu {ret}")
                continue
            if values is None:
                attempts.append(f"{mode}: koordinat döndürmedi")
                continue
            if not all(math.isfinite(value) for value in values):
                attempts.append(f"{mode}: geçersiz/sonsuz koordinat")
                continue
            return values

        if error_codes:
            raise JointNotFoundError(name, f"SAP hata kodu {error_codes[0]}")
        detail = " | ".join(attempts[-3:]) if attempts else "bilinmeyen hata"
        raise SapApiError(
            f"Joint '{name}' koordinatları okunamadı. Denenen çağrılar: {detail}"
        )

    @staticmethod
    def _read_xyz_once(
        method: Any, name: str, mode: str
    ) -> tuple[int | None, tuple[float, float, float] | None]:
        if mode == "returns":
            # comtypes, ref parametrelerini çağrı argümanı olarak değil dönüş
            # listesi olarak verir: [X, Y, Z, ret].
            result = method(name)
            return _parse_xyz_result(result, ret_last=True)
        if mode == "values":
            result = method(name, 0.0, 0.0, 0.0)
            return _parse_xyz_result(result)

        x = c_double(math.nan)
        y = c_double(math.nan)
        z = c_double(math.nan)

        if mode == "pointer":
            result = method(name, pointer(x), pointer(y), pointer(z))
        elif mode == "byref":
            result = method(name, byref(x), byref(y), byref(z))
        elif mode == "plain":
            result = method(name, x, y, z)
        else:  # pragma: no cover - yukarıdaki liste kapatır
            raise ValueError(f"Bilinmeyen okuma modu: {mode}")

        ret = _result_code(result)
        written = (x.value, y.value, z.value)
        if all(math.isfinite(value) for value in written):
            return ret, (float(written[0]), float(written[1]), float(written[2]))

        parsed_ret, parsed_values = _parse_xyz_result(result)
        if parsed_values is not None:
            return parsed_ret if parsed_ret is not None else ret, parsed_values
        return ret, None

    def get_joint_names(self) -> list[str]:
        """Modeldeki tüm joint adlarını döndürür."""

        try:
            method = self.model.PointObj.GetNameList
        except Exception as exc:
            raise SapApiError(f"PointObj.GetNameList erişilemedi: {exc}") from exc

        def no_args() -> list[Any]:
            return [method()]

        def byref_variant() -> list[Any]:
            count = c_long(0)
            names = _variant()
            result = method(byref(count), byref(names))
            return [result, getattr(names, "value", None)]

        def pointer_variant() -> list[Any]:
            count = c_long(0)
            names = _variant()
            result = method(pointer(count), pointer(names))
            return [result, getattr(names, "value", None)]

        def plain_values() -> list[Any]:
            count = 0
            names: list[str] = []
            result = method(count, names)
            return [result, names]

        calls = (no_args, byref_variant, pointer_variant, plain_values)
        last_error: Exception | None = None
        empty_success = False
        for call in calls:
            try:
                candidates = call()
            except Exception as exc:
                last_error = exc
                continue
            for candidate in candidates:
                names = _extract_string_array(candidate)
                if names is None:
                    continue
                if names:
                    return names
                empty_success = True

        if empty_success:
            return []
        detail = f" Son hata: {last_error}" if last_error else ""
        raise SapApiError("Joint ad listesi SAP2000'den okunamadı." + detail)

    def get_selected_joint_names(self) -> list[str]:
        """SAP2000 ekranında seçili olan joint adlarını döndürür."""

        try:
            names, types = self._read_selection()
        except Exception:
            return self._selected_with_point_flags()

        if types is not None and len(types) == len(names):
            return [
                name
                for object_type, name in zip(types, names)
                if object_type == POINT_OBJECT_TYPE
            ]

        # Nesne tipleri okunamadıysa yalnızca koordinatı okunabilen adları tut.
        joints: list[str] = []
        for name in names:
            try:
                self.get_joint_coordinates(name)
            except JointNotFoundError:
                continue
            joints.append(name)
        return joints

    def _read_selection(self) -> tuple[list[str], list[int] | None]:
        try:
            method = self.model.SelectObj.GetSelected
        except Exception as exc:
            raise SapApiError(f"SelectObj.GetSelected erişilemedi: {exc}") from exc

        def no_args() -> list[Any]:
            return [method()]

        def plain_values() -> list[Any]:
            count = 0
            object_types: list[int] = []
            object_names: list[str] = []
            result = method(count, object_types, object_names)
            return [result, object_types, object_names]

        def byref_variant() -> list[Any]:
            count = c_long(0)
            object_types = _variant()
            object_names = _variant()
            result = method(byref(count), byref(object_types), byref(object_names))
            return [
                result,
                getattr(object_types, "value", None),
                getattr(object_names, "value", None),
            ]

        def pointer_variant() -> list[Any]:
            count = c_long(0)
            object_types = _variant()
            object_names = _variant()
            result = method(
                pointer(count), pointer(object_types), pointer(object_names)
            )
            return [
                result,
                getattr(object_types, "value", None),
                getattr(object_names, "value", None),
            ]

        calls = (no_args, plain_values, byref_variant, pointer_variant)
        last_error: Exception | None = None
        empty_success = False
        for call in calls:
            try:
                candidates = call()
            except Exception as exc:
                last_error = exc
                continue

            names: list[str] | None = None
            types: list[int] | None = None
            for candidate in candidates:
                candidate_names, candidate_types = _extract_parallel_arrays(candidate)
                if candidate_names is not None and (
                    names is None or (not names and candidate_names)
                ):
                    names = candidate_names
                if candidate_types is not None and (
                    types is None or (not types and candidate_types)
                ):
                    types = candidate_types

            if names:
                return names, types
            if names is not None:
                empty_success = True

        if empty_success:
            return [], None
        detail = f" Son hata: {last_error}" if last_error else ""
        raise SapApiError("SAP2000 seçim listesi okunamadı." + detail)

    def _selected_with_point_flags(self) -> list[str]:
        names = self.get_joint_names()
        if not names:
            return []

        try:
            method = self.model.PointObj.GetSelected
        except Exception as exc:
            raise SapApiError(f"PointObj.GetSelected erişilemedi: {exc}") from exc

        selected: list[str] = []
        readable = False
        for name in names:
            try:
                flag = _bool_from_result(method(name))
            except Exception:
                continue
            if flag is None:
                continue
            readable = True
            if flag:
                selected.append(name)

        if not readable:
            raise SapApiError("SAP2000 seçimi okunamadı. Joint listesini elle girin.")
        return selected

    def set_local_axes(
        self,
        name: str,
        angle_a: float,
        angle_b: float = 0.0,
        angle_c: float = 0.0,
    ) -> None:
        """Joint local axes A/B/C açılarını atar."""

        try:
            method = self.model.PointObj.SetLocalAxes
        except Exception as exc:
            raise SapApiError(f"PointObj.SetLocalAxes erişilemedi: {exc}") from exc

        result = method(
            name,
            float(angle_a),
            float(angle_b),
            float(angle_c),
        )
        code = _result_code(result)
        if code not in (None, 0):
            raise SapApiError(
                f"Joint '{name}' local axes atanamadı (SAP hata kodu {code})."
            )

    def refresh_view(self) -> None:
        """SAP2000 görünümünü yeniler."""

        try:
            result = self.model.View.RefreshView(0, False)
        except Exception as exc:
            raise SapApiError(f"SAP2000 görünümü yenilenemedi: {exc}") from exc

        code = _result_code(result)
        if code not in (None, 0):
            raise SapApiError(f"SAP2000 görünümü yenilenemedi (hata kodu {code}).")
