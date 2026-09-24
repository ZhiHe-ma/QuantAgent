import hashlib
import io
import unittest
from datetime import datetime

from quantagent_platform.plugins import PluginError
from quantagent_platform.sec_client import SEC_URLS, fetch_sample


CONTACT = "QuantAgent test-contact@example.invalid"


class FakeResponse(io.BytesIO):
    def __init__(self, raw=b"{}", *, status=200, url=""):
        super().__init__(raw)
        self.status = status
        self.url = url

    def geturl(self):
        return self.url


class FakeOpener:
    def __init__(self, *, raw=b"{}", status=200, redirect=False, error=None, clock=None):
        self.raw = raw
        self.status = status
        self.redirect = redirect
        self.error = error
        self.clock = clock
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request.full_url, request.get_header("User-agent"), timeout,
                           None if self.clock is None else self.clock.now))
        if self.error is not None:
            raise self.error
        url = "https://example.invalid/redirected" if self.redirect else request.full_url
        return FakeResponse(self.raw, status=self.status, url=url)


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class SecClientTests(unittest.TestCase):
    def test_fetches_exactly_four_fixed_sec_urls_at_one_second_intervals(self):
        clock = FakeClock()
        opener = FakeOpener(raw=b'{"cik":1507605}', clock=clock)

        responses = fetch_sample(CONTACT, opener=opener, clock=clock,
                                 sleeper=clock.sleep)

        expected = [
            "https://data.sec.gov/submissions/CIK0001507605.json",
            "https://data.sec.gov/api/xbrl/companyfacts/CIK0001507605.json",
            "https://data.sec.gov/submissions/CIK0001167419.json",
            "https://data.sec.gov/api/xbrl/companyfacts/CIK0001167419.json",
        ]
        self.assertEqual([call[0] for call in opener.calls], expected)
        self.assertEqual([row.url for row in responses], expected)
        self.assertEqual(len(SEC_URLS), 4)
        self.assertEqual([call[3] for call in opener.calls], [0.0, 1.0, 2.0, 3.0])
        self.assertEqual(clock.sleeps, [1.0, 1.0, 1.0])
        self.assertTrue(all(call[1] == CONTACT and call[2] == 15 for call in opener.calls))
        self.assertEqual(responses[0].sha256,
                         hashlib.sha256(responses[0].raw).hexdigest())
        self.assertTrue(all(datetime.fromisoformat(row.retrieved_at).utcoffset()
                            is not None for row in responses))
        self.assertNotIn(CONTACT, repr(responses))

    def test_rejects_http_errors_redirects_oversize_and_timeout_without_contact_leak(self):
        cases = (
            ("redirect", FakeOpener(status=302)),
            ("moved", FakeOpener(redirect=True)),
            ("forbidden", FakeOpener(status=403)),
            ("throttled", FakeOpener(status=429)),
            ("oversize", FakeOpener(raw=b"x" * (8 * 1024 * 1024 + 1))),
            ("timeout", FakeOpener(error=TimeoutError(CONTACT))),
        )
        for name, opener in cases:
            with self.subTest(name=name):
                with self.assertRaises(PluginError) as caught:
                    fetch_sample(CONTACT, opener=opener,
                                 clock=FakeClock(), sleeper=lambda _: None)
                self.assertNotIn(CONTACT, str(caught.exception))
                self.assertEqual(len(opener.calls), 1)

    def test_empty_contact_is_rejected_before_open(self):
        opener = FakeOpener()
        with self.assertRaises(PluginError):
            fetch_sample("  ", opener=opener)
        self.assertEqual(opener.calls, [])


if __name__ == "__main__":
    unittest.main()
