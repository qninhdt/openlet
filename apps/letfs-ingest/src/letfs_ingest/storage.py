"""S3 object storage client and CRC32C checksum helpers for ingest."""

from __future__ import annotations

import asyncio
import base64
import struct
from typing import TYPE_CHECKING, cast

import boto3
import google_crc32c
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from openlet_sdk.config import Config, secret
from temporalio.exceptions import ApplicationError

if TYPE_CHECKING:
    from pathlib import Path

    from mypy_boto3_s3 import S3Client


def crc32c_base64(data: bytes) -> str:
    """Compute the base64-encoded CRC32C checksum of ``data``."""
    checksum = cast("int", google_crc32c.value(data))  # pyright: ignore[reportUnknownMemberType]
    return base64.b64encode(struct.pack(">I", checksum)).decode("ascii")


class S3Store:
    """Async wrapper over boto3 S3 operations with byte-budget enforcement."""

    def __init__(self, config: Config) -> None:
        settings = config["dependencies"]["s3"]
        self.bucket = settings["bucket"]
        addressing = "path" if settings.get("path_style", True) else "virtual"
        self.client: S3Client = boto3.client(  # pyright: ignore[reportUnknownMemberType]
            "s3",
            endpoint_url=settings["endpoint"],
            region_name=settings["region"],
            aws_access_key_id=secret(settings["access_key_id"]),
            aws_secret_access_key=secret(settings["secret_access_key"]),
            config=BotoConfig(s3={"addressing_style": addressing}),
        )

    def _get_bytes_sync(self, key: str, limit: int) -> bytes:
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=key)
            length = int(head.get("ContentLength", 0))
            if length > limit:
                raise ApplicationError(
                    f"blob {key} exceeds maximum allowed bytes ({limit})",
                    non_retryable=True,
                )
            obj = self.client.get_object(Bucket=self.bucket, Key=key)
            body = obj["Body"].read(limit + 1)
            if len(body) > limit:
                raise ApplicationError(
                    f"blob {key} exceeds maximum allowed bytes ({limit})",
                    non_retryable=True,
                )
            return bytes(body)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            raise ApplicationError(
                f"s3 read failed ({code}) for {key}",
                non_retryable=code in {"NoSuchKey", "404"},
            ) from exc

    async def get_bytes(self, key: str, limit: int) -> bytes:
        """Fetch an S3 object into memory up to ``limit`` bytes."""
        return await asyncio.to_thread(self._get_bytes_sync, key, limit)

    async def download_to_file(self, key: str, target: Path, limit: int) -> int:
        """Download an S3 object to ``target`` and return its byte length."""
        data = await self.get_bytes(key, limit)
        await asyncio.to_thread(target.write_bytes, data)
        return len(data)

    def _put_bytes_sync(self, key: str, data: bytes, media_type: str) -> str:
        checksum = crc32c_base64(data)
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=media_type,
            ChecksumCRC32C=checksum,
        )
        return checksum

    async def put_bytes(self, key: str, data: bytes, media_type: str) -> str:
        """Upload ``data`` to S3 with CRC32C verification and return the checksum."""
        return await asyncio.to_thread(self._put_bytes_sync, key, data, media_type)
