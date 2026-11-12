"""Initialize fresh databases or native service resources from OPENLET_CONFIG."""

import argparse
import asyncio
from datetime import timedelta

import boto3
import grpc
import psycopg
from authzed.api.v1 import SchemaServiceStub, WriteSchemaRequest
from botocore.exceptions import ClientError
from configure import ROOT, load, secret
from google.protobuf.duration_pb2 import Duration
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


def databases(c):
    pg = c["dependencies"]["postgres"]
    admin = c["deployment"]["postgres"]
    targets = [c["services"][name]["database"] for name in ("platform", "letfs")]
    targets += [c["deployment"][name]["database"] for name in ("temporal", "spicedb")]
    temporal = c["deployment"]["temporal"]
    targets += [{**temporal["database"], "name": temporal["visibility_database"]}]
    with psycopg.connect(host=pg["host"], port=pg["port"], dbname="postgres",
            user=admin["admin_user"], password=secret(admin["admin_password"]),
            sslmode=pg["sslmode"], autocommit=True) as db:
        for target in targets:
            if not db.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (target["user"],)).fetchone():
                db.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(target["user"]), sql.Literal(secret(target["password"]))))
            if not db.execute("SELECT 1 FROM pg_database WHERE datname=%s", (target["name"],)).fetchone():
                db.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(target["name"]), sql.Identifier(target["user"])))


async def resources(c):
    dep = c["dependencies"]
    graph = dep["spicedb"]
    channel = grpc.aio.secure_channel(graph["address"], grpc.ssl_channel_credentials()) if graph["tls"] else grpc.aio.insecure_channel(graph["address"])
    async with channel:
        await SchemaServiceStub(channel).WriteSchema(
            WriteSchemaRequest(schema=(ROOT / "packages/contracts/authz/schema.zed").read_text()),
            metadata=[("authorization", "Bearer " + secret(graph["key"]))], timeout=30)
    t = dep["temporal"]
    client = await Client.connect(t["address"], namespace=t["namespace"], tls=t["tls"])
    try:
        await client.workflow_service.register_namespace(RegisterNamespaceRequest(
            namespace=t["namespace"], workflow_execution_retention_period=Duration(
                seconds=c["deployment"]["temporal"]["namespace_retention_hours"] * 3600)))
    except RPCError as error:
        if error.status != RPCStatusCode.ALREADY_EXISTS:
            raise
    for owner in ("platform", "letfs"):
        interval = timedelta(seconds=c["services"][owner]["maintenance"]["interval_seconds"])
        schedule = Schedule(
            action=ScheduleActionStartWorkflow("Maintenance", id=f"{owner}-maintenance",
                task_queue=t["queues"][owner]),
            spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=interval)]),
            policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP))
        identity = f"{owner}-maintenance"
        try:
            await client.create_schedule(identity, schedule)
        except ScheduleAlreadyRunningError:
            await client.get_schedule_handle(identity).update(lambda _: ScheduleUpdate(schedule=schedule))
    vector = dep["qdrant"]
    host, port = vector["address"].rsplit(":", 1)
    q = QdrantClient(host=host, grpc_port=int(port), prefer_grpc=True,
        api_key=secret(vector["api_key"]), https=vector["tls"])
    try:
        if not q.collection_exists(vector["collection"]):
            q.create_collection(vector["collection"], vectors_config=models.VectorParams(
                size=c["models"]["embedding"]["dimensions"], distance=models.Distance.COSINE))
            q.create_payload_index(vector["collection"], "workspace_id", models.PayloadSchemaType.KEYWORD)
        q.create_payload_index(vector["collection"], "text", models.TextIndexParams(
            type=models.TextIndexType.TEXT, tokenizer=models.TokenizerType.WORD, scoring=True), wait=True)
    finally:
        q.close()
    obj = dep["s3"]
    s3 = boto3.client("s3", endpoint_url=obj["endpoint"], region_name=obj["region"],
        aws_access_key_id=secret(obj["access_key_id"]), aws_secret_access_key=secret(obj["secret_access_key"]))
    try:
        s3.head_bucket(Bucket=obj["bucket"])
    except ClientError as error:
        if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
            raise
        args = {} if obj["region"] == "us-east-1" else {"CreateBucketConfiguration": {"LocationConstraint": obj["region"]}}
        s3.create_bucket(Bucket=obj["bucket"], **args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("databases", "resources"))
    phase = parser.parse_args().phase
    config = load()
    if phase == "databases":
        databases(config)
    else:
        asyncio.run(resources(config))
