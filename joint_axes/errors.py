"""Uygulama hata tipleri."""

from __future__ import annotations


class JointAxesError(Exception):
    """Tüm uygulama hatalarının taban sınıfı."""


class InputValidationError(JointAxesError):
    """Kullanıcı girdisi geçersiz."""


class SapConnectionError(JointAxesError):
    """SAP2000 OAPI bağlantısı kurulamadı."""


class SapApiError(JointAxesError):
    """SAP2000 API çağrısı başarısız oldu."""


class JointNotFoundError(SapApiError):
    """Joint modelde bulunamadı veya koordinatı okunamadı."""

    def __init__(self, joint_name: str, detail: str = "") -> None:
        self.joint_name = joint_name
        message = f"Joint '{joint_name}' modelde bulunamadı"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)
