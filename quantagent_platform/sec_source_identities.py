"""Stable identities of the fixed SEC sample, without a transport dependency."""

SEC_URLS = (
    ("submissions", "0001507605", "https://data.sec.gov/submissions/CIK0001507605.json"),
    ("companyfacts", "0001507605", "https://data.sec.gov/api/xbrl/companyfacts/CIK0001507605.json"),
    ("submissions", "0001167419", "https://data.sec.gov/submissions/CIK0001167419.json"),
    ("companyfacts", "0001167419", "https://data.sec.gov/api/xbrl/companyfacts/CIK0001167419.json"),
)

RAW_NAMES = (
    "sec-mara-submissions.json",
    "sec-mara-companyfacts.json",
    "sec-riot-submissions.json",
    "sec-riot-companyfacts.json",
)
