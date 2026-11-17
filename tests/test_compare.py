import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from contractlens import SpecError, compare

ROOT = Path(__file__).resolve().parent.parent


def example(version):
    return json.loads((ROOT / "examples" / f"{version}.json").read_text())


def request(schema):
    spec = example("before")
    spec["paths"]["/users"]["post"]["requestBody"]["content"]["application/json"]["schema"] = schema
    return spec


def ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


class ComparisonTests(unittest.TestCase):
    def test_sample_finds_mandatory_phone_with_source_evidence(self):
        before, after = example("before"), example("after")
        report = compare(before, after)
        self.assertEqual(report["summary"], {"total": 1, "high": 1})
        finding, = report["findings"]
        self.assertEqual(finding["operation"], "POST /users")
        self.assertEqual(finding["field"], ["phoneNumber"])
        self.assertEqual(finding["before"]["pointer"], "/components/schemas/CreateUser/required")
        self.assertEqual(finding["after"]["pointer"], "/components/schemas/CreateUser/required/2")
        self.assertEqual(finding["after"]["value"], after["components"]["schemas"]["CreateUser"]["required"][2])

    def test_nested_array_objects_with_escaped_local_pointers(self):
        before = request({"type": "object", "properties": {"contacts": {"type": "array", "items": ref("A~1%20B~0")}}})
        before["components"]["schemas"]["A/ B~"] = {"type": "object", "properties": {"email": {"type": "string"}}}
        after = copy.deepcopy(before)
        after["components"]["schemas"]["A/ B~"]["required"] = ["email"]
        finding, = compare(before, after)["findings"]
        self.assertEqual(finding["field"], ["contacts", "[]", "email"])
        self.assertEqual(finding["after"]["pointer"], "/components/schemas/A~1 B~0/required/0")

    def test_recursive_schema_traversal_terminates(self):
        before = request(ref("Tree"))
        before["components"]["schemas"]["Tree"] = {"properties": {"child": ref("Tree"), "label": {}}}
        after = copy.deepcopy(before)
        after["components"]["schemas"]["Tree"]["required"] = ["label"]
        finding, = compare(before, after)["findings"]
        self.assertEqual(finding["field"], ["label"])

    def test_removed_operation(self):
        before = example("before")
        after = copy.deepcopy(before)
        after["paths"] = {}
        finding, = compare(before, after)["findings"]
        self.assertEqual(finding["rule"], "operation_removed")
        self.assertEqual(finding["before"]["pointer"], "/paths/~1users/post")
        self.assertEqual(finding["after"]["pointer"], "/paths")

    def test_removes_nested_response_field(self):
        before = example("before")
        after = copy.deepcopy(before)
        for spec, props in ((before, {"token": {"type": "string"}}), (after, {})):
            response = spec["paths"]["/users"]["post"]["responses"]["201"]
            response["content"] = {"application/json": {"schema": {"properties": {"data": {"properties": props}}}}}
        finding, = compare(before, after)["findings"]
        self.assertEqual(finding["rule"], "response_field_removed")
        self.assertEqual(finding["field"], ["data", "token"])

    def test_request_type_direction_number_vs_integer(self):
        integer, number = request({"type": "integer"}), request({"type": "number"})
        self.assertEqual(compare(integer, number)["findings"], [])
        finding, = compare(number, integer)["findings"]
        self.assertEqual(finding["rule"], "request_type_changed")

    def test_readonly_field_is_not_reported_as_required_in_request(self):
        before = request({"properties": {"serverId": {"type": "string", "readOnly": True}}})
        after = copy.deepcopy(before)
        after["paths"]["/users"]["post"]["requestBody"]["content"]["application/json"]["schema"]["required"] = ["serverId"]
        self.assertEqual(compare(before, after)["findings"], [])

    def test_same_spec_has_no_findings(self):
        before = example("before")
        self.assertEqual(compare(before, before)["findings"], [])

    def test_skipped_external_refs_and_composition_have_warnings(self):
        before = request({"$ref": "external.json#/User"})
        after = request({"type": "object", "required": ["phone"]})
        self.assertIn("same-document", compare(before, after)["warnings"][0])
        self.assertIn("composition", compare(request({"allOf": [{}]}), after)["warnings"][0])

    def test_missing_and_cyclic_reference_chain_errors(self):
        with self.assertRaisesRegex(SpecError, "target not found"):
            compare(request(ref("Missing")), example("after"))
        before = request(ref("Loop"))
        before["components"]["schemas"]["Loop"] = ref("Loop")
        with self.assertRaisesRegex(SpecError, "circular"):
            compare(before, example("after"))

    def test_cli_exit_code_for_high_risk(self):
        process = subprocess.run([sys.executable, "-B", "-m", "contractlens", "examples/before.json",
                                  "examples/after.json", "--fail-on-high"],
                                 cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(process.returncode, 1, process.stderr)
        self.assertEqual(json.loads(process.stdout)["summary"]["high"], 1)
