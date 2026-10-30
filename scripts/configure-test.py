#!/usr/bin/env python3
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import configure


class ConfigurationTest(unittest.TestCase):
    def test_test_identity_ignores_development_environment(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(configure, "ROOT", Path(tmp)),
            patch("sys.argv", ["configure.py", "--test"]),
            patch.dict(
                os.environ,
                {
                    "JWT_ISSUER": "https://development.example",
                    "JWKS_URL": "https://development.example/jwks",
                    "JWT_AUDIENCE": "development",
                },
                clear=True,
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            configure.main()
            config = json.loads((Path(tmp) / ".local/test/envoy.json").read_text())
            manager = config["static_resources"]["listeners"][0]["filter_chains"][0]["filters"][0]["typed_config"]
            jwt_filter = next(
                f["typed_config"] for f in manager["http_filters"]
                if f["name"] == "envoy.filters.http.jwt_authn"
            )
            provider = jwt_filter["providers"]["clerk"]
            self.assertEqual(provider["issuer"], "http://issuer:8080")
            self.assertEqual(provider["audiences"], ["openlet-test"])
            self.assertEqual(
                provider["remote_jwks"]["http_uri"]["uri"],
                "http://issuer:8080/.well-known/jwks.json",
            )

    def test_test_credentials_are_stable_and_private(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(configure, "ROOT", Path(tmp)),
            patch("sys.argv", ["configure.py", "--test"]),
            patch.dict(os.environ, {}, clear=True),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            configure.main()
            folder = Path(tmp) / ".local/test"
            secret = (folder / "secrets/gateway_token").read_text()
            self.assertGreaterEqual(len(secret), 32)
            self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
            configure.main()
            self.assertEqual((folder / "secrets/gateway_token").read_text(), secret)
            config = json.loads((folder / "envoy.json").read_text())
            self.assertNotIn("admin", config)
            jwks = next(c for c in config["static_resources"]["clusters"] if c["name"] == "jwks")
            self.assertEqual(jwks["dns_lookup_family"], "V4_ONLY")

    def test_external_plaintext_issuer_rejected(self):
        values = {
            "JWT_ISSUER": "http://external.example",
            "JWKS_URL": "http://external.example/jwks",
            "JWT_AUDIENCE": "openlet",
        }
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(configure, "ROOT", Path(tmp)),
            patch("sys.argv", ["configure.py"]),
            patch.dict(os.environ, values, clear=True),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(SystemExit):
                configure.main()


if __name__ == "__main__":
    unittest.main()
