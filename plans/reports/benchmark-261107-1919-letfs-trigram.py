"""Measure proposed text GIN indexes in an owned, disposable PostgreSQL only."""

import argparse
import csv
import io
import json
import os
from pathlib import Path
import random
import re
import signal
import statistics
import subprocess
import tempfile
import time


def run(args, *, data=None, stdin=None, timeout=180):
    result = subprocess.run(
        args, input=data, stdin=stdin, text=True, capture_output=True, timeout=timeout
    )
    if result.returncode:
        raise RuntimeError(f"{args[0:3]} failed: {result.stderr[-3000:]}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    source = (root / "scripts/performance/sql-benchmark.py").read_text()
    image = re.search(r'^image = "([^"]+)"', source, re.M).group(1)
    name = f"openlet-leta-trigram-bench-{os.getpid()}"
    scratch = Path(tempfile.mkdtemp(prefix="leta-trigram-preimages-"))
    base = ["docker", "exec", "-i", name, "psql", "-h", "127.0.0.1", "-XqAt", "-v", "ON_ERROR_STOP=1", "-U", "bench", "-d", "bench"]

    def sql(query):
        return run(base, data=query)

    def backup(filename):
        target = scratch / filename
        with target.open("w") as output:
            subprocess.run(
                ["docker", "exec", name, "pg_dump", "-U", "bench", "-d", "bench"],
                stdout=output, stderr=subprocess.PIPE, text=True, check=True, timeout=180
            )
        return str(target)

    def measure(query, repeats=5, settings=""):
        plans = []
        for _ in range(repeats + 1):
            raw = sql("SET jit=off; SET max_parallel_workers_per_gather=0; " + settings + " EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + query)
            plans.append(json.loads(raw)[0])
        return {"median_ms": statistics.median(p["Execution Time"] for p in plans[1:]), "plans": plans[1:]}

    def terminate(*_):
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, terminate)
    report = {"image": image, "container": name, "corpora": [], "notes": [
        "Synthetic data only; no Openlet database, account data or blob content was read.",
        "2 CPU, 1536 MiB limit, 128 MiB shared_buffers, tmpfs PGDATA; warm single-client queries.",
        "Sizes are disk relation sizes, not resident RAM. No scope joins or concurrent writes.",
        "One warmup followed by five EXPLAIN ANALYZE samples; planner chooses its own plan.",
        "diagnostic_index_forced disables sequential scans only to investigate default-plan behavior; not production tuning."
    ]}
    started = False
    try:
        print(f"Starting owned benchmark container {name}", flush=True)
        run(["docker", "run", "-d", "--rm", "--name", name, "--network", "none",
             "--cpus", "2", "--memory", "1536m", "--tmpfs", "/var/lib/postgresql:rw,size=1073741824",
             "--label", "openlet.task=leta-trigram-benchmark", "-e", "POSTGRES_USER=bench",
             "-e", "POSTGRES_DB=bench", "-e", "POSTGRES_HOST_AUTH_METHOD=trust", image,
             "-c", "shared_buffers=128MB", "-c", "maintenance_work_mem=128MB",
             "-c", "max_parallel_maintenance_workers=0"], timeout=240)
        started = True
        for _ in range(200):
            probe = subprocess.run(["docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "bench"], capture_output=True, timeout=5)
            if probe.returncode == 0:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("benchmark PostgreSQL did not become ready")

        report["version"] = sql("SELECT version();").strip()
        report["empty_backup"] = backup("empty-before-schema.sql")
        sql("CREATE EXTENSION pg_trgm;")
        report["pg_trgm_version"] = sql("SELECT extversion FROM pg_extension WHERE extname='pg_trgm';").strip()
        rng = random.Random(20261107)
        vocabulary = (
            "account action activity agent approval argument async backend batch box cache calendar callback "
            "cancel checkpoint client command config connection content context contract create database "
            "deadline default delete directory document download edge editor engine error event example "
            "execute expiry file filter folder graph group history identity image index inline input "
            "integration interval item json label langgraph limit list log member message metadata model "
            "mount node notification operation option output owner page parent path payload permission "
            "policy postgres preview prompt query queue read receipt record redis reference reply request "
            "response result retry role root runtime schedule scope search select semantic sender server "
            "session shared signal source state status storage stream system target task temporal text "
            "thread time timeout timezone token tool transaction tree type update upload user validate "
            "value version view visibility worker workflow workspace write báo cáo dữ liệu thời gian "
            "người dùng thông tin quyền truy cập thư mục tìm kiếm tài liệu đồng thời xử lý"
        ).split()
        predicates = {
            "rare_literal": "content ILIKE '%needleopenlet%'",
            "common_literal": "content ILIKE '%request%'",
            "short_literal": "content ILIKE '%xy%'",
            "anchored_regex": "content ~ 'needleopenlet-[0-9]{6}'"
        }
        for label, row_bytes, count, kind in [
            ("docs_8k", 8192, 4096, "docs"),
            ("docs_64k", 65536, 512, "docs"),
            ("logs_8k", 8192, 4096, "logs")
        ]:
            print(f"Loading {label}: {count} files of {row_bytes} UTF-8 bytes", flush=True)
            sql(f"CREATE TABLE {label}(id integer PRIMARY KEY, content text NOT NULL);")
            corpus = scratch / f"{label}.csv"
            with corpus.open("w", newline="") as output:
                writer = csv.writer(output)
                for i in range(count):
                    prefix = f"# File {i:06d}\nrequest workspace text\n"
                    if i % 128 == 0:
                        prefix += f"needleopenlet-{i:06d}\n"
                    if kind == "docs":
                        body = " ".join(rng.choices(vocabulary, k=row_bytes // 3))
                    else:
                        rows = [json.dumps({"request": rng.randbytes(16).hex(), "token": rng.randbytes(32).hex(), "status": 200}) for _ in range(row_bytes // 60)]
                        body = "\n".join(rows)
                    raw = (prefix + body).encode()[:row_bytes]
                    text = raw.decode("utf-8", errors="ignore")
                    text += " " * (row_bytes - len(text.encode()))
                    assert len(text.encode()) == row_bytes
                    writer.writerow((i, text))
            with corpus.open() as data:
                run(base + ["-c", f"COPY {label} FROM STDIN WITH (FORMAT csv)"], stdin=data)
            sql(f"VACUUM ANALYZE {label};")
            size = json.loads(sql(f"SELECT json_build_object('rows',count(*),'logical_bytes',sum(octet_length(content)),'stored_column_bytes',sum(pg_column_size(content)),'table_bytes',pg_table_size('{label}')) FROM {label};"))
            assert size["rows"] == count
            assert size["logical_bytes"] == count * row_bytes
            queries = {}
            for key, predicate in predicates.items():
                query = f"SELECT count(*) FROM {label} WHERE {predicate};"
                expected = int(sql(query).strip())
                if key in ("rare_literal", "anchored_regex"):
                    assert expected == count // 128
                queries[key] = {"sql": query, "matches": expected, "before": measure(query)}
            report["corpora"].append({"name": label, "size": size, "queries": queries})

        report["corpus_backup"] = backup("corpus-before-indexes.sql")
        for corpus in report["corpora"]:
            name_table = corpus["name"]
            index = name_table + "_content_trgm"
            print(f"Building GIN index for {name_table}", flush=True)
            began = time.monotonic()
            sql(f"CREATE INDEX {index} ON {name_table} USING gin(content gin_trgm_ops);")
            corpus["build_wall_seconds"] = time.monotonic() - began
            sql(f"ANALYZE {name_table};")
            corpus["gin_bytes"] = int(sql(f"SELECT pg_relation_size('{index}');").strip())
            corpus["planner_stats"] = json.loads(sql(f"SELECT json_build_object('heap_pages',c.relpages,'estimated_rows',c.reltuples,'avg_content_width',s.avg_width) FROM pg_class c LEFT JOIN pg_stats s ON s.tablename=c.relname AND s.attname='content' WHERE c.oid='{name_table}'::regclass;"))
            for key, query in corpus["queries"].items():
                assert int(sql(query["sql"]).strip()) == query["matches"]
                query["after"] = measure(query["sql"])
                if key in ("rare_literal", "anchored_regex"):
                    query["diagnostic_index_forced"] = measure(query["sql"], settings="SET enable_seqscan=off;")
                    plan_text = json.dumps(query["diagnostic_index_forced"]["plans"][0])
                    assert index in plan_text
            print(json.dumps({"corpus": name_table, "size": corpus["size"], "gin_bytes": corpus["gin_bytes"], "times_ms": {k: [q["before"]["median_ms"],q["after"]["median_ms"]] for k,q in corpus["queries"].items()}}), flush=True)
        report["checks"] = "UTF-8 sizes, row counts, predetermined rare matches and all before/after result counts passed."
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(f"Saved {args.output}", flush=True)
    finally:
        if started:
            run(["docker", "stop", "--time", "10", name], timeout=30)
            print(f"Stopped and removed owned container {name}", flush=True)


if __name__ == "__main__":
    main()
