import csv
import io
import json
import random
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from letfs_ingest.parser.text_split import estimate_tokens, split_text

TAXONOMY = {
    "document": "research_paper report article book manual contract other",
    "text": "content summary notes overview transcript other",
    "image": "photo screenshot chart diagram illustration other",
    "table": "records summary time_series other",
    "spreadsheet": "dataset financial tracker other",
    "presentation": "lecture pitch report other",
    "code": "source configuration notebook other",
    "other": "unknown",
}
SEMANTIC_TYPES = tuple(
    f"{family}:{kind}" for family, kinds in TAXONOMY.items() for kind in kinds.split()
)


class Metadata(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, populate_by_name=True
    )
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=600)
    semantic_type: Literal[SEMANTIC_TYPES] = Field(alias="type")
    context: str = Field(min_length=1, max_length=3000)


def sample_text(text: str, budget: int, windows: int = 8) -> str:
    if budget < 16 or windows < 2:
        raise ValueError("sampling requires at least 16 tokens and two windows")
    if estimate_tokens(text) <= budget:
        return text
    marker = "\n\n[... omitted ...]\n\n"
    count = min(windows, max(2, budget // 16))
    block_budget = max(1, (budget - estimate_tokens(marker) * (count - 1)) // count)
    blocks = split_text(text, block_budget)
    count = min(count, len(blocks))
    indices = sorted({round(i * (len(blocks) - 1) / (count - 1)) for i in range(count)})
    selected = [blocks[i] for i in indices]
    selected[-1] = text[-block_budget * 4 :]
    result = marker.join(selected)
    # Include omission markers in the serialized evidence budget.
    while estimate_tokens(result) > budget:
        largest = max(range(len(selected)), key=lambda i: len(selected[i]))
        selected[largest] = selected[largest][:-1]
        result = marker.join(selected)
    return result


def value_type(value: str) -> str:
    value = value.strip()
    if not value:
        return "null"
    if value.lower() in {"true", "false"}:
        return "boolean"
    if value.startswith("0") and len(value) > 1 and value[1].isdigit():
        return "string"
    try:
        int(value)
        return "integer"
    except ValueError:
        try:
            float(value)
            return "number"
        except ValueError:
            return "string"


def csv_profile(text: str, budget: int) -> str:
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    headers = next(reader, [])
    types = [Counter() for _ in headers]
    samples = []
    first = []
    last = []
    randomizer = random.Random(0)
    rows = 0
    for rows, row in enumerate(reader, 1):
        for index, counts in enumerate(types):
            counts[value_type(row[index] if index < len(row) else "")] += 1
        if rows <= 2:
            first.append(row)
        last = (last + [row])[-2:]
        if len(samples) < 8:
            samples.append(row)
        else:
            index = randomizer.randrange(rows)
            if index < len(samples):
                samples[index] = row
    columns = [
        {
            "name": name,
            "types": dict(counts),
            "null_rate": counts["null"] / rows if rows else 0,
        }
        for name, counts in zip(headers, types, strict=True)
    ]
    profile = {
        "delimiter": dialect.delimiter,
        "header": "first row (unverified)",
        "row_count": rows,
        "column_count": len(headers),
        "columns": columns,
        "samples": first + samples + last,
    }
    return sample_text(json.dumps(profile, ensure_ascii=False), budget)


async def enrich_tree(nodes, contents, ai):
    import asyncio
    import posixpath

    from letfs_ingest.processing.readme import (
        final_paths,
        own_body,
        render_readme,
        rewrite_links,
    )

    readmes = {
        node["parent_id"]: node
        for node in nodes
        if node["name"] == "README.md" and node["path"]
    }
    children = {node["id"]: [] for node in nodes}
    for node in nodes:
        if node["parent_id"] in children and node["name"] != "README.md":
            children[node["parent_id"]].append(node)
    source = next(node for node in nodes if not node["path"])
    parsed_source = source["kind"] == "file" and source["id"] in readmes
    metadata = {}
    semaphore = asyncio.Semaphore(ai.settings.concurrency)

    async def describe(node, body, summaries=""):
        mime = node["media_type"] or ""
        image = contents.get(node["id"]) if mime.startswith("image/") else None
        evidence = (
            csv_profile(body, ai.settings.evidence_tokens)
            if mime == "text/csv"
            else body
        )
        evidence = sample_text(
            json.dumps(
                {
                    "filename": node["name"],
                    "own_content": evidence,
                    "children": summaries,
                },
                ensure_ascii=False,
            ),
            ai.settings.evidence_tokens,
        )
        async with semaphore:
            metadata[node["id"]] = await ai.describe(evidence, image)

    leaves = [
        node
        for node in nodes
        if node["kind"] == "file"
        and not (parsed_source and node["id"] == source["id"])
        and not (node["path"] and node["name"] == "README.md")
    ]
    await asyncio.gather(
        *(
            describe(
                node,
                contents[node["id"]].decode("utf-8", errors="replace")
                if not (node["media_type"] or "").startswith("image/")
                else "",
            )
            for node in leaves
        )
    )
    folders = [
        node
        for node in nodes
        if node["kind"] == "directory" or (parsed_source and node["id"] == source["id"])
    ]
    for node in sorted(
        folders, key=lambda n: n["path"].count("/") + bool(n["path"]), reverse=True
    ):
        own_readme = readmes.get(node["id"])
        if own_readme is None:
            raise ValueError("artifact directory is missing README.md")
        body = own_body(contents[own_readme["id"]].decode("utf-8"))
        summaries = []
        for child in children[node["id"]]:
            owner = readmes[child["id"]] if child["kind"] == "directory" else child
            meta = metadata[owner["id"]]
            summaries.append(
                {
                    "title": meta.title,
                    "description": meta.description,
                    "type": meta.semantic_type,
                }
            )
        await describe(own_readme, body, summaries)
    if parsed_source:
        metadata[source["id"]] = metadata[readmes[source["id"]]["id"]]
    paths = final_paths(nodes, metadata)
    path_map = {node["path"]: paths[node["id"]] for node in nodes}
    rewritten = {}
    for node in nodes:
        if not node["path"] or not node["path"].endswith(".md"):
            continue
        body = rewrite_links(
            contents[node["id"]].decode("utf-8"),
            node["path"],
            paths[node["id"]],
            path_map,
        )
        if node["name"] == "README.md":
            body = own_body(body)
            parent = node["parent_id"]
            body = render_readme(
                metadata[node["id"]],
                body,
                [
                    (
                        posixpath.relpath(paths[child["id"]], paths[parent] or "."),
                        metadata[
                            readmes[child["id"]]["id"]
                            if child["kind"] == "directory"
                            else child["id"]
                        ],
                    )
                    for child in children[parent]
                ],
            )
        rewritten[node["id"]] = body.encode("utf-8")
    return paths, metadata, rewritten
