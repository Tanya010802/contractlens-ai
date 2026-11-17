"""Deterministic, evidence-backed compatibility checks for OpenAPI JSON."""
from collections import Counter
from urllib.parse import unquote
import re

METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
COMPOSITION = {"allOf", "anyOf", "oneOf", "not", "if", "$id", "$dynamicRef", "prefixItems"}
REF_SIBLINGS = COMPOSITION | {"type", "required", "properties", "items", "enum"}


class SpecError(ValueError):
    """An input specification cannot be read safely by the comparison engine."""


def pointer(path):
    return "".join("/" + part.replace("~", "~0").replace("/", "~1") for part in path)


class Document:
    def __init__(self, data, label, warnings):
        if (not isinstance(data, dict)
                or not re.fullmatch(r"3\.[01]\.\d+", str(data.get("openapi", "")))
                or not isinstance(data.get("paths"), dict)):
            raise SpecError(f"{label}: expected an OpenAPI 3.0 or 3.1 JSON document with a paths object")
        self.data = data
        self.label = label
        self.warnings = warnings

    def warn(self, path, reason):
        message = f"{self.label} {pointer(path) or '/'}: {reason}"
        if message not in self.warnings:
            self.warnings.append(message)

    def read(self, path):
        node = self.data
        for part in path:
            if isinstance(node, list):
                if not re.fullmatch(r"0|[1-9][0-9]*", part):
                    raise KeyError(part)
                node = node[int(part)]
            else:
                node = node[part]
        return node

    def resolve(self, path):
        seen = set()
        while True:
            if path in seen:
                raise SpecError(f"{self.label} {pointer(path)}: circular reference chain")
            seen.add(path)
            try:
                node = self.read(path)
            except (KeyError, TypeError, IndexError, ValueError) as exc:
                raise SpecError(f"{self.label} {pointer(path)}: reference target not found") from exc
            if not isinstance(node, dict):
                self.warn(path, "expected an object; skipped")
                return None, path
            if "$ref" not in node:
                return node, path
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/"):
                self.warn(path, "only same-document JSON Pointer references are supported; skipped")
                return None, path
            if node.keys() & REF_SIBLINGS:
                self.warn(path, "reference with adjacent validation keywords; skipped")
                return None, path
            parts = unquote(ref[1:]).split("/")[1:]
            if any(re.search(r"~(?![01])", part) for part in parts):
                raise SpecError(f"{self.label} {pointer(path)}: invalid JSON Pointer escape")
            path = tuple(part.replace("~1", "/").replace("~0", "~") for part in parts)


def mapping(node, key):
    value = node.get(key, {})
    if not isinstance(value, dict):
        raise SpecError(f"expected {key!r} to be an object")
    return value


def required(node):
    value = node.get("required", [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise SpecError("schema 'required' must be an array of strings")
    return value


class Comparison:
    def __init__(self, before, after):
        self.warnings = []
        self.before = Document(before, "before", self.warnings)
        self.after = Document(after, "after", self.warnings)
        self.findings = []
        self.operation = ""
        self.location = ""

    def add(self, rule, field, impact, old_path, new_path, old_value, new_value):
        finding = {
            "id": f"F{len(self.findings) + 1:03}",
            "rule": rule, "priority": "high", "operation": self.operation,
            "location": self.location, "field": list(field), "impact": impact,
            "before": {"pointer": pointer(old_path), "value": old_value},
            "after": {"pointer": pointer(new_path), "value": new_value},
        }
        self.findings.append(finding)

    def content(self, old_path, new_path, direction):
        old, old_path = self.before.resolve(old_path)
        new, new_path = self.after.resolve(new_path)
        if old is None or new is None:
            return
        label = self.location
        old_media, new_media = mapping(old, "content"), mapping(new, "content")
        for media in sorted(old_media.keys() & new_media.keys()):
            self.location = f"{label} · {media}"
            old_item, new_item = old_media[media], new_media[media]
            if isinstance(old_item, dict) and isinstance(new_item, dict) and "schema" in old_item and "schema" in new_item:
                self.schema(old_path + ("content", media, "schema"),
                            new_path + ("content", media, "schema"), direction, (), set())
        self.location = label

    def schema(self, old_path, new_path, direction, field, ancestors):
        if len(field) > 64:
            self.after.warn(new_path, "schema traversal depth limit reached")
            return
        old, old_path = self.before.resolve(old_path)
        new, new_path = self.after.resolve(new_path)
        pair = (old_path, new_path)
        if old is None or new is None or pair in ancestors:
            return
        for doc, path, node in ((self.before, old_path, old), (self.after, new_path, new)):
            if node.keys() & COMPOSITION:
                doc.warn(path, "schema composition or resource boundary; skipped")
                return
        old_props, new_props = mapping(old, "properties"), mapping(new, "properties")
        if direction == "request":
            self.request_fields(old, new, old_path, new_path, field, new_props)
        else:
            for name in sorted(old_props.keys() - new_props.keys()):
                self.add("response_field_removed", field + (name,),
                         "Clients that read this response field may need to change.",
                         old_path + ("properties", name), new_path + (("properties",) if "properties" in new else ()),
                         "declared", "not declared")
        if "type" in old and "type" in new and old["type"] != new["type"]:
            old_types = old["type"] if isinstance(old["type"], list) else [old["type"]]
            new_types = new["type"] if isinstance(new["type"], list) else [new["type"]]
            # JSON Schema integers also satisfy a number schema.
            accepted, candidates = (new_types, old_types) if direction == "request" else (old_types, new_types)
            if any(kind not in accepted and not (kind == "integer" and "number" in accepted)
                   for kind in candidates):
                self.add(f"{direction}_type_changed", field,
                         "The type change may affect payloads supported by existing clients.",
                         old_path + ("type",), new_path + ("type",), old["type"], new["type"])

        children = [(("properties", name), (name,)) for name in sorted(old_props.keys() & new_props.keys())]
        if "items" in old and "items" in new:
            children.append((("items",), ("[]",)))
        for suffix, child in children:
            self.schema(old_path + suffix, new_path + suffix, direction, field + child, ancestors | {pair})

    def request_fields(self, old, new, old_path, new_path, field, new_props):
        old_required = required(old)
        for index, name in enumerate(required(new)):
            if name in old_required:
                continue
            if name in new_props:
                property_schema, _ = self.after.resolve(new_path + ("properties", name))
                if property_schema is not None and property_schema.get("readOnly") is True:
                    continue
            self.add("request_field_required", field + (name,),
                     "Requests that previously omitted this field may now fail validation.",
                     old_path + (("required",) if "required" in old else ()),
                     new_path + ("required", str(index)), old_required, name)

    def operations(self, doc):
        result = {}
        for route in sorted(doc.data["paths"]):
            if not route.startswith("/"):
                continue
            path = ("paths", route)
            item, path = doc.resolve(path)
            if item is not None:
                for method in sorted(item.keys() & METHODS):
                    if not isinstance(item[method], dict):
                        raise SpecError(f"{doc.label} {pointer(path + (method,))}: invalid operation")
                    result[(route, method)] = (item[method], path + (method,))
        return result

    def run(self):
        old_ops, new_ops = self.operations(self.before), self.operations(self.after)
        for (route, method), (old, old_path) in old_ops.items():
            self.operation = f"{method.upper()} {route}"
            if (route, method) not in new_ops:
                # A skipped path item can hide operations, so avoid reporting it as removed.
                new_paths = self.after.data["paths"]
                if route in new_paths and self.after.resolve(("paths", route))[0] is None:
                    continue
                self.location = "Operation"
                new_parent = ("paths", route) if route in new_paths else ("paths",)
                self.add("operation_removed", (), "Applications calling this endpoint may fail.",
                         old_path, new_parent, "declared", "not declared")
                continue
            new, new_path = new_ops[(route, method)]
            if "requestBody" in old and "requestBody" in new:
                self.location = "Request body"
                self.content(old_path + ("requestBody",), new_path + ("requestBody",), "request")
            self.responses(old, new, old_path, new_path)

        summary = Counter(finding["priority"] for finding in self.findings)
        return {"findings": self.findings, "warnings": self.warnings,
                "summary": {"total": len(self.findings), "high": summary["high"]}}

    def responses(self, old, new, old_path, new_path):
        old_responses, new_responses = mapping(old, "responses"), mapping(new, "responses")
        for status in sorted(old_responses.keys() & new_responses.keys()):
            self.location = f"Response {status}"
            self.content(old_path + ("responses", status), new_path + ("responses", status), "response")


def compare(before: dict, after: dict) -> dict:
    return Comparison(before, after).run()
