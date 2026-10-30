#!/usr/bin/env python3
"""Validate owned OpenAPI documents and captured real public response DTOs."""
import json
from pathlib import Path
import re
import sys
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]


def validate_document(document):
    assert document["openapi"].startswith("3.1.")
    ids = set()
    for path, methods in document["paths"].items():
        for method, operation in methods.items():
            assert method in {"get", "post", "put", "patch", "delete"}
            assert operation["operationId"] not in ids
            ids.add(operation["operationId"])
            parameters = operation.get("parameters", [])
            names = {p["name"] for p in parameters if p["in"] == "path" and p["required"]}
            assert names == set(re.findall(r"\{(\w+)\}", path)), path
            for security in operation.get("security", []):
                assert set(security) <= set(document["components"]["securitySchemes"])
    def refs(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "$ref":
                    assert child.startswith("#/"), child
                    node = document
                    for segment in child[2:].split("/"):
                        node = node[segment]
                else:
                    refs(child)
        elif isinstance(value, list):
            for child in value:
                refs(child)
    refs(document)
    for schema in document["components"]["schemas"].values():
        Draft202012Validator.check_schema(schema)


def main():
    public = json.loads((ROOT / "contracts/public/openapi.yaml").read_text())
    internal = json.loads((ROOT / "contracts/internal/openapi.yaml").read_text())
    validate_document(public)
    validate_document(internal)
    routes = [(re.compile("^" + re.sub(r"\{\w+\}", "[^/]+", path) + "$"), methods) for path, methods in public["paths"].items()]
    source = ROOT / ".local/test/histories/contracts/responses.jsonl"
    count = 0
    if source.is_file():
        for line in source.read_text().splitlines():
            response = json.loads(line)
            if response["path"].startswith("/internal/"):
                assert response["status"] == 404, "Envoy exposed an internal route"
                continue
            candidates = [methods for pattern, methods in routes if pattern.fullmatch(response["path"])]
            assert len(candidates) == 1, response["path"]
            operation = candidates[0][response["method"].lower()]
            schema_response = operation["responses"].get(str(response["status"]))
            assert schema_response, (response["path"], response["status"])
            schema = schema_response.get("content", {}).get("application/json", {}).get("schema")
            if schema:
                schema = dict(schema, components=public["components"])
                try:
                    Draft202012Validator(schema, format_checker=FormatChecker()).validate(response["body"])
                except Exception as error:
                    raise AssertionError((response["path"], response["status"], str(error))) from error
                count += 1
    elif "--responses" in sys.argv:
        raise AssertionError("run make test-e2e TEST=all first")
    print(f"OpenAPI references/schema checks passed; {count} captured response DTOs validated.")


if __name__ == "__main__":
    main()
