"""Measure service SQL from a source tree using a disposable, owned PostgreSQL container."""

import argparse
import hashlib
import json
import os
import pathlib
import re
import runpy
import signal
import statistics
import subprocess
import time
from functools import partial

name = f"openlet-api-sql-bench-{os.getpid()}"
image = "postgres:18.6-trixie@sha256:74935e72241653ca55e0414067e6d8763aceb8a810eb51b452253ec3dcfc4336"
scope = "11111111-1111-4111-8111-111111111111"
fs = "22222222-2222-4222-8222-222222222222"


def run(args, data=None):
    completed = subprocess.run(
        args, input=data, text=True, capture_output=True, timeout=120, check=False
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr)
    return completed.stdout


def sql(query, db="bench"):
    return run(
        [
            "docker",
            "exec",
            "-i",
            name,
            "psql",
            "-XAt",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "bench",
            "-d",
            db,
        ],
        query,
    )


def uid(i):
    h = hashlib.md5(f"node-{i}".encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def raw(source, file, needle):
    matches = [
        x
        for x in re.findall("`([^`]*)`", (source / file).read_text(), re.DOTALL)
        if needle in x
    ]
    assert len(matches) == 1, (file, needle, len(matches))
    return matches[0]


def bind(query, args):
    return re.sub(r"\$(\d+)", lambda match: args[int(match.group(1)) - 1], query)


def lit(x):
    if x is None:
        return "NULL"
    return "'" + str(x).replace("'", "''") + "'"


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark actual service SQL in disposable PostgreSQL; never connects to application databases."
    )
    parser.add_argument("source", type=pathlib.Path, help="source tree to measure")
    parser.add_argument(
        "output", type=pathlib.Path, help="JSON timings and EXPLAIN plans"
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Include maintenance, backfill and cross-scope cleanup workloads",
    )
    options = parser.parse_args()
    root = options.source.resolve()
    output = options.output.resolve()
    read = partial(raw, root)
    base = "apps/letfs/internal/filesystem/"
    cols = read(
        base + "nodes.go",
        "n.id,n.scope_id,n.parent_id,n.name,n.kind,n.revision,n.size_bytes,n.created_at,n.updated_at,",
    )
    # Extract the actual resolver, including its concatenated column projection.
    src = (root / (base + "paths.go")).read_text()
    resolver = (
        src.split("s.tx.Query(ctx, `")[1]
        .split("`, s.scopeID")[0]
        .replace("`+nodeColumns+`", cols)
    )
    searchlive = read(base + "search.go", "WITH RECURSIVE live AS")
    filters = read(base + "search.go", "AND ($4::text IS NULL")
    namequery = read(base + "search.go", "AS sort_value FROM live") % (
        searchlive,
        cols.replace("f.context", "NULL::text"),
        "n.name",
        filters,
        "n.name",
        ">",
        "n.name",
        "ASC",
        "ASC",
    )
    semantic = read(
        base + "semantic_search.go", "req AS (SELECT * FROM jsonb_to_recordset($10)"
    )
    if semantic.startswith("%s"):
        semantic = semantic % (
            searchlive,
            cols.replace("f.context", "NULL::text"),
            filters,
        )
    else:
        semantic = semantic % (cols.replace("f.context", "NULL::text"), filters)

    def terminate(*_):
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, terminate)
    results = []
    run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "--cpus",
            "2",
            "--memory",
            "768m",
            "--label",
            "openlet.task=api-sql-benchmark",
            "-e",
            "POSTGRES_USER=bench",
            "-e",
            "POSTGRES_DB=bench",
            "-e",
            "POSTGRES_PASSWORD=isolated-benchmark",
            image,
        ]
    )
    try:
        for _ in range(200):
            if (
                subprocess.run(
                    [
                        "docker",
                        "exec",
                        name,
                        "pg_isready",
                        "-h",
                        "127.0.0.1",
                        "-U",
                        "bench",
                    ],
                    capture_output=True,
                    timeout=5,
                    check=False,
                ).returncode
                == 0
            ):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("postgres not ready")
        for svc in ["letfs", "account", "workspace"]:
            sql("CREATE DATABASE " + svc)
            sql((root / f"apps/{svc}/migrations/0001_initial.sql").read_text(), svc)

        def bench(
            label,
            query,
            db="letfs",
            modes=("force_custom_plan",),
            types=None,
            args=None,
        ):
            for mode in modes:
                if types:
                    statement = (
                        f"PREPARE q({types}) AS {query}; EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) EXECUTE q("
                        + ",".join(args)
                        + ");"
                    )
                else:
                    statement = "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + query + ";"
                plans = []
                for _ in range(4):
                    out = sql(
                        "SET statement_timeout='30s'; SET plan_cache_mode="
                        + mode
                        + "; BEGIN; "
                        + statement
                        + " ROLLBACK;",
                        db,
                    )
                    plans.append(
                        json.loads(out[out.index("[") : out.rindex("]") + 1])[0]
                    )
                runs = [plan["Execution Time"] for plan in plans[1:]]
                result = {
                    "case": label,
                    "mode": mode,
                    "runs_ms": runs,
                    "median_ms": statistics.median(runs),
                    "plan": plans[-1],
                    "sql": query,
                    "args": args,
                }
                results.append(result)
                output.write_text(
                    json.dumps({"source": str(root), "results": results}, indent=2)
                )
                print(
                    json.dumps(
                        {
                            k: v
                            for k, v in result.items()
                            if k not in ("plan", "sql", "args")
                        }
                    ),
                    flush=True,
                )

        sql(
            f"BEGIN; INSERT INTO filesystems(id,limit_bytes,node_count) VALUES('{fs}',100000000,100000); INSERT INTO scopes(id,filesystem_id,root_id) VALUES('{scope}','{fs}','{uid(1)}'); INSERT INTO nodes(id,scope_id,parent_id,name,kind) SELECT md5('node-'||i)::uuid,'{scope}',CASE WHEN i=1 THEN NULL ELSE md5('node-'||((i-2)/10+1))::uuid END,'n'||i,CASE WHEN i<=10000 THEN 'directory' ELSE 'file' END FROM generate_series(1,100000) i; INSERT INTO files(node_id,storage_kind,inline_bytes,desired_generation,processing_format,publication_status) SELECT id,'inline','content'::bytea,1,'text','ready' FROM nodes WHERE kind='file'; COMMIT; ANALYZE;",
            "letfs",
        )
        # Ten thousand siblings plus many unrelated IDs for child paging/copy probes.
        sql(
            f"INSERT INTO nodes(id,scope_id,parent_id,name,kind) SELECT md5('node-'||i)::uuid,'{scope}','{uid(1)}','n'||i,'directory' FROM generate_series(100001,110000) i; ANALYZE nodes;",
            "letfs",
        )
        sql(
            f"INSERT INTO uploads(id,scope_id,actor_id,input,transport,expected_size,processing_file_id,processing_generation,relative_path,processing_stage,expires_at) SELECT md5('upload-'||i)::uuid,'{scope}',NULL,'{{}}','inline',1,md5('node-'||(10001+i%90000))::uuid,1,'output','parse',now()+CASE WHEN i%1000=0 THEN interval '-1 hour' ELSE interval '1 hour' END FROM generate_series(1,100000) i; INSERT INTO idempotency_keys(scope,operation,request_key,request_hash,result) SELECT 'actor/'||i,CASE WHEN i%2=0 THEN 'process-file' ELSE 'create-upload' END,i::text,'hash',CASE WHEN i%2=0 THEN jsonb_build_object('file_id',md5('node-'||(10001+i%90000))::uuid,'generation',1) ELSE jsonb_build_object('id',md5('upload-'||i)::uuid) END FROM generate_series(1,100000) i; ANALYZE;",
            "letfs",
        )
        names = []
        target = 100000
        while target > 1:
            names.insert(0, "n" + str(target))
            target = (target - 2) // 10 + 1
        for label, requests in [
            ("path", [{"idx": 0, "start_id": uid(1), "parts": names}]),
            ("id", [{"idx": 0, "start_id": uid(100000), "parts": []}]),
            (
                "batch-100",
                [
                    {"idx": i, "start_id": uid(99901 + i), "parts": []}
                    for i in range(100)
                ],
            ),
        ]:
            bench(
                "resolve-" + label,
                resolver,
                modes=("force_custom_plan", "force_generic_plan"),
                types="uuid,uuid,jsonb",
                args=[lit(scope), lit(uid(1)), lit(json.dumps(requests))],
            )
        listquery = (
            "SELECT "
            + cols.replace("f.context", "NULL::text")
            + ",false"
            + read(
                base + "nodes.go",
                "FROM nodes n LEFT JOIN files f ON f.node_id=n.id WHERE n.scope_id=$1 AND n.parent_id=$2 AND n.id>$3",
            )
        )
        for parent in [1, 5000]:
            for after in [
                "00000000-0000-0000-0000-000000000000",
                "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
            ]:
                bench(
                    "list-" + str(parent) + "-" + after[:4],
                    listquery,
                    types="uuid,uuid,uuid,int",
                    args=[lit(scope), lit(uid(parent)), lit(after), "51"],
                )
        bench(
            "copy-next-child",
            read(
                base + "copy_data.go",
                "SELECT id FROM nodes WHERE scope_id=$1 AND parent_id=$2 AND id>$3",
            ),
            types="uuid,uuid,uuid,uuid",
            args=[
                lit(scope),
                lit(uid(5000)),
                lit("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"),
                lit("ffffffff-ffff-ffff-ffff-ffffffffffff"),
            ],
        )
        bench(
            "move-subtree-height",
            "WITH RECURSIVE a AS (SELECT id,0 AS depth FROM nodes WHERE id="
            + lit(uid(2))
            + " AND scope_id="
            + lit(scope)
            + " UNION ALL SELECT n.id,a.depth+1 FROM a JOIN nodes n ON n.parent_id=a.id AND n.scope_id="
            + lit(scope)
            + " WHERE a.depth<128) SELECT max(depth)::bigint FROM a",
        )
        for label, q in [
            (
                "uploads-for-generation",
                "SELECT candidate_key FROM uploads WHERE processing_file_id=$1 AND processing_generation=$2 AND result_node_id IS NULL",
            ),
            (
                "complete-processing-receipt",
                read(
                    base + "artifacts.go",
                    "UPDATE idempotency_keys SET expires_at=now()",
                ),
            ),
            (
                "complete-upload-receipt",
                read(
                    base + "upload_publication.go",
                    "UPDATE idempotency_keys SET expires_at=now()",
                ),
            ),
            (
                "expire-uploads",
                read(
                    base + "maintenance.go",
                    "SELECT id,scope_id FROM uploads WHERE state",
                ),
            ),
        ]:
            args = (
                [lit(uid(50001)), lit("1")]
                if label != "complete-upload-receipt"
                else ["md5('upload-50001')::uuid::text"]
            )
            bench(label, bind(q, args))
        for label, q in [
            (
                "unscoped-child-probe",
                "SELECT EXISTS(SELECT 1 FROM nodes WHERE parent_id=$1)",
            ),
            (
                "scoped-child-probe",
                "SELECT EXISTS(SELECT 1 FROM nodes WHERE scope_id=$2 AND parent_id=$1)",
            ),
        ]:
            bench(label, bind(q, [lit(uid(50000)), lit(scope)]))
        args = [
            lit(scope),
            lit(uid(1)),
            lit("/"),
            *["NULL"] * 6,
            lit("n100000"),
            "NULL",
            lit(""),
            "21",
        ]
        bench("name-search-selective", bind(namequery, args))
        args[9] = lit("")
        bench("name-search-all", bind(namequery, args))
        for count in [0, 1, 80]:
            req = [
                {
                    "idx": i,
                    "source_id": uid(99901 + i),
                    "file_id": uid(99901 + i),
                    "generation": 1,
                }
                for i in range(count)
            ]
            bench(
                "hydrate-" + str(count),
                bind(
                    semantic,
                    [
                        lit(scope),
                        lit(uid(1)),
                        lit("/"),
                        *["NULL"] * 6,
                        lit(json.dumps(req)),
                    ],
                ),
            )
        bench(
            "delete-scope-leaves",
            bind(
                read(
                    base + "deletion.go",
                    "SELECT n.id FROM nodes n WHERE n.scope_id=$1\n AND NOT EXISTS",
                ),
                [lit(scope)],
            ),
        )
        # Indexed read/list controls in the other services: 100k accounts/members, 10k workspaces.
        sql(
            "INSERT INTO accounts(id,type,clerk_id) SELECT md5('node-'||i)::uuid,'user','clerk-'||i FROM generate_series(1,100000) i; ANALYZE;",
            "account",
        )
        bench(
            "account-profile",
            bind(
                read(
                    "apps/account/internal/account/store.go",
                    "SELECT id,type,owner_id,display_name,avatar_url FROM accounts WHERE id=$1",
                ),
                [lit(uid(50000))],
            ),
            "account",
        )
        bench(
            "account-summaries",
            bind(
                read(
                    "apps/account/internal/account/store.go",
                    "SELECT id,type,owner_id,display_name,avatar_url FROM accounts WHERE id=ANY",
                ),
                [
                    "ARRAY["
                    + ",".join(lit(uid(50000 + i)) for i in range(100))
                    + "]::uuid[]"
                ],
            ),
            "account",
        )
        sql(
            "INSERT INTO workspaces(id,name,filesystem_id,shared_scope_id) SELECT md5('ws-'||i)::uuid,'workspace',md5('fs-'||i)::uuid,md5('shared-'||i)::uuid FROM generate_series(1,10000) i; INSERT INTO workspace_members(workspace_id,account_id,role,personal_scope_id) SELECT md5('ws-'||((i-1)/10+1))::uuid,md5('member-'||((i-1)%10))::uuid,'member',md5('personal-'||i)::uuid FROM generate_series(1,100000) i; ANALYZE;",
            "workspace",
        )
        wc = read(
            "apps/workspace/internal/workspace/store.go",
            "w.id,w.name,w.filesystem_id,w.shared_scope_id,w.status,m.role,m.personal_scope_id",
        )
        src = (root / "apps/workspace/internal/workspace/store.go").read_text()
        query = (
            src.split("func (s *Store) List(")[1]
            .split("s.DB.Query(ctx, `")[1]
            .split("`, actor")[0]
            .replace("`+workspaceColumns+`", wc)
        )
        bench(
            "workspace-list",
            bind(
                query,
                [
                    "md5('member-0')::uuid",
                    lit("00000000-0000-0000-0000-000000000000"),
                    "51",
                ],
            ),
            "workspace",
        )
        bench(
            "workspace-members",
            bind(
                read(
                    "apps/workspace/internal/workspace/store.go",
                    "SELECT account_id,role,personal_scope_id,status FROM workspace_members WHERE workspace_id=$1 AND account_id>$2",
                ),
                [
                    "md5('ws-1')::uuid",
                    lit("00000000-0000-0000-0000-000000000000"),
                    "51",
                ],
            ),
            "workspace",
        )
        bench(
            "insert-1000-nodes",
            f"INSERT INTO nodes(id,scope_id,parent_id,name,kind) SELECT md5('write-node-'||i)::uuid,'{scope}','{uid(1)}','write-'||i,'directory' FROM generate_series(1,1000) i",
        )
        bench(
            "insert-1000-uploads",
            f"INSERT INTO uploads(id,scope_id,actor_id,input,transport,expected_size,processing_file_id,processing_generation,relative_path,processing_stage) SELECT md5('write-upload-'||i)::uuid,'{scope}',NULL,'{{}}','inline',1,'{uid(50001)}',1,'write-'||i,'parse' FROM generate_series(1,1000) i",
        )
        bench(
            "insert-1000-receipts",
            "INSERT INTO idempotency_keys(scope,operation,request_key,request_hash,result) SELECT 'write/'||i,'process-file',i::text,'hash',jsonb_build_object('file_id',md5('node-'||i)::uuid,'generation',1) FROM generate_series(1,1000) i",
        )
        if options.audit:
            runpy.run_path(str(pathlib.Path(__file__).with_name("sql-audit-cases.py")))[
                "audit"
            ](read, bench, sql, scope, fs, uid, lit, bind, cols)
        sizes = json.loads(
            sql(
                "SELECT jsonb_object_agg(indexrelname,pg_relation_size(indexrelid)) FROM pg_stat_user_indexes",
                "letfs",
            )
        )
        output.write_text(
            json.dumps(
                {
                    "source": str(root),
                    "postgres": sql("SELECT version()"),
                    "limits": {"cpus": 2, "memory_mib": 768},
                    "index_bytes": sizes,
                    "results": results,
                },
                indent=2,
            )
        )
    finally:
        run(["docker", "stop", "--time", "5", name])


if __name__ == "__main__":
    main()
