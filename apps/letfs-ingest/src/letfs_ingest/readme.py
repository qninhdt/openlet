import json

from openlet_sdk.config import JSON

from .providers import Metadata


def own_body(text: str) -> str:
    if text.startswith("---\n"):
        header, separator, body = text[4:].partition("\n---\n\n")
        if separator:
            try:
                fields = json.loads(header)
            except ValueError:
                return text
            if isinstance(fields, dict) and "children" in fields and "semantic_type" in fields:
                return body
    return text


def render(metadata: Metadata, body: str, children: dict[str, dict[str, JSON]]) -> str:
    fields = metadata.model_dump()
    fields["children"] = children
    return "---\n" + json.dumps(fields, ensure_ascii=False, indent=2) + "\n---\n\n" + own_body(body)
