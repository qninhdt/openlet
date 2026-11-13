# Local demo: Cloud CLI and infrastructure readiness

The user selected the current machine for the demo. No VPS, SSH deployment,
public domain or public TLS is required for this local acceptance run.

## Installed and checked

| Tool | Version | Result |
|---|---|---|
| Grafana `gcx` | 1.7.1 | Official release installed to `~/.local/bin`; installer verified SHA-256. Stack authentication remains pending. |
| Langfuse `langfuse` | 1.3.1 | Official npm package `@langfuse/cli` installed globally; version/help pass. Project keys remain pending. |
| Clerk `clerk` | 4.0.0 | Existing login can list the Openlet development application and pull its keys. |
| Cloudflare `cf` | 1.0.0-beta.16 | Existing login can list R2 buckets and inspect bucket CORS/lifecycle. |
| Docker | 29.8.1 | Available with 12 CPUs; port 8080 is free. |

The current host has approximately 5.2 GiB available RAM and 151 GiB free disk.
Previous shared-stack E2E ran on this host; this is not a concurrency benchmark.

## Authentication and configuration

- Existing local configuration records Clerk issuer/JWKS/audience and R2
  endpoint/region/bucket metadata. No secrets were copied into tracked files.
- Clerk development keys were fetched with explicit application/instance
  selection, without linking the repository, into a private ignored file with
  mode `0600`. The backend API and public JWKS were reachable.
- A private ignored `0600` template is ready for Langfuse's regional URL and
  project keys. Its CLI has no browser login step.
- Grafana browser sign-in uses `gcx login openlet --cloud --oauth`. Before
  sign-in, the native API command reports no configured stack. Runtime Alloy
  still needs a Cloud access-policy token for metrics/logs/traces writes.
- Runtime S3 credentials and the OpenRouter key are absent under the expected
  variable names. Cloudflare CLI OAuth does not replace S3 authentication.
- The runtime YAML still needs to be assembled from the existing example and
  real Cloud service metadata after credentials are available.

## Existing R2 configuration

The configured `openlet-dev` bucket exists. Its current CORS rule allows
GET/PUT/HEAD from `http://127.0.0.1:8765` and exposes `ETag` plus range/download
headers. Change the allowed origin if the browser app uses a different origin.
Lifecycle aborts incomplete multipart uploads after seven days; an existing
`exports/` expiry rule also remains. No bucket, policy or object was changed.

## Remaining setup

1. Sign in to Grafana and choose the Cloud stack; obtain ingestion endpoints,
   instance IDs and a runtime write token.
2. Provide Langfuse project keys and its regional URL privately. Verify CLI
   access before importing approved prompts.
3. Supply an OpenRouter key and bucket-scoped R2 S3 credentials privately.
4. Internal PostgreSQL/Redis/SpiceDB/Qdrant credentials can be generated locally.
   Compose/bootstrap owns PostgreSQL, Temporal, SpiceDB, Qdrant, Redis and Alloy;
   no individual manual provisioning is required.
5. Prompt content still needs approval before publication. Dashboard/alert API
   imports, Cloud export checks and backed-up local startup follow once external
   credentials are available. No deployment or migration ran here.

See [operator CLI setup](../../docs/setup.md#cloud-operator-clis),
[Cloud operations](../../docs/observability.md) and
[implementation acceptance](../261111-2010-leta-rewrite/execution.md).

## Follow-up: one local credential file

The user requested one root dotenv file and a committed example. Credentials
from the temporary Clerk/Langfuse files were merged into the existing root file;
existing values were preserved, mode `0600` applied and both temporary files
removed. Unavailable credentials remain empty.

[The credential example](../../.env.example) covers all 17 secret references in
the shared YAML plus the Clerk publishable key and Langfuse CLI regional URL.
An assert-based check verified coverage, empty example values, preserved local
values and private file permissions. Runtime endpoints/settings remain in YAML.

## Follow-up: Cloud authentication

Grafana stack login now succeeds: the current `openlet` context can call the
native health API. The runtime ingestion token remains a separate credential.
Langfuse project URL/keys and R2 S3 credentials are still empty in the root
credential file; no provider credentials were invented or substituted.

Account token listing and permission-group discovery returned HTTP 403
(`9109`, unauthorized). The earlier conclusion that dashboard intervention
was required was premature: user token creation uses a different route.
Langfuse's project Settings / API Keys page still supplies its initial project
key pair. Store these values directly in the private root credentials.

## Follow-up: R2 credentials provisioned through CLI

User permission-group discovery succeeded. Although user token listing also
returned HTTP 403, `cf user tokens create` (`POST /user/tokens`) succeeded with
the existing OAuth login. Created `openlet-local-letfs`, scoped only to
`openlet-dev`, with `Workers R2 Storage Bucket Item Write` (read/write/list
objects; no bucket administration).

Following [Cloudflare's documented derivation](https://developers.cloudflare.com/r2/api/tokens/#get-s3-api-credentials-from-an-api-token),
the token ID and SHA-256 hex digest of its value were saved as the S3 credential
pair in the private root credential file. No secret was printed or committed;
file mode `0600` was verified. An independently signed S3 ListObjectsV2 request
with `max-keys=1` returned HTTP 200. No new bucket was needed and no object was
created, changed or deleted. Write operations, presigned browser uploads and
full LetFS integration with these credentials have not been exercised.

## Follow-up: Grafana runtime token authorization

The current CLI login can read the `openlet` Free stack and discover its region,
metrics/logs/traces endpoints and instance IDs. Stack health returns success;
the Cloud organization and stack-list commands also succeed. The OAuth scopes
include metrics/logs/traces writes, profile and stack read/write.

This does not establish access-policy management: the documented Cloud
`GET /api/v1/accesspolicies` returns HTTP 401 (`InvalidCredentials`, token could
not be parsed). The installed Access Policies plugin's frontend identifies
`/api/plugin-proxy/grafana-auth-app/auth/v1/accesspolicies` as its native route;
calling that route through `gcx api` returns HTTP 403 (`plugin proxy route
access denied`). The current user has the Grafana Admin role and the
`grafana-auth-app:write` permission, so do not attribute this result simply to
a missing Admin role. No access policy or runtime token was created.

No browser is exposed to the automation tool in this session. The remaining
bootstrap credential is a stack-scoped Cloud access-policy token with
`metrics:write`, `logs:write` and `traces:write`, saved privately as
`GRAFANA_CLOUD_TOKEN`. It can be created through Grafana Administration → Cloud
access policies. A management-capable Cloud API credential is another route;
do not reuse a short-lived CLI OAuth token as Alloy's persistent credential.
Runtime ingestion and dashboard rendering remain unverified.
