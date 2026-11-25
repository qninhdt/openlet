"""Initialize fresh databases or native service resources from OPENLET_CONFIG."""

import argparse
import asyncio
import os
from datetime import timedelta
from typing import TYPE_CHECKING, cast

import boto3
import grpc
import psycopg
from authzed.api.v1 import WriteSchemaRequest
from authzed.api.v1.schema_service_pb2_grpc import SchemaServiceStub
from botocore.exceptions import ClientError
from configure import ROOT, load, secret
from google.protobuf.duration_pb2 import Duration
from openlet_sdk.config import Config, DatabaseSettings
from psycopg import sql
from qdrant_client import QdrantClient, models
from temporalio.api.workflowservice.v1 import RegisterNamespaceRequest
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleUpdate,
)
from temporalio.service import RPCError, RPCStatusCode

if TYPE_CHECKING:
    from mypy_boto3_s3.literals import BucketLocationConstraintType


def databases(c: Config) -> None:
    pg = c["dependencies"]["postgres"]
    admin = c["deployment"]["postgres"]
    targets: list[DatabaseSettings] = [
        c["services"]["platform"]["database"],
        c["services"]["letfs"]["database"],
    ]
    targets += [
        c["deployment"]["temporal"]["database"],
        c["deployment"]["spicedb"]["database"],
    ]
    if "leta" in os.environ.get("COMPOSE_PROFILES", "").split(","):
        targets.append(c["services"]["leta"]["database"])
    temporal = c["deployment"]["temporal"]
    targets.append(
        {
            "name": temporal["visibility_database"],
            "user": temporal["database"]["user"],
            "password": temporal["database"]["password"],
        }
    )
    with psycopg.connect(
        host=pg["host"],
        port=pg["port"],
        dbname="postgres",
        user=admin["admin_user"],
        password=secret(admin["admin_password"]),
        sslmode=pg["sslmode"],
        autocommit=True,
    ) as db:
        if "observability" in os.environ.get("COMPOSE_PROFILES", "").split(","):
            cloud = c.get("observability")
            if cloud is None:
                raise ValueError("observability settings are required")
            if not db.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s", (cloud["postgres_user"],)
            ).fetchone():
                db.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(cloud["postgres_user"]),
                        sql.Literal(secret(cloud["postgres_password"])),
                    )
                )
            db.execute(
                sql.SQL("GRANT pg_monitor TO {}").format(
                    sql.Identifier(cloud["postgres_user"])
                )
            )
        for target in targets:
            if not db.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s", (target["user"],)
            ).fetchone():
                db.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(target["user"]),
                        sql.Literal(secret(target["password"])),
                    )
                )
            if not db.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s", (target["name"],)
            ).fetchone():
                db.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        sql.Identifier(target["name"]), sql.Identifier(target["user"])
                    )
                )


async def resources(c: Config) -> None:
    dep = c["dependencies"]
    graph = dep["spicedb"]
    channel = (
        grpc.secure_channel(graph["address"], grpc.ssl_channel_credentials())
        if graph["tls"]
        else grpc.insecure_channel(graph["address"])
    )
    with channel:
        await asyncio.to_thread(
            SchemaServiceStub(channel).WriteSchema,
            WriteSchemaRequest(
                schema=(ROOT / "packages/contracts/authz/schema.zed").read_text()
            ),
            metadata=(("authorization", "Bearer " + secret(graph["key"])),),
            timeout=30,
        )
    t = dep["temporal"]
    client = await Client.connect(t["address"], namespace=t["namespace"], tls=t["tls"])
    try:
        await client.workflow_service.register_namespace(
            RegisterNamespaceRequest(
                namespace=t["namespace"],
                workflow_execution_retention_period=Duration(
                    seconds=c["deployment"]["temporal"]["namespace_retention_hours"]
                    * 3600
                ),
            )
        )
    except RPCError as error:
        if error.status != RPCStatusCode.ALREADY_EXISTS:
            raise
    for owner, service in (
        ("platform", c["services"]["platform"]),
        ("letfs", c["services"]["letfs"]),
    ):
        interval = timedelta(seconds=service["maintenance"]["interval_seconds"])
        schedule = Schedule(
            action=ScheduleActionStartWorkflow(
                "Maintenance",
                id=f"{owner}-maintenance",
                task_queue=t["queues"]["platform"]
                if owner == "platform"
                else t["queues"]["letfs"],
            ),
            spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=interval)]),
            policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
        )
        identity = f"{owner}-maintenance"
        try:
            await client.create_schedule(identity, schedule)
        except ScheduleAlreadyRunningError:
            await client.get_schedule_handle(identity).update(
                lambda _: ScheduleUpdate(schedule=schedule)
            )
    vector = dep["qdrant"]
    host, port = vector["address"].rsplit(":", 1)
    q = QdrantClient(
        host=host,
        grpc_port=int(port),
        prefer_grpc=True,
        api_key=secret(vector["api_key"]),
        https=vector["tls"],
    )
    try:
        if not q.collection_exists(vector["collection"]):
            q.create_collection(
                vector["collection"],
                vectors_config=models.VectorParams(
                    size=c["models"]["embedding"]["dimensions"],
                    distance=models.Distance.COSINE,
                ),
            )
        for field in ("workspace_id", "blob_id"):
            q.create_payload_index(
                vector["collection"], field, models.PayloadSchemaType.KEYWORD, wait=True
            )
        q.create_payload_index(
            vector["collection"],
            "text",
            models.TextIndexParams(
                type=models.TextIndexType.TEXT,
                tokenizer=models.TokenizerType.WORD,
                scoring=True,
            ),
            wait=True,
        )
    finally:
        q.close()
    obj = dep["s3"]
    s3 = boto3.client(  # pyright: ignore[reportUnknownMemberType]  # Only the S3 service overload has installed stubs.
        "s3",
        endpoint_url=obj["endpoint"],
        region_name=obj["region"],
        aws_access_key_id=secret(obj["access_key_id"]),
        aws_secret_access_key=secret(obj["secret_access_key"]),
    )
    try:
        s3.head_bucket(Bucket=obj["bucket"])
    except ClientError as error:
        if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 404:
            raise
        if obj["region"] == "us-east-1":
            s3.create_bucket(Bucket=obj["bucket"])
        else:
            s3.create_bucket(
                Bucket=obj["bucket"],
                CreateBucketConfiguration={
                    "LocationConstraint": cast(
                        "BucketLocationConstraintType", obj["region"]
                    )
                },
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("databases", "resources"))
    phase = parser.parse_args().phase
    config = load()
    if phase == "databases":
        databases(config)
    else:
        asyncio.run(resources(config))
