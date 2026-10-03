"""Shared response identity and contract use without a concrete SEC transport."""
from dataclasses import fields, FrozenInstanceError, replace
import hashlib
from pathlib import Path
import subprocess
import sys
import unittest

from quantagent_platform.contracts import ContractError
from quantagent_platform import sec_client, sec_contracts, sec_source_identities
from tests.support.sec_samples import make_responses

ROOT = Path(__file__).resolve().parents[3]


class SecResponseContractTests(unittest.TestCase):
    def test_original_imports_share_one_frozen_response_and_fixed_constants(self):
        response_type = sec_contracts.SecResponse
        self.assertEqual(response_type.__module__, "quantagent_platform.sec_response_contracts")
        from quantagent_platform import sec_response_contracts as canonical
        self.assertIs(response_type, canonical.SecResponse)
        self.assertIs(sec_client.SecResponse, response_type)
        self.assertIs(sec_contracts.SEC_URLS, canonical.SEC_URLS)
        self.assertIs(sec_client.SEC_URLS, canonical.SEC_URLS)
        self.assertIs(sec_source_identities.SEC_URLS, canonical.SEC_URLS)
        self.assertEqual(sec_client.MAX_RESPONSE_BYTES, canonical.MAX_RESPONSE_BYTES)
        self.assertEqual(sec_contracts.MAX_RESPONSE_BYTES, canonical.MAX_RESPONSE_BYTES)
        self.assertEqual(canonical.MAX_RESPONSE_BYTES, 8 * 1024 * 1024)
        self.assertEqual([(f.name, f.type) for f in fields(response_type)],
                         [("kind", "str"), ("cik", "str"), ("url", "str"),
                          ("raw", "bytes"), ("sha256", "str"), ("retrieved_at", "str")])
        raw = b"synthetic response body"
        row = response_type("submissions", "0001507605", canonical.SEC_URLS[0][2],
                            raw, hashlib.sha256(raw).hexdigest(), "2026-09-24T11:59:00+00:00")
        self.assertIs(row.raw, raw)
        with self.assertRaises(FrozenInstanceError):
            row.kind = "changed"
        self.assertFalse(response_type.__dataclass_params__.repr)
        self.assertNotIn(raw.decode(), repr(row))
        self.assertTrue(all(isinstance(r, response_type) for r in make_responses()))

    def test_normalization_contract_imports_without_client_or_http_stack(self):
        script = '''
import importlib.abc
import sys
import urllib.request
from unittest.mock import patch
blocked = {"requests", "fastapi", "pydantic", "uvicorn", "httpx2"}
class BlockTransport(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in blocked:
            raise ImportError("concrete transport/HTTP import blocked: " + fullname)
with patch.object(urllib.request, "urlopen", side_effect=AssertionError("network forbidden")), patch.object(urllib.request, "build_opener", side_effect=AssertionError("transport construction forbidden")):
    sys.meta_path.insert(0, BlockTransport())
    # Startup composition may import concrete plugins; reload the contract separately.
    import quantagent_platform
    sys.modules.pop("quantagent_platform.sec_contracts", None)
    sys.modules.pop("quantagent_platform.sec_client", None)
    blocked.add("quantagent_platform.sec_client")
    from quantagent_platform.sec_contracts import SecResponse, MAX_RESPONSE_BYTES, SEC_URLS, normalize_sample
    assert SecResponse.__module__ == "quantagent_platform.sec_response_contracts"
    assert MAX_RESPONSE_BYTES == 8 * 1024 * 1024 and len(SEC_URLS) == 4
    assert "quantagent_platform.sec_client" not in sys.modules
print("pure SEC contract usable without transport")
'''
        result = subprocess.run([sys.executable, "-B", "-c", script], cwd=ROOT,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("pure SEC contract usable without transport", result.stdout)

    def test_normalization_preserves_raw_size_and_bytes_rejection(self):
        self.assertEqual(sec_contracts.MAX_RESPONSE_BYTES, sec_client.MAX_RESPONSE_BYTES)
        original = make_responses(retrieved_at="2026-09-24T11:59:00+00:00")
        for raw in (b"x" * (8 * 1024 * 1024 + 1), bytearray(b"{}")):
            with self.subTest(raw_type=type(raw).__name__, length=len(raw)):
                rows = list(original)
                rows[0] = replace(rows[0], raw=raw, sha256=hashlib.sha256(raw).hexdigest())
                with self.assertRaisesRegex(ContractError, "allowed shape or size"):
                    sec_contracts.normalize_sample(rows)


if __name__ == "__main__":
    unittest.main()
