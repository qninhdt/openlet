"""Measure application SQL in owned integration fixtures through a test-only Go overlay."""

import argparse
import json
import os
import subprocess
from pathlib import Path


def summarize(output):
    inventory = json.loads((output / "inventory.json").read_text())
    sites = {(site["file"], site["line"]): dict(site, samples=[]) for site in inventory}
    assert len(sites) == len(inventory), "duplicate inventory site"
    errors = []
    for file in sorted(output.glob("queries-*.jsonl")):
        for line in file.read_text().splitlines():
            sample = json.loads(line)
            key = sample["site"]["file"], sample["site"]["line"]
            assert key in sites, f"sample absent from inventory: {key}"
            if sample.get("error"):
                errors.append(sample)
            else:
                sites[key]["samples"].append(sample)
    for site in sites.values():
        variants = {}
        for sample in site.pop("samples"):
            variants.setdefault(sample["sql"], []).append(sample)
        site["variants"] = []
        for query, samples in variants.items():
            # Retain all observed workloads; no-data measurements remain explicit.
            site["variants"].append({"sql": query, "samples": samples})
    missing = [site for site in sites.values() if not site["variants"]]
    return {
        "total": len(sites),
        "measured": len(sites) - len(missing),
        "sites": list(sites.values()),
        "errors": errors,
    }


def write_report(output, report):
    summary = summarize(output)
    (output / "summary.json").write_text(json.dumps(summary, indent=2))
    lines = [
        "# Per-query SQL measurements",
        "",
        (
            f"Measured **{summary['measured']}/{summary['total']}** source execution sites. "
            f"Failed probes: {len(summary['errors'])} (excluded from successful timings)."
        ),
        "",
        (
            "Each EXPLAIN sample is one warm-up followed by three rolled-back runs; "
            "the table shows the range of their medians across observed SQL variants and workloads. "
            "These are PostgreSQL execution times, excluding planning, network, pool waits and API work. "
            "Control statements use actual client elapsed time and are labelled separately. "
            "Rows means root output or mutation input rows from the plan; it is not a universal affected-row count. "
            "An aggregate/EXISTS can return one row without matching underlying data."
        ),
        "",
        (
            "Integration tests supply real application SQL and bound parameters on isolated fixtures. "
            "Supplemental cases use verbatim inventoried SQL on explicitly seeded fixtures. "
            "Most integration fixtures are small; these timings alone do not prove large-data or concurrent performance. "
            "All observed workloads, SQL, parameter metadata and plans are in "
            f"`{output}/summary.json` and `queries-*.jsonl`. Bound parameter values are not "
            "persisted as separate fields, though PostgreSQL plans can embed fixture constants."
        ),
        "",
        "| Source | Function | SQL variants | Median ms range | Rows range | Measurement |",
        "|---|---|---:|---:|---:|---|",
    ]
    for site in summary["sites"]:
        samples = [
            sample for variant in site["variants"] for sample in variant["samples"]
        ]
        source = f"{site['file']}:{site['line']}"
        target = os.path.relpath(
            Path(__file__).resolve().parents[2] / site["file"], report.parent
        )
        if samples:
            medians = [sample["median_ms"] for sample in samples]
            rows = [sample["work_rows"] for sample in samples]
            kinds = ", ".join(sorted({sample["kind"] for sample in samples}))
            timing = f"{min(medians):.3f}–{max(medians):.3f}"
            row_range = f"{min(rows):g}–{max(rows):g}"
        else:
            timing, row_range, kinds = "—", "—", "MISSING"
        lines.append(
            f"| [{source}]({target}#L{site['line']}) | {site['function']} | {len(site['variants'])} | {timing} | {row_range} | {kinds} |"
        )
    report.write_text("\n".join(lines) + "\n")
    print(
        f"Measured {summary['measured']}/{summary['total']} sites; failed probes {len(summary['errors'])}"
    )
    return summary


def prepare(root, output):
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PATH="/usr/local/go/bin:" + os.environ["PATH"])
    inventory = subprocess.run(
        ["go", "run", "scripts/performance/sql_inventory.go"],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    inventory_path = output / "inventory.json"
    if inventory_path.exists() and any(output.glob("queries-*.jsonl")):
        assert json.loads(inventory_path.read_text()) == json.loads(inventory), (
            "output contains samples for a different SQL inventory"
        )
    inventory_path.write_text(inventory)
    replacements = {}
    for file in (
        "packages/go/testfixture/postgres.go",
        "apps/letfs/internal/testfixture/postgres.go",
    ):
        text = (root / file).read_text()
        if file.startswith("apps/"):
            text = text.replace(
                '"context"',
                '"context"\n sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"',
                1,
            )
            factory = "sharedfixture.NewSQLBenchmark"
        else:
            factory = "NewSQLBenchmark"
        needle = "db, err := pgxpool.NewWithConfig(ctx, config)"
        assert text.count(needle) == 1
        text = text.replace(
            needle,
            f"config.ConnConfig.Tracer = {factory}(t, {json.dumps(str(root))}, {json.dumps(str(output))})\n\t"
            + needle,
        )
        target = output / (file.replace("/", "-") + ".go")
        target.write_text(text)
        replacements[str(root / file)] = str(target)
    for source, virtual in (
        ("sql_trace.go", "sql_benchmark_overlay.go"),
        ("sql_trace_test.go", "sql_benchmark_overlay_test.go"),
    ):
        replacements[str(root / "packages/go/testfixture" / virtual)] = str(
            root / "scripts/performance" / source
        )
    constants = output / "sql-benchmark-path.go"
    constants.write_text(
        "package testfixture\nconst sqlBenchmarkRoot = " + json.dumps(str(root)) + "\n"
    )
    replacements[
        str(root / "packages/go/testfixture/sql_benchmark_path_overlay.go")
    ] = str(constants)
    overlay = output / "overlay.json"
    overlay.write_text(json.dumps({"Replace": replacements}, indent=2))
    return overlay, env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "service",
        choices=(
            "summary",
            "selfcheck",
            "additional",
            "account",
            "workspace",
            "letfs",
            "all",
        ),
        default="all",
        nargs="?",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if args.service == "summary":
        assert args.report, "summary requires --report"
        write_report(output, args.report.resolve())
        return
    overlay, env = prepare(root, output)
    services = (
        ("account", "workspace", "letfs") if args.service == "all" else (args.service,)
    )
    for service in services:
        command = [
            "go",
            "test",
            "-overlay",
            str(overlay),
            "-tags",
            "integration",
            "-p",
            "1",
            "-count=1",
            "-timeout",
            "30m",
        ]
        workdir = root / "apps" / service
        if service in ("selfcheck", "additional"):
            command += [
                "-run",
                "^TestSQLBenchmark"
                + (
                    "ProbePreservesFixture"
                    if service == "selfcheck"
                    else "AdditionalQueries"
                )
                + "$",
                "./testfixture",
            ]
            workdir = root / "packages/go"
        else:
            command += ["./..."]
        print("Measuring", service, flush=True)
        with (output / f"{service}.log").open("w") as log:
            completed = subprocess.run(
                command,
                cwd=workdir,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        print(service, "exit", completed.returncode, flush=True)
        if completed.returncode:
            raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
