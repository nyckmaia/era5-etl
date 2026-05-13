"""CDS API credentials: status, save, and connectivity test.

The web UI uses these endpoints to drive a guided onboarding flow:

- ``GET /api/credentials/status`` reports whether the running app can see
  CDS credentials (env vars or ``~/.cdsapirc``). It never returns the
  key — only the URL and the source.
- ``POST /api/credentials`` writes ``~/.cdsapirc`` from a form payload.
  Existing files are overwritten; on POSIX the file is chmod'd to 0600.
- ``POST /api/credentials/test`` makes a single HTTP request to the CDS
  catalogue endpoint with a short timeout, so the user gets immediate
  feedback before launching a real download.

Format of ``~/.cdsapirc`` (the YAML cdsapi expects)::

    url: https://cds.climate.copernicus.eu/api
    key: <token>
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException

from era5_etl.web.models import (
    CredentialsIn,
    CredentialStatusOut,
    CredentialTestOut,
)

router = APIRouter(prefix="/api/credentials", tags=["credentials"])

CDSAPIRC_FILENAME = ".cdsapirc"
DEFAULT_CDS_URL = "https://cds.climate.copernicus.eu/api"
_CATALOGUE_PROBE_PATH = "/catalogue/v1/"


def _cdsapirc_path() -> Path:
    """Resolve ``~/.cdsapirc`` regardless of platform."""
    return Path.home() / CDSAPIRC_FILENAME


def _parse_cdsapirc(path: Path) -> dict[str, str]:
    """Parse the simple ``key: value`` lines of ``~/.cdsapirc``.

    Tolerates blank lines and ``#`` comments. Unknown keys are kept verbatim
    so we round-trip cleanly when the user adds extra fields like ``verify``.
    """
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


def _read_status() -> CredentialStatusOut:
    """Build the current status without exposing the secret key."""
    env_url = os.environ.get("CDSAPI_URL")
    env_key = os.environ.get("CDSAPI_KEY")
    file_path = _cdsapirc_path()

    if env_url and env_key:
        return CredentialStatusOut(
            has_credentials=True,
            source="env",
            url=env_url,
            file_path=str(file_path),
        )

    if file_path.exists():
        try:
            data = _parse_cdsapirc(file_path)
            if data.get("url") and data.get("key"):
                return CredentialStatusOut(
                    has_credentials=True,
                    source="file",
                    url=data["url"],
                    file_path=str(file_path),
                )
        except OSError:
            pass

    return CredentialStatusOut(
        has_credentials=False,
        source="none",
        url=None,
        file_path=str(file_path),
    )


@router.get("/status", response_model=CredentialStatusOut)
def get_status() -> CredentialStatusOut:
    return _read_status()


@router.post("", response_model=CredentialStatusOut)
def save_credentials(body: CredentialsIn) -> CredentialStatusOut:
    """Write ``~/.cdsapirc`` from URL+key. Overwrites any existing file."""
    url = body.url.strip()
    key = body.key.strip()
    if not url.startswith(("https://", "http://")):
        raise HTTPException(
            status_code=422, detail="url must start with https:// (or http://)"
        )
    if "\n" in url or "\n" in key:
        raise HTTPException(status_code=422, detail="url and key must be single-line")

    path = _cdsapirc_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = f"url: {url}\nkey: {key}\n"
    path.write_text(payload, encoding="utf-8")
    # Best-effort: lock down permissions on POSIX. No-op on Windows.
    try:
        os.chmod(path, 0o600)
    except (OSError, NotImplementedError):
        pass

    return _read_status()


@router.post("/test", response_model=CredentialTestOut)
def test_credentials() -> CredentialTestOut:
    """Probe the configured CDS endpoint with a short timeout.

    Strategy: read URL + key the same way ``cdsapi`` does, then issue a
    plain HTTP GET against the catalogue endpoint with the API key in the
    ``PRIVATE-TOKEN`` header. We don't reach into ``cdsapi`` internals
    because they vary between legacy/new client versions; a direct
    ``httpx`` call is more robust and gives us the latency for free.
    """
    status = _read_status()
    if not status.has_credentials:
        return CredentialTestOut(
            ok=False,
            message="No CDS credentials found. Save them first.",
        )

    import httpx

    url = status.url or DEFAULT_CDS_URL
    key = _resolve_key(status.source)
    if not key:
        return CredentialTestOut(
            ok=False,
            message="Credentials present but the key could not be read back from disk.",
        )

    probe = url.rstrip("/") + _CATALOGUE_PROBE_PATH
    headers = {"PRIVATE-TOKEN": key, "Accept": "application/json"}

    started = time.monotonic()
    try:
        response = httpx.get(probe, headers=headers, timeout=15.0)
    except httpx.TimeoutException:
        return CredentialTestOut(
            ok=False,
            message=(
                f"Timed out contacting {probe} after 15s. "
                "Check network connectivity and the URL."
            ),
        )
    except httpx.RequestError as exc:
        return CredentialTestOut(
            ok=False,
            message=f"Could not reach {probe}: {exc}",
        )

    latency = int((time.monotonic() - started) * 1000)
    if response.status_code in (200, 204):
        return CredentialTestOut(
            ok=True,
            message=f"OK — reached {url} in {latency} ms.",
            latency_ms=latency,
            status_code=response.status_code,
        )
    if response.status_code in (401, 403):
        return CredentialTestOut(
            ok=False,
            message=(
                f"Server rejected the API key ({response.status_code}). "
                "Re-copy the Personal Access Token from your CDS profile."
            ),
            latency_ms=latency,
            status_code=response.status_code,
        )
    return CredentialTestOut(
        ok=False,
        message=(
            f"Unexpected response {response.status_code} from {probe}. "
            f"Body: {response.text[:200]}"
        ),
        latency_ms=latency,
        status_code=response.status_code,
    )


def _resolve_key(source: str) -> str | None:
    """Read the API key from env or file — never returned to the client."""
    if source == "env":
        return os.environ.get("CDSAPI_KEY")
    if source == "file":
        try:
            return _parse_cdsapirc(_cdsapirc_path()).get("key")
        except OSError:
            return None
    return None
