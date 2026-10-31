import json
import posixpath
import re
from collections import Counter
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from openlet_processor.exporters import slug


def final_paths(nodes, metadata):
    readmes = {
        node["parent_id"]: node["id"]
        for node in nodes
        if node["name"] == "README.md" and node["path"]
    }
    names = {}
    paths = {}
    indices = {}
    counters = Counter()
    pending = sorted(nodes, key=lambda node: (node["path"].count("/"), node["path"]))
    for node in pending:
        old = node["path"]
        if not old:
            names[node["id"]] = ""
            continue
        name = PurePosixPath(old).name
        key = (node["parent_id"], PurePosixPath(name).suffix)
        counters[key] += 1
        original_index = re.fullmatch(r"untitled-(\d+)\.[^.]+", name)
        indices[node["id"]] = (
            int(original_index[1]) if original_index else counters[key]
        )
        if name == "README.md":
            renamed = name
        else:
            title = slug(
                metadata[
                    readmes[node["id"]] if node["kind"] == "directory" else node["id"]
                ].title
            )
            structural = (
                re.fullmatch(r"(\d+)-.+", name)
                if (node["kind"] == "directory" or name.endswith(".md"))
                else None
            )
            extension = PurePosixPath(name).suffix if node["kind"] == "file" else ""
            renamed = (
                f"{structural[1]}-{title}{extension}"
                if structural
                else title + extension
            )
        names[node["id"]] = renamed
    # Reserve all unsuffixed names before allocating collision suffixes.
    reserved = {(node["parent_id"], names[node["id"]]) for node in nodes}
    seen = set()
    for node in pending:
        name = names[node["id"]]
        parent = node["parent_id"]
        if (parent, name) in seen:
            index = indices[node["id"]]
            stem, extension = posixpath.splitext(name)
            candidate = f"{stem}-{index}{extension}"
            while (parent, candidate) in reserved:
                index += 1
                candidate = f"{stem}-{index}{extension}"
            name = candidate
            reserved.add((parent, name))
        seen.add((parent, name))
        paths[node["id"]] = posixpath.join(paths[parent], name) if node["path"] else ""
    return paths


def own_body(text: str) -> str:
    if text.startswith("---\n"):
        header, separator, body = text[4:].partition("\n---\n\n")
        if separator:
            try:
                metadata = json.loads(header)
            except ValueError:
                return text
            if isinstance(metadata, dict) and set(metadata) == {
                "title",
                "description",
                "type",
                "context",
                "children",
            }:
                return body
    return text


def rewrite_links(text, old_path, new_path, path_map):
    def replace(match):
        link = match[1]
        parsed = urlsplit(link)
        if parsed.scheme or parsed.netloc or not parsed.path:
            return match[0]
        old = posixpath.normpath(
            posixpath.join(posixpath.dirname(old_path), unquote(parsed.path))
        )
        if old not in path_map:
            return match[0]
        new = posixpath.relpath(path_map[old], posixpath.dirname(new_path) or ".")
        if parsed.query:
            new += "?" + parsed.query
        if parsed.fragment:
            new += "#" + parsed.fragment
        return f"]({new})"

    return re.sub(r"\]\(([^)\s]+)\)", replace, text)


def render_readme(metadata, body: str, children) -> str:
    fields = metadata.model_dump(by_alias=True)
    fields["children"] = {
        name: {
            key: meta.model_dump(by_alias=True)[key]
            for key in ("title", "description", "type")
        }
        for name, meta in children
    }
    return (
        "---\n" + json.dumps(fields, ensure_ascii=False, indent=2) + "\n---\n\n" + body
    )
