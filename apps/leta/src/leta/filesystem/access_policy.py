"""Check native authority before Mirage can return a cached representation."""

import errno
from urllib.parse import urlsplit

from mirage.observe.context import start_op
from mirage.policy import Deny, Policy, VfsContext
from mirage.vfs.types import Effect
from redis.exceptions import RedisError

from leta.filesystem.letfs_vfs import LetFSVFS


class AccessPolicy(Policy):
    def __init__(self, backends: dict[str, LetFSVFS]):
        self.backends = backends
        self.cache = None

    async def pre_vfs(self, ctx: VfsContext):
        try:
            return await self._check(ctx)
        except OSError as error:
            return Deny("filesystem operation refused", error=error)
        except RedisError:
            return Deny(
                "Redis cache unavailable",
                error=OSError(errno.EHOSTUNREACH, "Redis cache unavailable"),
            )

    async def _check(self, ctx: VfsContext):
        timer = start_op()
        backend = self.backends.get(ctx.prefix.rstrip("/"))
        if backend is None:
            return None
        content = ctx.call.effect == Effect.READ or (
            ctx.call.effect == Effect.COPY and not ctx.write
        )
        try:
            current = await backend.native_stat(ctx.path, content=content)
        except FileNotFoundError:
            if not (ctx.write and ctx.call.creates):
                raise
            # mkdir -p may create more than one absent ancestor.
            parent = ctx.path.dir
            while True:
                try:
                    await backend.native_stat(parent)
                    break
                except FileNotFoundError:
                    if parent.virtual == parent.dir.virtual:
                        raise
                    parent = parent.dir
            current = None
        cached = await self.cache.get_versioned(ctx.path.virtual)
        if cached is not None and (current is None or cached[1] != current.fingerprint):
            await self.cache.remove(ctx.path.virtual)
        if content and current is not None and current.node.kind == "file":
            # Warm derived reads can bypass native hooks, but still use this token.
            backend._record_read(ctx.path, current, 0, timer)
        return None


def cache_network(redis_url: str):
    # Mirage's socket ceiling also covers its own Redis cache connections.
    endpoint = urlsplit(redis_url)
    host = endpoint.hostname
    if not host:
        raise ValueError("Redis cache endpoint required")
    if ":" in host:
        host = f"[{host}]"
    return {"allowed_domains": [f"{host}:{endpoint.port or 6379}"]}
