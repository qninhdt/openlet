# External development configuration

Clerk development and Cloudflare R2 were configured under the user-authorized CLI identities. Both external smoke targets passed. No production Clerk instance, frontend, email sender or public bucket was configured.

## Configuration and verification

- A dedicated Clerk development application has custom session claims for backend-owned `openlet_user_id` and audience `openlet`. Before configuration changes, its original configuration was saved privately.
- A dedicated APAC R2 development bucket is private, with no custom public domains. Its S3 credential is scoped to object read/write in that bucket. The existing seven-day incomplete multipart abort rule was verified; no object expiry was introduced.
- Configuration and credential retrieval routes are in [operations](../../docs/operations.md). OAuth callback values, credentials and identity payloads are excluded from this report.
- `python3 scripts/configure-test.py` passed both configuration checks, including IPv4 JWKS resolution.
- `make test-provider` passed against the external R2 bucket using the normal Compose service image: put, copy, exact bytes, ranged read, anonymous denial, delete and not-found after deletion.
- A dedicated development test user and Backend API session exercised bootstrap access denial, real onboarding, new-token claims, `/v1/me`, preservation of unrelated Clerk metadata, and repeated onboarding returning the same internal user/workspace IDs.
- `make test-clerk` passed with the real refreshed development token through Envoy.

## Failures corrected

Envoy initially returned `Jwks remote fetch is failed`: its default DNS behavior selected IPv6 while the Compose network is IPv4. Selecting `V4_ONLY` for the JWKS cluster restored real onboarding. The template and configuration regression assertion now preserve that behavior.

Clerk rejected the smoke script's default Python User-Agent with HTTP 403. An explicit application User-Agent returned HTTP 200; the smoke script now sends it. TLS verification remains enabled.

An initial temporary smoke driver used `status` instead of the actual `state` DTO field; this was corrected before the successful check. No application DTO changed.

## Remaining acceptance

The existing full local suite was not repeated for these narrow gateway/smoke-script changes. Prior local acceptance remains recorded separately.

The R2-specific coordinated five-database/object recovery procedure has not been implemented or drilled. The local SeaweedFS restore proof does not cover R2, and no historical object recovery guarantee is claimed. Phase 6 remains open for that acceptance.

The development stack was stopped after verification, preserving databases, Temporal histories and configured external resources. Start it using the private environment route in operations. The dedicated development smoke user remains; its temporary session is revoked after checks.
