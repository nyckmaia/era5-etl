"""Tests for CDS downloader module."""

import calendar
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from era5_etl.config import DownloadConfig
from era5_etl.exceptions import CDSAPIError, DownloadError


class TestDaysInMonth:
    """Tests for calendar.monthrange-based days calculation."""

    def test_january_31_days(self):
        _, num_days = calendar.monthrange(2023, 1)
        assert num_days == 31

    def test_february_non_leap_28_days(self):
        _, num_days = calendar.monthrange(2023, 2)
        assert num_days == 28

    def test_february_leap_29_days(self):
        _, num_days = calendar.monthrange(2024, 2)
        assert num_days == 29

    def test_april_30_days(self):
        _, num_days = calendar.monthrange(2023, 4)
        assert num_days == 30

    def test_february_century_non_leap(self):
        _, num_days = calendar.monthrange(1900, 2)
        assert num_days == 28

    def test_february_400_year_leap(self):
        _, num_days = calendar.monthrange(2000, 2)
        assert num_days == 29


class TestBuildCDSRequest:
    """Tests for CDS request building with correct day counts."""

    @patch("era5_etl.download.cds_downloader.cdsapi.Client")
    def test_february_leap_year_request(self, mock_client_cls: MagicMock, tmp_path: Path):
        """Feb 2024 (leap) should have 29 days."""
        mock_client_cls.return_value = MagicMock()
        config = DownloadConfig(output_dir=tmp_path / "out")

        from era5_etl.download.cds_downloader import CDSDownloader

        with patch.object(CDSDownloader, "_validate_credentials"):
            downloader = CDSDownloader(config)

        request = downloader._build_cds_request(2024, 2)
        days = request["day"]
        assert isinstance(days, list)
        assert len(days) == 29
        assert days[-1] == "29"

    @patch("era5_etl.download.cds_downloader.cdsapi.Client")
    def test_february_non_leap_year_request(self, mock_client_cls: MagicMock, tmp_path: Path):
        """Feb 2023 (non-leap) should have 28 days."""
        mock_client_cls.return_value = MagicMock()
        config = DownloadConfig(output_dir=tmp_path / "out")

        from era5_etl.download.cds_downloader import CDSDownloader

        with patch.object(CDSDownloader, "_validate_credentials"):
            downloader = CDSDownloader(config)

        request = downloader._build_cds_request(2023, 2)
        days = request["day"]
        assert isinstance(days, list)
        assert len(days) == 28

    @patch("era5_etl.download.cds_downloader.cdsapi.Client")
    def test_december_31_days_request(self, mock_client_cls: MagicMock, tmp_path: Path):
        """December should have 31 days."""
        mock_client_cls.return_value = MagicMock()
        config = DownloadConfig(output_dir=tmp_path / "out")

        from era5_etl.download.cds_downloader import CDSDownloader

        with patch.object(CDSDownloader, "_validate_credentials"):
            downloader = CDSDownloader(config)

        request = downloader._build_cds_request(2023, 12)
        days = request["day"]
        assert isinstance(days, list)
        assert len(days) == 31


class TestRetryLogic:
    """Tests for exponential backoff retry in CDS API downloads."""

    @patch("era5_etl.download.cds_downloader.time.sleep")
    @patch("era5_etl.download.cds_downloader.cdsapi.Client")
    def test_retry_succeeds_after_failures(
        self, mock_client_cls: MagicMock, mock_sleep: MagicMock, tmp_path: Path
    ):
        """Client that fails 2x then succeeds should not raise."""
        mock_client = MagicMock()
        mock_client.retrieve.side_effect = [
            Exception("Timeout"),
            Exception("Server error"),
            None,  # Success on 3rd attempt
        ]
        mock_client_cls.return_value = mock_client

        config = DownloadConfig(
            output_dir=tmp_path / "out",
            max_retries=3,
            retry_delay=1.0,
        )

        from era5_etl.download.cds_downloader import CDSDownloader

        with patch.object(CDSDownloader, "_validate_credentials"):
            downloader = CDSDownloader(config)

        request = {"product_type": "reanalysis"}
        target = tmp_path / "test.nc"

        # Should not raise
        downloader._retrieve_with_retry(request, target, 2023, 1)
        assert mock_client.retrieve.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("era5_etl.download.cds_downloader.time.sleep")
    @patch("era5_etl.download.cds_downloader.cdsapi.Client")
    def test_retry_exhausted_raises(
        self, mock_client_cls: MagicMock, mock_sleep: MagicMock, tmp_path: Path
    ):
        """All retries exhausted should raise DownloadError."""
        mock_client = MagicMock()
        mock_client.retrieve.side_effect = Exception("Persistent failure")
        mock_client_cls.return_value = mock_client

        config = DownloadConfig(
            output_dir=tmp_path / "out",
            max_retries=2,
            retry_delay=1.0,
        )

        from era5_etl.download.cds_downloader import CDSDownloader

        with patch.object(CDSDownloader, "_validate_credentials"):
            downloader = CDSDownloader(config)

        request = {"product_type": "reanalysis"}
        target = tmp_path / "test.nc"

        with pytest.raises(DownloadError, match="All 3 attempts failed"):
            downloader._retrieve_with_retry(request, target, 2023, 1)

        # max_retries=2 means 3 total attempts (initial + 2 retries)
        assert mock_client.retrieve.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("era5_etl.download.cds_downloader.time.sleep")
    @patch("era5_etl.download.cds_downloader.cdsapi.Client")
    def test_no_retries(
        self, mock_client_cls: MagicMock, mock_sleep: MagicMock, tmp_path: Path
    ):
        """With max_retries=0, should fail immediately."""
        mock_client = MagicMock()
        mock_client.retrieve.side_effect = Exception("Fail")
        mock_client_cls.return_value = mock_client

        config = DownloadConfig(
            output_dir=tmp_path / "out",
            max_retries=0,
            retry_delay=1.0,
        )

        from era5_etl.download.cds_downloader import CDSDownloader

        with patch.object(CDSDownloader, "_validate_credentials"):
            downloader = CDSDownloader(config)

        with pytest.raises(DownloadError, match="All 1 attempts failed"):
            downloader._retrieve_with_retry({}, tmp_path / "x.nc", 2023, 1)

        assert mock_client.retrieve.call_count == 1
        assert mock_sleep.call_count == 0

    @patch("era5_etl.download.cds_downloader.time.sleep")
    @patch("era5_etl.download.cds_downloader.cdsapi.Client")
    def test_first_attempt_succeeds(
        self, mock_client_cls: MagicMock, mock_sleep: MagicMock, tmp_path: Path
    ):
        """When first attempt succeeds, no retries should happen."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        config = DownloadConfig(
            output_dir=tmp_path / "out",
            max_retries=3,
            retry_delay=1.0,
        )

        from era5_etl.download.cds_downloader import CDSDownloader

        with patch.object(CDSDownloader, "_validate_credentials"):
            downloader = CDSDownloader(config)

        downloader._retrieve_with_retry({}, tmp_path / "x.nc", 2023, 1)
        assert mock_client.retrieve.call_count == 1
        assert mock_sleep.call_count == 0


class TestCredentialValidation:
    """Tests for CDS API credential validation."""

    def test_missing_credentials_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """No ~/.cdsapirc and no env vars should raise CDSAPIError."""
        monkeypatch.delenv("CDSAPI_URL", raising=False)
        monkeypatch.delenv("CDSAPI_KEY", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")

        from era5_etl.download.cds_downloader import CDSDownloader

        config = DownloadConfig(output_dir=tmp_path / "out")

        with pytest.raises(CDSAPIError, match="credentials not found"):
            CDSDownloader(config)

    def test_env_vars_accepted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """CDSAPI_URL + CDSAPI_KEY env vars should pass validation."""
        monkeypatch.setenv("CDSAPI_URL", "https://cds.example.com/api")
        monkeypatch.setenv("CDSAPI_KEY", "12345:abcdef")

        from era5_etl.download.cds_downloader import CDSDownloader

        with patch("era5_etl.download.cds_downloader.cdsapi.Client"):
            config = DownloadConfig(output_dir=tmp_path / "out")
            downloader = CDSDownloader(config)
            assert downloader.client is not None

    def test_cdsapirc_file_accepted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """~/.cdsapirc file should pass validation."""
        monkeypatch.delenv("CDSAPI_URL", raising=False)
        monkeypatch.delenv("CDSAPI_KEY", raising=False)

        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        cdsapirc = fake_home / ".cdsapirc"
        cdsapirc.write_text("url: https://cds.example.com/api\nkey: 12345:abcdef\n")
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        from era5_etl.download.cds_downloader import CDSDownloader

        with patch("era5_etl.download.cds_downloader.cdsapi.Client"):
            config = DownloadConfig(output_dir=tmp_path / "out")
            downloader = CDSDownloader(config)
            assert downloader.client is not None


class TestDownloadConfigRetryFields:
    """Tests for retry configuration fields in DownloadConfig."""

    def test_default_retry_values(self):
        config = DownloadConfig()
        assert config.max_retries == 3
        assert config.retry_delay == 30.0

    def test_custom_retry_values(self):
        config = DownloadConfig(max_retries=5, retry_delay=60.0)
        assert config.max_retries == 5
        assert config.retry_delay == 60.0

    def test_zero_retries_allowed(self):
        config = DownloadConfig(max_retries=0)
        assert config.max_retries == 0
