import io
import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from contractlens.api import app
from contractlens.suggestions import suggest
from test_compare import example

CLIENT = TestClient(app)
SPECS = {"before": example("before"), "after": example("after")}
SCENARIO = {"category": "negative", "title": "Omit the field",
            "procedure": "Submit the previous body without phoneNumber.",
            "verify": "Check the rejection matches the API requirements."}


class ApiTests(unittest.TestCase):
    def test_compare_and_invalid_inputs(self):
        response = CLIENT.post("/api/compare", json=SPECS)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["findings"][0]["id"], "F001")
        self.assertEqual(CLIENT.post("/api/compare", json={"before": {}, "after": {}}).status_code, 422)

    def test_disabled_ai(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "", "OPENAI_MODEL": ""}):
            self.assertFalse(CLIENT.get("/api/config").json()["ai_available"])
            response = CLIENT.post("/api/suggestions", json={**SPECS, "finding_id": "F001"})
            self.assertEqual(response.status_code, 503)

    def test_suggestions_use_only_a_verified_finding(self):
        with patch("contractlens.api.model_enabled", return_value=True), \
                patch("contractlens.api.suggest", return_value={"scenarios": [SCENARIO]}) as model:
            self.assertEqual(CLIENT.post("/api/suggestions", json={**SPECS, "finding_id": "missing"}).status_code, 404)
            model.assert_not_called()
            response = CLIENT.post("/api/suggestions", json={**SPECS, "finding_id": "F001"})
            self.assertEqual(response.json(), {"finding_id": "F001", "scenarios": [SCENARIO]})
            self.assertEqual(model.call_args.args[0]["field"], ["phoneNumber"])

    def test_provider_payload_minimizes_shared_fields_and_validates_response(self):
        finding = CLIENT.post("/api/compare", json=SPECS).json()["findings"][0]
        def model_response(suggestion):
            return io.BytesIO(json.dumps({"status": "completed", "output": [{"content": [
                {"type": "output_text", "text": json.dumps({"scenarios": [suggestion]})}]}]}).encode())
        with patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test", "OPENAI_MODEL": "unit-test"}), \
                patch("contractlens.suggestions.urlopen", side_effect=[model_response(SCENARIO),
                    model_response({**SCENARIO, "category": "invented"})]) as model:
            self.assertEqual(suggest(finding)["scenarios"], [SCENARIO])
            payload = json.loads(model.call_args.args[0].data)
            self.assertFalse(payload["store"])
            self.assertTrue(payload["text"]["format"]["strict"])
            self.assertEqual(set(json.loads(payload["input"])), {"rule", "operation", "location", "field", "impact"})
            with self.assertRaises(RuntimeError):
                suggest(finding)
