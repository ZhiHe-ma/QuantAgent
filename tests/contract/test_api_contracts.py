"""Shared API owner aliases and pure input models retain their public contract."""
from dataclasses import FrozenInstanceError
import importlib
from pathlib import Path
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from quantagent_platform import result_api, submission_api


class ApiContractTests(unittest.TestCase):
    def test_original_model_and_error_paths_export_the_same_owned_types(self):
        contracts = importlib.import_module("quantagent_platform.api_contracts")
        for module, names in (
            (result_api, ("ExactRef", "AgentSelection", "RecipeRef", "FinalResultRef", "StepSummary",
                          "ResultLinks", "RunSummary", "ReportArtifact", "ApiConfig", "ReadApiError",
                          "AuthenticationRequired", "AccessDenied", "RunNotFound", "ResultUnavailable",
                          "ArtifactIntegrityError")),
            (submission_api, ("SubmitRunRequest", "RegisteredFixture", "InvalidSubmission",
                              "SubmissionTooLarge", "IdempotencyConflict", "SubmissionPending",
                              "FixtureChanged", "ExecutionFailed")),
        ):
            for name in names:
                with self.subTest(name=name):
                    self.assertIs(getattr(module, name), getattr(contracts, name))

    def test_shared_config_and_request_data_do_not_read_files(self):
        contracts = importlib.import_module("quantagent_platform.api_contracts")
        with patch.object(Path, "read_bytes", side_effect=AssertionError("pure config must not read")), \
             patch.object(Path, "mkdir", side_effect=AssertionError("pure config must not write")):
            config = contracts.ApiConfig(Path("unopened"), "owner", "x" * 32)
            reference = contracts.RegisteredFixture(Path("unopened"), "0" * 64)
            self.assertEqual("0" * 64, reference.sha256)
            with self.assertRaises(FrozenInstanceError):
                config.owner_subject = "other"
            for token in ("x" * 31, " " * 32):
                with self.assertRaises(ValueError):
                    contracts.ApiConfig(Path("unopened"), "owner", token)
            body = {"contract_type": "quantagent.submit_run.v1", "fixture_id": "sample",
                    "fixture_sha256": "0" * 64, "request_id": "sample-request"}
            self.assertEqual(body, contracts.SubmitRunRequest.model_validate(body).model_dump(mode="json"))
            with self.assertRaises(ValidationError):
                contracts.SubmitRunRequest.model_validate({**body, "arbitrary_path": "unopened"})


if __name__ == "__main__":
    unittest.main()
