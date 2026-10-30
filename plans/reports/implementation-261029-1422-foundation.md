# Foundation implementation

Phase 1 of the accepted backend plan is implemented. User/Workspace Go processes and Rust letfs run behind native Envoy configuration, with private PostgreSQL and persistent Temporal. Provisioning commits real bucket/filesystem/root records and rejects immutable-scope conflicts.

## Evidence

- `make verify` passed: Go unit tests/vet, Rust unit tests/clippy, format and configuration checks.
- The real Compose foundation suite passed JWT signature/issuer/audience/expiry cases, bootstrap restrictions, forged-header/direct-access rejection and configured burst rejection.
- PostgreSQL tests passed concurrent provisioning retries, input/conflict rejection, root/node-count checks and all 20 cross-database credential denials.
- Simultaneous PostgreSQL/Temporal/service restart preserved provisioning and the registered namespace; readiness recovered.
- The suite stopped its containers, preserving isolated test volumes and pre-migration dumps. No commit/publish occurred.

## Review

Applied the installed code-review checklist inline to foundation source, auth boundaries, transaction ordering, configuration and scripts. Repaired actual findings: Chi unknown-route handling bypassed the empty subrouter middleware; added router-level regression tests and mounted the guarded subrouter. Added normal container restart policy and a bounded Go startup attempt after a simultaneous dependency restart exposed startup exits. Native Envoy returns 403 for a disallowed audience; documented and tested that behavior explicitly.

The ak-cook conditional simplifier ran on configuration files. It moved native Envoy/Temporal structures into committed templates; tests and byte-for-byte comparisons preserved generated behavior. No custom gateway application was introduced.

## Boundaries

These checks do not prove live Clerk, S3 behavior or domain workflow recovery. Those remain required in their owning phases. Pre-migration dumps are not a coordinated application/object backup. The full six-phase plan remains in progress.
