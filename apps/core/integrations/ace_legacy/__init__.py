"""Read-only транспорт для legacy Microsoft Access через Windows ACE OLE DB."""

from .reader import AccessTransportError, run_access_export

__all__ = ["AccessTransportError", "run_access_export"]
