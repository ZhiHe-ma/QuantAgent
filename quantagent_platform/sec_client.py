"""Bounded, fixed-endpoint reads from the SEC EDGAR JSON APIs."""

from __future__ import annotations

import hashlib
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from .plugins import PluginError


MAX_RESPONSE_BYTES = 8 * 1024 * 1024
SEC_URLS = (
    ("submissions", "0001507605", "https://data.sec.gov/submissions/CIK0001507605.json"),
    ("companyfacts", "0001507605", "https://data.sec.gov/api/xbrl/companyfacts/CIK0001507605.json"),
    ("submissions", "0001167419", "https://data.sec.gov/submissions/CIK0001167419.json"),
    ("companyfacts", "0001167419", "https://data.sec.gov/api/xbrl/companyfacts/CIK0001167419.json"),
)


@dataclass(frozen=True, repr=False)
class SecResponse:
    kind: str
    cik: str
    url: str
    raw: bytes
    sha256: str
    retrieved_at: str


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


def fetch_sample(
    user_agent: str,
    *,
    opener: Any = None,
    clock: Callable[[], float] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> list[SecResponse]:
    """Fetch the two pinned issuers; neither callers nor data can choose URLs."""
    if (not isinstance(user_agent, str) or not user_agent.strip()
            or "\r" in user_agent or "\n" in user_agent or len(user_agent) > 256):
        raise PluginError("SEC_USER_AGENT must contain a valid project contact")
    opener = opener if opener is not None else urllib.request.build_opener(_NoRedirect())
    clock = clock or time.monotonic
    sleeper = sleeper or time.sleep
    next_start: float | None = None
    responses: list[SecResponse] = []

    for kind, cik, url in SEC_URLS:
        now = clock()
        if next_start is not None and now < next_start:
            sleeper(next_start - now)
        started = clock()
        next_start = started + 1.0
        request = urllib.request.Request(
            url,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            method="GET",
        )
        try:
            with opener.open(request, timeout=15) as response:
                status = response.status
                final_url = response.geturl()
                if status != 200 or final_url != url:
                    raise PluginError(f"SEC response rejected: HTTP {status}")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise PluginError(f"SEC request failed: HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise PluginError("SEC request failed: network or timeout error") from None
        except (AttributeError, TypeError, ValueError):
            raise PluginError("SEC response has an invalid transport shape") from None
        if not isinstance(raw, bytes):
            raise PluginError("SEC response body is not bytes")
        if len(raw) > MAX_RESPONSE_BYTES:
            raise PluginError("SEC response exceeds 8 MiB limit")
        responses.append(SecResponse(
            kind=kind,
            cik=cik,
            url=url,
            raw=raw,
            sha256=hashlib.sha256(raw).hexdigest(),
            retrieved_at=datetime.now(timezone.utc).isoformat(),
        ))

    return responses
