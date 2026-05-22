"""Custom exceptions for ERA5-ETL."""


class ERA5ETLError(Exception):
    """Base exception for all ERA5-ETL errors."""

    pass


class DownloadError(ERA5ETLError):
    """Raised when CDS download fails."""

    pass


class DownloadSizeError(DownloadError):
    """Raised when a CDS download request exceeds the size limit."""

    pass


class CDSRequestTooLargeError(DownloadError):
    """Raised when the CDS server itself rejects a request as too large.

    Distinct from :class:`DownloadSizeError` (which the local planner
    raises before contacting CDS): this one fires when CDS responds
    with the 403 'cost limits exceeded' or 'Your request is too large'
    message. ``CDSDownloader`` catches it and splits the offending
    chunk adaptively rather than retrying the same request.
    """

    pass


class ProcessingError(ERA5ETLError):
    """Raised when NetCDF processing fails."""

    pass


class StorageError(ERA5ETLError):
    """Raised when storage operation fails."""

    pass


class ConfigurationError(ERA5ETLError):
    """Raised when configuration is invalid."""

    pass


class CDSAPIError(ERA5ETLError):
    """Raised for CDS API errors."""

    pass


class PipelineCancelled(ERA5ETLError):
    """Raised when pipeline is cancelled by user."""

    pass
