import json


def own_body(text):
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


def render(metadata, body, children):
    fields = metadata.model_dump()
    fields["children"] = children
    return "---\n" + json.dumps(fields, ensure_ascii=False, indent=2) + "\n---\n\n" + own_body(body)
