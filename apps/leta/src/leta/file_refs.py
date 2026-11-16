"""Atomic composer references; names are labels, never file locators or capabilities."""

import re
from uuid import UUID

from openlet_api.letfs.v1 import letfs_pb2 as fs
from openlet_sdk.config import JSON

from .auth import Actor
from .config import Services

PATTERN = re.compile(r":file\[((?:\\.|[^\]\\\n]){1,1024})\]\{name=([\w:-]+/[\w:-]+)\}")


def plaintext(content: str) -> str:
    return PATTERN.sub(lambda match: re.sub(r"\\(.)", r"\1", match[1]), content)


def references(content: str) -> list[tuple[str, UUID, UUID]]:
    found: list[tuple[str, UUID, UUID]] = []
    for match in PATTERN.finditer(content):
        label, target = match.groups()
        storage, node = target.split("/", 1)
        try:
            pair = (re.sub(r"\\(.)", r"\1", label), UUID(storage), UUID(node))
        except ValueError:
            raise ValueError("file references require storage and node UUIDs") from None
        if len(pair[0]) > 255:
            raise ValueError("file labels cannot exceed 255 characters")
        if not any(item[1:] == pair[1:] for item in found):
            found.append(pair)
    if len(found) > 20:
        raise ValueError("a message can reference at most 20 files")
    return found


async def validate(
    s: Services, workspace: UUID, sender: Actor, recipient: Actor, content: str
) -> list[JSON]:
    result: list[JSON] = []
    for label, storage, node_id in references(content):
        await s.auth.require(sender, "storage", storage, "read")
        await s.auth.require(recipient, "storage", storage, "read")
        node: fs.Node = await s.files.Stat(
            fs.NodeRequest(
                workspace_id=str(workspace),
                storage_id=str(storage),
                target=fs.NodeLocator(node_id=str(node_id)),
            ),
            metadata=sender.metadata,
            timeout=15,
        )
        if node.kind != fs.NODE_KIND_FILE:
            raise ValueError("only files can be attached to messages")
        result.append(
            {
                "storage_id": str(storage),
                "node_id": str(node_id),
                "label": label,
                "name": node.name,
                "mime": node.file.media_type,
                "size": node.file.size_bytes,
                "version": node.file.version,
            }
        )
    return result
