"""Connections to the isolated Compose services used by the seed installer."""

from contextlib import ExitStack
from typing import TYPE_CHECKING, Any

import boto3
import grpc
import psycopg
from authzed.api.v1.permission_service_pb2_grpc import PermissionsServiceStub
from botocore.config import Config as S3ClientConfig
from openlet_sdk.config import Config, DatabaseSettings, secret
from psycopg import sql
from qdrant_client import QdrantClient

from .compose import Stack

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

type Row = tuple[Any, ...]


def copy(
    db: psycopg.Connection[Row], table: str, columns: str, rows: list[Row]
) -> None:
    if rows:
        stmt = sql.SQL("COPY {} ({}) FROM STDIN").format(
            sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, columns.split())),
        )
        with db.cursor().copy(stmt) as stream:
            for row in rows:
                stream.write_row(row)


class Services:
    def __init__(
        self, scope: ExitStack, stack: Stack, config: Config, has_leta: bool
    ) -> None:
        dependencies = config["dependencies"]
        self.config = config
        pg = dependencies["postgres"]
        pg_port = int(stack.port("postgres", pg["port"]).rsplit(":", 1)[1])

        def connect(settings: DatabaseSettings) -> psycopg.Connection[Row]:
            return scope.enter_context(
                psycopg.connect(
                    host="127.0.0.1",
                    port=pg_port,
                    dbname=settings["name"],
                    user=settings["user"],
                    password=secret(settings["password"]),
                    sslmode=pg["sslmode"],
                    autocommit=True,
                    connect_timeout=10,
                )
            )

        self.platform = connect(config["services"]["platform"]["database"])
        self.letfs = connect(config["services"]["letfs"]["database"])
        self.leta = (
            connect(config["services"]["leta"]["database"]) if has_leta else None
        )
        spice = dependencies["spicedb"]
        channel = scope.enter_context(
            grpc.insecure_channel(
                stack.port("spicedb", spice["address"].rsplit(":", 1)[1])
            )
        )
        self.graph = PermissionsServiceStub(channel)
        self.graph_headers = (("authorization", "Bearer " + secret(spice["key"])),)
        qdrant = dependencies["qdrant"]
        self.qdrant = QdrantClient(
            host="127.0.0.1",
            grpc_port=int(
                stack.port("qdrant", qdrant["address"].rsplit(":", 1)[1]).rsplit(
                    ":", 1
                )[1]
            ),
            prefer_grpc=True,
            api_key=secret(qdrant["api_key"]),
            https=qdrant["tls"],
            check_compatibility=False,
        )
        scope.callback(self.qdrant.close)
        self.collection = qdrant["collection"]
        obj = dependencies["s3"]
        self.bucket = obj["bucket"]
        self.s3: S3Client = boto3.client(  # pyright: ignore[reportUnknownMemberType]  # Only the S3 overload has installed stubs.
            "s3",
            endpoint_url=f"http://{stack.port('rustfs', 9000)}",
            region_name=obj["region"],
            aws_access_key_id=secret(obj["access_key_id"]),
            aws_secret_access_key=secret(obj["secret_access_key"]),
            config=S3ClientConfig(s3={"addressing_style": "path"}),
        )
        scope.callback(self.s3.close)
