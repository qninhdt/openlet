"""Atomic composer references; names are labels, never file locators or capabilities."""

import re
from collections.abc import Awaitable, Callable
from dataclasses import replace
from uuid import UUID

from mirage import FileStat, FileType
from openlet_api.letfs.v1 import letfs_pb2 as fs
from openlet_sdk.config import JSON

from .auth import Actor
from .config import Services

PATTERN = re.compile(r":file\[((?:\\.|[^\]\\\n]){1,1024})\]\{name=([\w:-]+/[\w:-]+)\}")
PATH_PATTERN = re.compile(
    r":file\[((?:\\.|[^\]\\\n]){1,1024})\]\{path=((?:\\.|[^}\\\n]){1,4096})\}"
)


def token(label: str, storage: str, node: str) -> str:
    label = re.sub(r"([\\\[\]])", r"\\\1", label.replace("\n", " "))
    return f":file[{label}]{{name={storage}/{node}}}"


async def resolve(
    content: str, attachments: list[str], stat: Callable[[str], Awaitable[FileStat]]
) -> tuple[str, str]:
    async def reference(path: str, label: str | None = None) -> str:
        metadata = await stat(path)
        storage, node = metadata.extra.get("storage_id"), metadata.extra.get("node_id")
        if metadata.type != FileType.FILE or not storage or not node:
            raise ValueError(
                f"Cannot attach {path}: choose a stored file, not a directory or extracted artifact"
            )
        return token(
            label if label is not None else metadata.name, str(storage), str(node)
        )

    parts: list[str] = []
    end = 0
    for match in PATH_PATTERN.finditer(content):
        label, path = (re.sub(r"\\(.)", r"\1", value) for value in match.groups())
        parts.extend((content[end : match.start()], await reference(path, label)))
        end = match.end()
    parts.append(content[end:])
    normalized = "".join(parts)
    attached = [await reference(path) for path in attachments]
    references(normalized + "\n" + "\n".join(attached))
    if len(normalized) > 32000:
        raise ValueError(
            "Message content exceeds 32000 characters after resolving file mentions"
        )
    return normalized, "\n".join(attached)


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
    s: Services,
    workspace: UUID,
    sender: Actor,
    recipient: Actor,
    content: str,
    *,
    copy_request: UUID | None = None,
) -> list[JSON]:
    result: list[JSON] = []
    sources: list[tuple[str, UUID, UUID, fs.Node, bool]] = []
    for label, storage, node_id in references(content):
        await s.auth.require(sender, "storage", storage, "read")
        copy = copy_request is not None and not await s.auth.allowed(
            recipient, "storage", storage, "read"
        )
        if not copy:
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
        sources.append((label, storage, node_id, node, copy))
    for label, storage, node_id, node, copy in sources:
        if copy:
            from . import conversations
            from .agents import stable

            assert (
                copy_request is not None
                and sender.kind == "agent"
                and recipient.kind == "user"
            )
            target = await conversations.storage(s, sender.id, recipient.id)
            actor = (
                replace(sender, zed_token=str(target["zed_token"]))
                if target.get("zed_token")
                else sender
            )
            parent = await s.files.CreateDirectories(
                fs.CreateDirectoriesRequest(
                    workspace_id=str(workspace),
                    storage_id=str(target["storage_id"]),
                    base=fs.NodeLocator(node_id=str(target["root_node_id"])),
                    path=f"attachments/{copy_request}/{storage}/{node_id}",
                ),
                metadata=actor.metadata,
                timeout=15,
            )
            node = await s.files.CopyNode(
                fs.TransferNodeRequest(
                    workspace_id=str(workspace),
                    storage_id=str(storage),
                    source=fs.NodeLocator(node_id=str(node_id)),
                    destination_storage_id=str(target["storage_id"]),
                    parent=fs.NodeLocator(node_id=parent.id),
                    name=node.name,
                    request_id=str(
                        stable(copy_request, f"attachment/{storage}/{node_id}")
                    ),
                ),
                metadata=actor.metadata,
                timeout=30,
            )
            storage, node_id = UUID(node.storage_id), UUID(node.id)
            await s.auth.require(recipient, "storage", storage, "read")
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
