"""Custom exceptions for PyERA5."""


class PyERA5Error(Exception):
    """Base exception for PyERA5."""

    pass


class DownloadError(PyERA5Error):
    """Exception raised when download fails."""

    pass


class ProcessingError(PyERA5Error):
    """Exception raised when processing fails."""

    pass


class StorageError(PyERA5Error):
    """Exception raised when storage operation fails."""

    pass


class ConfigurationError(PyERA5Error):
    """Exception raised for invalid configuration."""

    pass


class CDSAPIError(PyERA5Error):
    """Exception raised for CDS API errors."""

    pass
