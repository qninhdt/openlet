import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

spec = importlib.util.spec_from_file_location(
    "sql_query_benchmark", Path(__file__).with_name("sql-query-benchmark.py")
)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class QuerySummaryTests(unittest.TestCase):
    def test_summary_retains_missing_empty_and_dynamic_variants(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            sites = [
                {"file": "store.go", "line": line, "function": "query"}
                for line in (10, 20, 30)
            ]
            (output / "inventory.json").write_text(json.dumps(sites))
            samples = [
                {
                    "site": sites[0],
                    "sql": "SELECT a",
                    "kind": "explain_analyze",
                    "median_ms": 0,
                    "work_rows": 0,
                },
                {
                    "site": sites[0],
                    "sql": "SELECT b",
                    "kind": "explain_analyze",
                    "median_ms": 2,
                    "work_rows": 3,
                },
                {
                    "site": sites[1],
                    "sql": "UPDATE a",
                    "kind": "probe_error",
                    "error": "23505",
                },
                {
                    "site": sites[2],
                    "sql": "SAVEPOINT a",
                    "kind": "control_client_elapsed",
                    "median_ms": 0.1,
                    "work_rows": 0,
                },
            ]
            (output / "queries-1.jsonl").write_text("\n".join(map(json.dumps, samples)))
            summary = benchmark.summarize(output)
            self.assertEqual((summary["measured"], summary["total"]), (2, 3))
            self.assertEqual(len(summary["errors"]), 1)
            self.assertEqual(len(summary["sites"][0]["variants"]), 2)
            self.assertEqual(
                summary["sites"][0]["variants"][0]["samples"][0]["work_rows"], 0
            )
            report = output / "report.md"
            benchmark.write_report(output, report)
            self.assertIn("MISSING", report.read_text())
            self.assertIn("0.000–2.000", report.read_text())

    def test_summary_rejects_samples_outside_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "inventory.json").write_text("[]")
            (output / "queries-1.jsonl").write_text(
                json.dumps({"site": {"file": "other.go", "line": 1}})
            )
            with self.assertRaisesRegex(AssertionError, "absent from inventory"):
                benchmark.summarize(output)

    @mock.patch.object(benchmark.subprocess, "run")
    def test_prepare_rejects_changed_inventory_with_existing_samples(self, run):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            (output / "inventory.json").write_text('[{"file":"old.go"}]')
            (output / "queries-1.jsonl").write_text("{}")
            run.return_value.stdout = '[{"file":"new.go"}]'

            with self.assertRaisesRegex(AssertionError, "different SQL inventory"):
                benchmark.prepare(root, output)


if __name__ == "__main__":
    unittest.main()
