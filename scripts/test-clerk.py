#!/usr/bin/env python3
"""Read-only smoke for a real, already onboarded Clerk development session."""
import base64
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main():
    token_path = os.environ.get("CLERK_SMOKE_JWT_FILE")
    subject = os.environ.get("CLERK_SMOKE_SUBJECT", "")
    key_path = Path(".local/secrets/clerk_secret_key")
    if not token_path or not subject or not key_path.is_file():
        print("NOT RUN: configure a Clerk development instance, CLERK_SMOKE_SUBJECT and CLERK_SMOKE_JWT_FILE (refreshed after onboarding).", file=sys.stderr)
        return 2
    key = key_path.read_text().strip()
    if not key.startswith("sk_test_"):
        raise ValueError("only Clerk development credentials are allowed")
    token = Path(token_path).read_text().strip()
    claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    if claims.get("sub") != subject or not claims.get("openlet_user_id"):
        raise ValueError("a refreshed onboarded development token is required")
    request = Request("https://api.clerk.com/v1/users/" + subject, headers={"Authorization": "Bearer " + key, "User-Agent": "openlet-clerk-smoke/1.0"})
    with urlopen(request, timeout=15) as response:
        user = json.load(response)
    if user["public_metadata"].get("openlet_user_id") != claims["openlet_user_id"]:
        raise ValueError("Clerk metadata and refreshed claim differ")
    request = Request("http://127.0.0.1:8080/v1/me", headers={"Authorization": "Bearer " + token})
    with urlopen(request, timeout=15) as response:
        profile = json.load(response)
    if profile["id"] != claims["openlet_user_id"]:
        raise ValueError("Envoy/backend identity differs")
    print("Live Clerk development metadata, refreshed claim and gateway identity passed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, HTTPError):
        print("Clerk smoke failed; no credential or user payload logged.", file=sys.stderr)
        sys.exit(1)
