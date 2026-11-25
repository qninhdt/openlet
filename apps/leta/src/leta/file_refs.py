"""Atomic composer references; names are labels, never file locators or capabilities."""

import re
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import PurePosixPath
from uuid import UUID

import grpc
from mirage import FileStat, FileType
from openlet_api.letfs.v1 import letfs_pb2 as fs
from openlet_sdk.config import JSON

from .auth import Actor
from .config import Services

PATTERN = re.compile(
    r":(?:file|folder)\[((?:\\.|[^\]\\\n]){1,1024})\]\{name=([\w:-]+/[\w:-]+)\}"
)
PATH_PATTERN = re.compile(
    r"(?<!!)\[((?:\\.|[^\]\\\n]){1,1024})\]\("
    r"(?:<((?:/(?:shared|chat|user)|~)(?:/(?:\\.|[^>\\\n]){0,4096})?)>"
    r"|((?:/(?:shared|chat|user)|~)(?:/(?:\\.|[^\s)\\\n]){0,4096})?))\)"
)


def token(label: str, storage: str, node: str, *, folder: bool = False) -> str:
    label = re.sub(r"([\\\[\]])", r"\\\1", label.replace("\n", " "))
    return f":{'folder' if folder else 'file'}[{label}]{{name={storage}/{node}}}"


def stored_target(metadata: FileStat, path: str) -> tuple[UUID, UUID]:
    storage, node = metadata.extra.get("storage_id"), metadata.extra.get("node_id")
    if (
        metadata.type not in (FileType.FILE, FileType.DIRECTORY)
        or not isinstance(storage, str)
        or not isinstance(node, str)
    ):
        raise ValueError(f"Choose a stored file or folder: {path}")
    return UUID(storage), UUID(node)


async def resolve(
    content: str, attachments: list[str], stat: Callable[[str], Awaitable[FileStat]]
) -> tuple[str, str]:
    async def reference(path: str, label: str | None = None) -> str:
        metadata = await stat(path)
        storage, node = stored_target(metadata, path)
        return token(
            label if label is not None else metadata.name,
            str(storage),
            str(node),
            folder=metadata.type == FileType.DIRECTORY,
        )

    parts: list[str] = []
    end = 0
    for match in PATH_PATTERN.finditer(content):
        label = re.sub(r"\\(.)", r"\1", match.group(1))
        raw_path = match.group(2) if match.group(2) is not None else match.group(3)
        path = re.sub(r"\\(.)", r"\1", raw_path)
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


def _dedup_name(name: str, *, is_dir: bool, tag: str) -> str:
    ext = "" if is_dir else PurePosixPath(name).suffix
    stem = name[: len(name) - len(ext)] if ext else name
    suffix = f" ({tag}){ext}"
    max_stem_bytes = max(0, 255 - len(suffix.encode("utf-8")))
    encoded = stem.encode("utf-8")
    if len(encoded) > max_stem_bytes:
        stem = encoded[:max_stem_bytes].decode("utf-8", errors="ignore")
    return f"{stem}{suffix}"


async def validate(
    s: Services,
    workspace: UUID,
    sender: Actor,
    recipient: Actor,
    content: str,
    *,
    copy_request: UUID | None = None,
    copy_folders: bool = False,
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
        if node.kind not in (fs.NODE_KIND_FILE, fs.NODE_KIND_DIRECTORY):
            raise ValueError("only stored files and folders can be attached")
        if copy and node.kind == fs.NODE_KIND_DIRECTORY and not copy_folders:
            raise ValueError(
                f"The recipient cannot read {node.name}. Copy the folder only if authorized."
            )
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
                    path="attachments",
                ),
                metadata=actor.metadata,
                timeout=15,
            )
            primary_id = stable(copy_request, f"attachment/{storage}/{node_id}")
            transfer = fs.TransferNodeRequest(
                workspace_id=str(workspace),
                storage_id=str(storage),
                source=fs.NodeLocator(node_id=str(node_id)),
                destination_storage_id=str(target["storage_id"]),
                parent=fs.NodeLocator(node_id=parent.id),
                name=node.name,
                request_id=str(primary_id),
            )
            try:
                node = await s.files.CopyNode(
                    transfer, metadata=actor.metadata, timeout=30
                )
            except grpc.aio.AioRpcError as error:
                if error.code() != grpc.StatusCode.ALREADY_EXISTS:
                    raise
                dedup_id = stable(copy_request, f"attachment/{storage}/{node_id}/dedup")
                dedup_name = _dedup_name(
                    node.name,
                    is_dir=node.kind == fs.NODE_KIND_DIRECTORY,
                    tag=dedup_id.hex[:8],
                )
                node = await s.files.CopyNode(
                    fs.TransferNodeRequest(
                        workspace_id=str(workspace),
                        storage_id=str(storage),
                        source=fs.NodeLocator(node_id=str(node_id)),
                        destination_storage_id=str(target["storage_id"]),
                        parent=fs.NodeLocator(node_id=parent.id),
                        name=dedup_name,
                        request_id=str(dedup_id),
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
                **(
                    {
                        "mime": node.file.media_type,
                        "size": node.file.size_bytes,
                        "version": node.file.version,
                    }
                    if node.kind == fs.NODE_KIND_FILE
                    else {"kind": "folder"}
                ),
            }
        )
    return result
