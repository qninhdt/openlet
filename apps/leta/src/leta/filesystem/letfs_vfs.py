import asyncio
import errno
import posixpath
from dataclasses import dataclass
from uuid import UUID, uuid7

from mirage.cache.types import ABSENT_WRITE, MatchWrite, ReplaceRequest
from mirage.observe.context import record, start_op
from mirage.types import DirListing, FileStat, FileType, ListingVersion, PathSpec
from mirage.utils.key_prefix import mounted_path, strip_mount
from mirage.vfs import BaseVFS
from mirage.vfs.call import vfs_call
from mirage.vfs.types import Effect, Target
from openlet.clients.letfs import (
    ExistingText,
    FilesystemClient,
    Locator,
    SearchFilters,
    TextCreation,
    TextSelection,
)
from openlet.clients.letfs import (
    FileStat as NativeStat,
)
from openlet.errors import AppError
from openlet.rpc import Actor

MAX_READ_BYTES = 4 << 20
MAX_TEXT_BYTES = 1 << 20
MAX_TREE_ENTRIES = 10000


@dataclass(frozen=True)
class Mount:
    filesystem_id: str
    scope_id: str
    root_id: str
    prefix: str
    writable: bool

    def __post_init__(self):
        for value in (self.filesystem_id, self.scope_id, self.root_id):
            if str(UUID(value)) != value or not UUID(value).int:
                raise ValueError("mount requires canonical nonzero IDs")
        if (
            not self.prefix.startswith("/")
            or posixpath.normpath(self.prefix) != self.prefix
            or self.prefix == "/"
        ):
            raise ValueError("invalid mount prefix")


def file_stat(value: NativeStat) -> FileStat:
    node = value.node
    return FileStat(
        name=node.name,
        type=FileType.DIRECTORY if node.kind == "directory" else FileType.FILE,
        size=None if node.kind == "directory" else value.readable_size,
        modified=node.updated_at.isoformat() if node.updated_at else None,
        fingerprint=value.fingerprint,
        revision=f"{node.id}:{node.revision}",
        extra={
            "node_id": node.id,
            "storage_kind": value.storage_kind,
            "media_type": node.media_type,
            "readonly": node.readonly,
        },
    )


async def collect_body(body, limit=MAX_TEXT_BYTES) -> bytes:
    if isinstance(body, bytes):
        if len(body) > limit:
            raise OSError(errno.EFBIG, "small text limit exceeded")
        return body
    result = bytearray()
    try:
        async for chunk in body:
            if not isinstance(chunk, bytes):
                raise TypeError("file body chunks must be bytes")
            if len(chunk) > limit - len(result):
                raise OSError(errno.EFBIG, "small text limit exceeded")
            result.extend(chunk)
    finally:
        close = getattr(body, "aclose", None)
        if close is not None:
            await close()
    return bytes(result)


class LetFSVFS(BaseVFS):
    name = "letfs"
    caches_reads = True
    read_revalidatable = True
    supports_snapshot = True
    reads_ranges = True
    sizes_always_known = True
    listing_version = ListingVersion.NONE
    index_ttl = 0

    def __init__(self, client: FilesystemClient, actor: Actor, mount: Mount):
        super().__init__()
        if actor.kind != "leta":
            raise ValueError("agent filesystem requires root Leta authority")
        self.client, self.actor, self.mount = client, actor, mount

    def locator(self, path: PathSpec, **guards) -> Locator:
        return Locator(
            path=strip_mount(path.virtual, self.mount.prefix),
            root_id=self.mount.root_id,
            **guards,
        )

    async def call(self, method, *args, **kwargs):
        try:
            return await method(
                self.mount.filesystem_id,
                self.mount.scope_id,
                *args,
                actor=self.actor,
                **kwargs,
            )
        except AppError as error:
            code = {
                "missing": errno.ENOENT,
                "exists": errno.EEXIST,
                "forbidden": errno.EACCES,
                "invalid": errno.EINVAL,
                "limit": errno.EFBIG,
            }.get(error.kind)
            if code is None:
                raise
            raise OSError(code, str(error)) from error

    async def native_stat(self, path: PathSpec, *, content=False) -> NativeStat:
        return await self.call(
            self.client.stat, self.locator(path), content_check=content
        )

    async def stat(self, path: PathSpec) -> FileStat:
        return file_stat(await self.native_stat(path))

    def _record_read(self, path, stat, size, timer):
        record(
            "read",
            path.virtual,
            self.name,
            size,
            timer,
            fingerprint=stat.fingerprint,
            revision=file_stat(stat).revision,
        )

    async def _read(self, path: PathSpec, selection: TextSelection, fingerprint=None):
        timer = start_op()
        value = await self.call(
            self.client.read_text,
            self.locator(path),
            selection,
            expected_fingerprint=fingerprint,
        )
        self._record_read(path, value.stat, len(value.content), timer)
        return value

    async def read(self, path: PathSpec, offset: int = 0, size: int | None = None):
        value = await self._read(path, TextSelection("bytes", offset, size))
        return value.content

    @vfs_call(effect=Effect.READ, target=Target.FILE)
    async def read_text_lines(self, path: PathSpec, start_line: int, max_lines: int):
        return await self._read(
            path, TextSelection("lines", start_line=start_line, line_count=max_lines)
        )

    @vfs_call(effect=Effect.READ, target=Target.FILE)
    async def read_image(self, path: PathSpec):
        timer = start_op()
        value = await self.call(self.client.read_image, self.locator(path))
        self._record_read(path, value.stat, len(value.content), timer)
        return value

    async def first_lines(self, path: PathSpec, n: int):
        return (await self._read(path, TextSelection("head", line_count=n))).content

    async def last_lines(self, path: PathSpec, n: int):
        return (await self._read(path, TextSelection("tail", line_count=n))).content

    async def line_count(self, path: PathSpec):
        timer = start_op()
        value = await self.native_stat(path, content=True)
        self._record_read(path, value, 0, timer)
        return value.newline_count

    async def checksum(self, path: PathSpec, algorithm: str):
        timer = start_op()
        value = await self.call(self.client.text_metrics, self.locator(path), algorithm)
        self._record_read(path, value.stat, 0, timer)
        return value.digest if value.supported else None

    async def readdir(self, path: PathSpec, limit: int | None = None):
        page = await self.call(
            self.client.read_tree,
            self.locator(path),
            depth=1,
            limit=min(limit or MAX_TREE_ENTRIES, MAX_TREE_ENTRIES),
        )
        return DirListing(
            entries=[file_stat(item.stat) for item in page.items],
            partial=not page.complete,
        )

    async def read_tree(self, path: PathSpec):
        page = await self.call(self.client.read_tree, self.locator(path))
        if not page.complete:
            return None
        return {item.path: file_stat(item.stat) for item in page.items}

    @vfs_call(effect=Effect.METADATA)
    async def list_entries(self, path, depth, limit, cursor=None):
        return await self.call(
            self.client.read_tree,
            self.locator(path),
            depth=depth,
            limit=limit,
            cursor=cursor,
        )

    async def files_containing(self, path, text, *, whole_word, ignore_case):
        value = await self.call(
            self.client.text_search, self.locator(path), text, ignore_case=ignore_case
        )
        if not value.complete:
            return None
        return [
            mounted_path(path, posixpath.join(path.mount_path, item.path))
            for item in value.items
        ]

    async def lines_containing(self, path, text, *, ignore_case):
        timer = start_op()
        value = await self.call(
            self.client.text_search,
            self.locator(path),
            text,
            mode="lines",
            ignore_case=ignore_case,
        )
        if not value.complete:
            return None
        self._record_read(path, value.stat, len(value.content), timer)
        return value.content

    async def follow(self, path, n, interval):
        if n < 0 or interval <= 0:
            raise ValueError("invalid tail follow parameters")
        initial = await self._read(path, TextSelection("tail", line_count=n))

        async def lines():
            offset = initial.stat.readable_size
            identity = initial.stat.node.id
            pending = initial.content
            while True:
                end = pending.rfind(b"\n") + 1
                if end:
                    yield pending[:end]
                    pending = pending[end:]
                await asyncio.sleep(interval)
                current = await self.native_stat(path, content=True)
                if current.node.id != identity:
                    raise OSError(errno.ESTALE, "followed file was replaced")
                if current.readable_size < offset:
                    offset, pending = 0, b""
                if current.readable_size == offset:
                    continue
                try:
                    value = await self._read(
                        path, TextSelection("bytes", offset), current.fingerprint
                    )
                except AppError as error:
                    if error.kind == "conflict":
                        continue
                    raise
                pending += value.content
                offset += len(value.content)

        return lines()

    async def search(self, path, query):
        if set(query.options) - {"limit"}:
            raise ValueError("unsupported semantic search options")
        limit = query.options.get("limit", 10)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("semantic search limit must be between 1 and 50")
        results = await self.call(
            self.client.semantic_search,
            query.query,
            filters=SearchFilters(parent=self.locator(path)),
            limit=limit,
        )
        if results.degraded:
            raise OSError(errno.EHOSTUNREACH, "semantic search reranker unavailable")
        answer = []
        for item in results.items:
            relative = "/@" + item.node.id
            snippet = ""
            if item.matched is not None:
                relative += "".join(
                    "/" + child.filename for child in item.matched.breadcrumb[1:]
                )
                snippet = item.matched.snippet
            target = mounted_path(path, relative)
            # Hydration is current in LetFS; this also validates the emitted alias.
            await self.native_stat(target, content=True)
            answer.append((target.virtual, f"{target.virtual}\n{snippet}"))
        return answer

    async def search_many(self, paths, query):
        slots = asyncio.Semaphore(4)

        async def one(path):
            async with slots:
                return await self.search(path, query)

        ranked, records = {}, {}
        for group in await asyncio.gather(*(one(path) for path in paths)):
            for rank, (name, record_text) in enumerate(group):
                ranked[name] = ranked.get(name, 0) + 1 / (60 + rank)
                records[name] = record_text
        limit = query.options.get("limit", 10)
        return [
            (name, records[name])
            for name in sorted(ranked, key=lambda name: (-ranked[name], name))[:limit]
        ]

    @vfs_call(effect=Effect.READ, subtree=True)
    async def semantic_query(self, path, query):
        # Mirage declines its bulk search op under coded policies. The tool's
        # custom call still passes admission and native root/hit authorization.
        return await self.search(path, query)

    async def read_many(self, paths, limit):
        slots = asyncio.Semaphore(4)

        async def read_one(path):
            async with slots:
                stat = await self.native_stat(path, content=True)
                if stat.readable_size > min(limit, MAX_READ_BYTES):
                    return None
                value = await self._read(path, TextSelection(), stat.fingerprint)
                return path.virtual, value.content

        result, size = {}, 0
        for offset in range(0, len(paths), 4):
            values = await asyncio.gather(
                *(read_one(path) for path in paths[offset : offset + 4])
            )
            for item in values:
                if item is not None and len(item[1]) <= MAX_READ_BYTES - size:
                    result[item[0]] = item[1]
                    size += len(item[1])
            if size == MAX_READ_BYTES:
                break
        return result

    async def _target(self, path: PathSpec, *, absent=False):
        if not absent:
            try:
                current = await self.native_stat(path, content=True)
            except FileNotFoundError:
                pass
            else:
                return ExistingText(
                    self.locator(path, expected_node_id=current.node.id),
                    current.node.revision,
                    current.fingerprint,
                )
        parent = await self.native_stat(path.dir)
        return TextCreation(
            self.locator(path.dir, expected_parent_id=parent.node.id),
            posixpath.basename(path.vfs_path),
            str(uuid7()),
            node_id=str(uuid7()),
        )

    async def _mutate(self, path, method, *args, observed=None, **kwargs):
        timer = start_op()
        target = observed or await self._target(path)
        value = await self.call(method, target, *args, **kwargs)
        stat = file_stat(value.stat)
        record(
            "write",
            path.virtual,
            self.name,
            value.stat.readable_size,
            timer,
            fingerprint=stat.fingerprint,
            revision=stat.revision,
        )
        return stat

    @property
    def condition_support(self):
        return {"put": frozenset({"absent", "match"})}

    async def _replace(self, request: ReplaceRequest):
        body = await collect_body(request.body)
        if request.condition == ABSENT_WRITE:
            target = await self._target(request.path, absent=True)
        else:
            target = await self._target(request.path)
            if isinstance(request.condition, MatchWrite):
                if not isinstance(target, ExistingText):
                    raise OSError(errno.ESTALE, "file changed")
                expected = f"{target.locator.expected_node_id}:{target.revision}"
                if request.condition.version != expected:
                    raise OSError(errno.ESTALE, "file changed")
        return await self._mutate(
            request.path, self.client.write_text, body, observed=target
        )

    async def write(self, path, data, *, atomic=False):
        return await self._mutate(
            path, self.client.write_text, await collect_body(data)
        )

    @vfs_call(effect=Effect.WRITE, target=Target.FILE, creates=True)
    async def write_text(self, path, data, overwrite=False):
        return await self._mutate(
            path,
            self.client.write_text,
            await collect_body(data),
            observed=await self._target(path, absent=not overwrite),
        )

    async def append(self, path, data):
        return await self._mutate(
            path, self.client.append_text, await collect_body(data)
        )

    async def pwrite(self, path, data, offset):
        return await self._mutate(
            path,
            self.client.patch_text,
            content=await collect_body(data),
            offset=offset,
        )

    async def truncate(self, path, length, no_create=False):
        return await self._mutate(
            path, self.client.truncate_text, length, no_create=no_create
        )

    @vfs_call(effect=Effect.WRITE, target=Target.FILE)
    async def edit_text(self, path, old_text, new_text, replace_all=False):
        return await self._mutate(
            path,
            self.client.patch_text,
            old_text=old_text,
            content=new_text.encode("utf-8"),
            replace_all=replace_all,
        )

    async def create(self, path):
        try:
            return await self.stat(path)
        except FileNotFoundError:
            return await self._mutate(
                path,
                self.client.write_text,
                b"",
                observed=await self._target(path, absent=True),
            )

    async def mkdir(self, path, parents=False):
        parts = path.vfs_path.strip("/").split("/")
        if parents:
            locator = Locator(node_id=self.mount.root_id, root_id=self.mount.root_id)
        else:
            parent = await self.native_stat(path.dir)
            locator = self.locator(path.dir, expected_parent_id=parent.node.id)
            parts = parts[-1:]
        node = await self.call(
            self.client.create_directories, locator, parts, parents=parents
        )
        return file_stat(
            await self.call(
                self.client.stat, Locator(node_id=node.id, root_id=self.mount.root_id)
            )
        )

    async def _trash(self, path, *, directory=None, empty=False):
        node = (await self.native_stat(path)).node
        if directory is not None and (node.kind == "directory") != directory:
            raise OSError(
                errno.ENOTDIR if directory else errno.EISDIR, "wrong node kind"
            )
        await self.call(
            self.client.trash_node,
            self.locator(path, expected_node_id=node.id),
            revision=node.revision,
            empty_directory=empty,
        )

    async def unlink(self, path):
        await self._trash(path, directory=False)

    async def rmdir(self, path):
        await self._trash(path, directory=True, empty=True)

    async def rm_r(self, path):
        await self._trash(path)

    async def _copy_from(self, source, src, dst):
        if (
            not isinstance(source, LetFSVFS)
            or source.client is not self.client
            or source.actor != self.actor
            or source.mount.filesystem_id != self.mount.filesystem_id
        ):
            raise OSError(errno.ENOTSUP, "native LetFS copy requires the same backend")
        original = (await source.native_stat(src, content=True)).node
        parent = (await self.native_stat(dst.dir)).node
        node = await source.call(
            self.client.create_copy,
            original.id,
            parent.id,
            str(uuid7()),
            destination_scope_id=self.mount.scope_id,
            source_root_id=source.mount.root_id,
            destination_root_id=self.mount.root_id,
            name=posixpath.basename(dst.vfs_path),
            revision=original.revision,
        )
        return file_stat(
            await self.call(
                self.client.stat, Locator(node_id=node.id, root_id=self.mount.root_id)
            )
        )

    async def copy(self, src, dst):
        return await self._copy_from(self, src, dst)

    async def copy_from(self, source, src, dst):
        await self._copy_from(source, src, dst)

    async def dir_copy(self, src, dst):
        return await self._copy_from(self, src, dst)

    async def rename(self, src, dst):
        original = (await self.native_stat(src)).node
        parent = (await self.native_stat(dst.dir)).node
        node = await self.call(
            self.client.update_node,
            self.locator(src, expected_node_id=original.id),
            revision=original.revision,
            name=posixpath.basename(dst.vfs_path),
            parent=self.locator(dst.dir, expected_parent_id=parent.id),
        )
        return file_stat(
            await self.call(
                self.client.stat, Locator(node_id=node.id, root_id=self.mount.root_id)
            )
        )

    def storage_location(self):
        mount = self.mount
        return f"letfs:{mount.filesystem_id}:{mount.scope_id}:{mount.root_id}"

    async def before_full_walk(self, path, *, files=None):
        await self.native_stat(path, content=True)
        if files is not None and self.walk_limit >= 0 and files > self.walk_limit:
            raise OSError(errno.EFBIG, "filesystem walk limit exceeded")

    async def close(self):
        # Native client channels belong to the application, not an invocation.
        return None
