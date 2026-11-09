"""The seven filesystem/compute tools share one authorized Mirage session."""

import asyncio
import base64
import errno
import json
import shlex

from mirage.types import FileType, PathSpec, SearchQuery

from leta.filesystem.letfs_vfs import MAX_READ_BYTES, file_stat
from leta.filesystem.workspace import AgentWorkspace


class FilesystemTools:
    def __init__(self, invocation: AgentWorkspace):
        self.invocation = invocation
        self.session = invocation.session

    def path(self, value: str) -> PathSpec:
        if not value or "\0" in value:
            raise ValueError("nonempty virtual file path required")
        if value == "~" or value.startswith("~/"):
            value = "/home" + value[1:]
        return PathSpec.from_str_path(value, cwd=self.session.state.cwd)

    async def dispatch(self, method, path, **kwargs):
        value, _ = await self.session.vfs.dispatch(method, self.path(path), **kwargs)
        return value

    async def list_files(self, path="~", depth=1, limit=100, cursor=None):
        if not 1 <= depth <= 128 or not 1 <= limit <= 10000:
            raise ValueError("invalid listing depth or limit")
        result = await self.dispatch(
            "list_entries", path, depth=depth, limit=limit, cursor=cursor
        )
        return {
            "items": [
                {"path": item.path, **file_stat(item.stat).model_dump(mode="json")}
                for item in result.items
            ],
            "next_cursor": result.next_cursor,
            "complete": result.complete,
        }

    async def read_file(self, path, start_line=1, max_lines=200):
        if start_line < 1 or not 1 <= max_lines <= 10000:
            raise ValueError("invalid file line range")
        stat = await self.session.vfs.stat(self.path(path))
        if stat.type != FileType.FILE:
            raise IsADirectoryError(path)
        if stat.extra["storage_kind"] != "text" and (
            start_line != 1 or max_lines != 200
        ):
            raise ValueError("line selection is supported only for text files")
        if (stat.extra.get("media_type") or "").startswith("image/"):
            image = await self.dispatch("read_image", path)
            return [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "path": self.path(path).virtual,
                            "node_id": image.stat.node.id,
                            "width": image.width,
                            "height": image.height,
                            "sha256": image.sha256,
                        }
                    ),
                },
                {
                    "type": "image",
                    "mime_type": image.mime,
                    "base64": base64.b64encode(image.content).decode("ascii"),
                },
            ]
        if stat.extra["storage_kind"] != "text":
            return json.loads(await self.session.vfs.read(self.path(path)))
        value = await self.dispatch(
            "read_text_lines", path, start_line=start_line, max_lines=max_lines
        )
        return {
            "type": "text",
            "text": value.content.decode("utf-8"),
            "start_line": start_line,
            "offset": value.offset,
            "complete": value.offset + value.length == value.stat.readable_size,
        }

    async def write_file(self, path, content, overwrite=False):
        stat = await self.dispatch(
            "write_text", path, data=content.encode("utf-8"), overwrite=overwrite
        )
        return stat.model_dump(mode="json")

    async def edit_file(self, path, old_text, new_text, replace_all=False):
        stat = await self.dispatch(
            "edit_text",
            path,
            old_text=old_text,
            new_text=new_text,
            replace_all=replace_all,
        )
        return stat.model_dump(mode="json")

    async def run_shell(self, command, cwd="~", timeout_seconds=30):
        if not command or not 0 < timeout_seconds <= 300:
            raise ValueError("invalid command or timeout")
        size = 0

        async def bound_output(event):
            nonlocal size
            size += len(event.data)
            if size > MAX_READ_BYTES:
                raise OSError(errno.EFBIG, "command output limit exceeded")

        async with asyncio.timeout(timeout_seconds):
            execution = await self.session.shell(
                command, cwd=self.path(cwd).virtual, stream=True
            )
            result = await execution.collect(on_event=bound_output)
        return {
            "exit_code": result.exit_code,
            "stdout": (result.stdout or b"").decode("utf-8", errors="replace"),
            "stderr": (result.stderr or b"").decode("utf-8", errors="replace"),
        }

    async def run_python(self, code, timeout_seconds=30):
        return await self.run_shell(
            "python -c " + shlex.quote(code), timeout_seconds=timeout_seconds
        )

    async def semantic_search(self, query, paths=None, limit=10):
        if not query.strip() or not 1 <= limit <= 50:
            raise ValueError("invalid semantic search query or limit")
        if paths is None:
            paths = sorted(self.invocation.policy.backends)
        paths = list(dict.fromkeys(paths))
        if not paths:
            return []
        # Dispatch every scope so the same session policies judge every result.
        ranked, records = {}, {}
        for path in paths:
            items = await self.dispatch(
                "semantic_query", path, query=SearchQuery(query, {"limit": limit})
            )
            if items is None:
                raise OSError("semantic search unavailable for this path")
            for rank, (name, text) in enumerate(items):
                ranked[name] = ranked.get(name, 0) + 1 / (60 + rank)
                records[name] = text
        return [
            {"path": name, "text": records[name]}
            for name in sorted(ranked, key=lambda name: (-ranked[name], name))[:limit]
        ]
