import json
from pathlib import Path

from leta.api import create_app
from leta.http.models import CreateSchedule, HumanResponse, SendMessage

CONTRACT = Path(__file__).parents[3] / "packages/contracts/public/openapi.yaml"


def public_refs(value):
    if isinstance(value, dict):
        return {key: public_refs(item) for key, item in value.items()}
    if isinstance(value, list):
        return [public_refs(item) for item in value]
    if isinstance(value, str) and value.startswith("#/components/schemas/"):
        return value.replace("#/components/schemas/", "#/components/schemas/Leta", 1)
    return value


def test_public_leta_contract_matches_active_route_bodies_and_typed_responses():
    public = json.loads(CONTRACT.read_text())
    actual = create_app().openapi()
    paths = {
        path: methods
        for path, methods in actual["paths"].items()
        if path.startswith("/v1/")
    }
    assert len(paths) == 24
    for path, methods in paths.items():
        assert public["paths"][path].keys() == methods.keys()
        for method, operation in methods.items():
            documented = public["paths"][path][method]
            assert documented.get("requestBody") == public_refs(
                operation.get("requestBody")
            )
            assert documented.get("parameters", [])[
                : len(operation.get("parameters", []))
            ] == public_refs(operation.get("parameters", []))
            success = "201" if "201" in operation["responses"] else "200"
            assert documented["responses"][success] == public_refs(
                operation["responses"][success]
            )
            media = (
                "text/event-stream" if path.endswith("/events") else "application/json"
            )
            assert documented["responses"][success]["content"][media]["schema"]
            if method in {"post", "patch", "delete"}:
                assert documented["responses"]["202"]["content"]["application/json"][
                    "schema"
                ]["$ref"].endswith("/LetaPendingCommand")
    for name, schema in actual["components"]["schemas"].items():
        if name not in {"HTTPValidationError", "ValidationError"}:
            saved = dict(public["components"]["schemas"]["Leta" + name])
            saved.pop("examples", None)
            assert saved == public_refs(schema), name
    for model in (SendMessage, HumanResponse, CreateSchedule):
        for example in public["components"]["schemas"]["Leta" + model.__name__][
            "examples"
        ]:
            model.model_validate(example)


def test_public_contract_has_no_dangling_local_references():
    document = json.loads(CONTRACT.read_text())

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "$ref" and item.startswith("#/"):
                    target = document
                    for part in item[2:].split("/"):
                        target = target[part.replace("~1", "/").replace("~0", "~")]
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(document)
