"""Fixed SEC response identities, byte limit and immutable data; no transport IO."""

from __future__ import annotations

from dataclasses import dataclass


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
