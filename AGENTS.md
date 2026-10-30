# General engineering rules

Apply these defaults to the task at hand. Follow applicable repository and subtree instructions, established contracts, and configured tooling. Resolve conflicts explicitly; do not silently copy a local convention that introduces a known correctness or security defect.

## Understand before changing

- Establish the expected behavior, current behavior, acceptance criteria, and relevant constraints. Resolve consequential ambiguity before committing to a design; make routine, reversible choices from repository evidence.
- Read the affected implementation, its callers, and relevant tests. Trace data and control across boundaries until the assumptions behind the change are clear. Search for an existing implementation before adding another.
- Discover build, test, lint, formatting, and generation commands from manifests, task runners, documentation, and CI. Use the repository's package manager, lockfile, and supported runtime versions.
- Verify unfamiliar or version-sensitive APIs against installed types, source, or official documentation for the version in use. Do not invent APIs, flags, files, configuration, or dependency behavior.

## Keep the change coherent

- Implement the smallest complete solution to the requested problem. Update affected callers, contracts, tests, and documentation together; a small diff is not sufficient if it leaves inconsistent behavior.
- Keep unrelated cleanup, renaming, formatting, dependency upgrades, and speculative features out of the change. Refactor adjacent code when it materially helps the fix, keeping the reason and behavioral impact clear.
- Fix the cause at the layer that owns the invariant. Do not accumulate special cases in callers to compensate for a broken shared contract. Check for other manifestations of the same cause within the affected scope.
- Preserve user changes and unrelated work. Inspect the working tree before editing, and review the final diff for unintended edits, deletions, generated output, and temporary artifacts.

## Design for the next maintainer

- Prefer the simplest design that satisfies current requirements. Reuse suitable project components and standard library facilities. Add an abstraction when it expresses a real concept, removes meaningful duplication, or isolates a concrete boundary—not for hypothetical future flexibility.
- Keep responsibilities cohesive and dependencies explicit. Separate domain decisions from transport, persistence, presentation, and external effects where the distinction improves clarity or testing. Follow the existing architecture unless the task requires changing it.
- Give each fact and business rule a clear owner. Avoid duplicated state and synchronization logic. Do not merge superficially similar code when it represents independently changing concepts.
- Define contracts deliberately: inputs, outputs, invalid states, errors, ordering, mutation, and ownership. Use types or explicit variants to express meaningful distinctions and prevent invalid combinations when the language supports them.
- Preserve observable behavior during refactoring, including error semantics and side effects. Treat public API, schema, persisted data, and protocol changes as compatibility work: update consumers and provide the necessary migration or deprecation path.

## Write clear, finished code

- Match the surrounding naming, idioms, layout, and formatter. Choose names that explain domain meaning and units. Prefer straightforward control flow over clever compression; split code when it separates concerns or makes a difficult operation understandable.
- Keep types precise. Narrow and validate uncertain values at boundaries. Do not use broad casts, unchecked assertions, or lint/type suppressions to conceal a mismatch; any necessary escape hatch must be narrow and explained.
- Validate untrusted input and configuration at the boundary that owns the contract. Inside that boundary, rely on established invariants rather than repeating defensive checks everywhere. Distinguish missing, empty, zero, false, and invalid values when behavior depends on them.
- Ship working behavior. Remove introduced dead code, unused dependencies, debug output, commented-out implementations, placeholder branches, and speculative extension points. Do not hide incomplete work behind a successful result or a silent no-op.
- Use comments for intent, constraints, invariants, non-obvious tradeoffs, and compatibility reasons. Keep useful explanations current; omit narration of obvious code and promotional claims about its quality.
- For UI changes, check semantic structure, accessible names, keyboard and focus behavior, and relevant loading, empty, and error states using the existing design system.

## Handle failure and resource lifetimes

- Make failures explicit and actionable. Catch errors where recovery, translation, or useful context is possible; preserve the cause when appropriate. Do not silently convert unexpected failures into empty data or success.
- Preserve or add the operational signals needed to diagnose meaningful failures, following existing observability patterns. Keep logs useful and metric labels bounded; avoid duplicate noise and unbounded identifiers.
- Use fallbacks only when they are part of the intended contract. Define which failures permit the fallback and test both paths. A fallback must not bypass validation, authorization, or data integrity.
- Give files, connections, locks, subscriptions, timers, and background tasks a clear owner and cleanup path, including partial initialization, exceptions, cancellation, and shutdown. Prefer the language's structured resource and concurrency mechanisms.
- For concurrent or remote work, define ordering, shared-state access, cancellation, deadlines, and bounds. Retry only suitable failures, with a bounded policy and safe repeat semantics. A timeout may leave an external operation's outcome unknown; reconcile it rather than blindly repeating a non-idempotent effect.
- Keep related state changes atomic when correctness requires it. Use transactions, concurrency controls, or idempotency mechanisms appropriate to the system; do not leave partially applied work that callers can mistake for completion.

## Protect trust boundaries

- Enforce authentication and authorization at the actual operation and resource boundary, including ownership or tenant scope. Client validation, hidden UI, an unguessable identifier, and a comment are not access controls.
- Use established libraries for cryptography and security-sensitive protocols. Use parameterized queries and context-appropriate escaping. Treat external text as data, and prevent it from becoming executable code, commands, queries, or unsafe paths.
- Keep secrets and unnecessary personal data out of source, fixtures, logs, telemetry, errors, and serialized objects. Expose only the fields required by the contract; preserve useful diagnostics without leaking sensitive internals.
- Add dependencies only for a concrete need that existing facilities do not meet reasonably. Evaluate maintenance, compatibility, security, license, and runtime or bundle cost; update the canonical manifest and lockfile using project tooling. Do not edit vendored or generated files as a substitute for changing their source.

## Debug with evidence

- Reproduce the failure or obtain a discriminating observation before choosing a fix. Read the full error and relevant history; separate facts from hypotheses. Reduce the case and test one explanatory hypothesis at a time.
- Compare with a working path and inspect the actual dependency behavior. When fixes fail repeatedly or reveal new failures, revisit the model and architecture instead of layering more patches.
- Confirm that the original failure is resolved and intended neighboring behavior remains valid. If reproduction or verification is unavailable, state the gap and limit the claim accordingly.

## Test behavior that matters

- Add or update tests for changed behavior and meaningful regression risks. For a bug fix, create a focused reproduction and verify that it fails for the original defect before the fix and passes afterward when feasible. Use test-first development when it helps specify the behavior; do not impose a ritual on prose or purely mechanical edits.
- Choose the least expensive test level that can detect the failure reliably. Use unit tests for isolated logic, integration or contract tests for real boundaries, and end-to-end tests for critical user journeys. Follow project requirements and cover a boundary where mocks could otherwise hide incompatibility.
- Make each test prove a meaningful contract with independently derived expectations. Identify a plausible incorrect implementation it would reject. Do not merely restate the implementation, compare a result with itself, or test only that a mock was configured.
- Cover relevant success, invalid-input, boundary, and failure cases. Include cancellation, partial failure, repeated operations, or concurrent access when the changed behavior depends on them. Prefer a readable case table to a complicated test algorithm.
- Keep the subject under test real. Use fakes or mocks at appropriate external, slow, or nondeterministic boundaries, with realistic contracts. Assert interactions when the interaction itself is required behavior, rather than coupling tests to incidental internal calls.
- Make tests independent and reproducible: isolate state and data, control time and randomness where practical, and clean up resources. For async behavior, wait for observable conditions with a deadline rather than arbitrary sleeps. Await asynchronous assertions and ensure error tests fail if the expected error never occurs.
- Treat snapshots as reviewed expected output, not automatic approval. Use property tests, differential tests, fuzzing, sanitizers, or mutation testing when they address a concrete risk. Keep minimized failures as regressions; coverage numbers alone do not establish correctness.
- Do not weaken assertions, disable checks, or update expectations merely to make the change pass. Change a test when its contract is demonstrably wrong or intentionally changed. Investigate flaky tests rather than hiding them with retries.

## Optimize the relevant cost

- Choose algorithms and data access appropriate to expected scale. Avoid clearly unnecessary work, unbounded allocation or queues, repeated I/O, and N+1 queries; use measured workload evidence for more involved optimization.
- Establish a relevant baseline, identify the bottleneck, and compare before and after under equivalent conditions. Preserve correctness and report the tradeoff in latency, throughput, memory, I/O, or bundle size. Do not add caching, pooling, parallelism, or complexity without a justified benefit.
- Bound concurrency and resource use. Parallelize independent operations only when ordering, failure behavior, and downstream capacity permit it. If caching is warranted, define invalidation, lifetime, key scope, and memory limits.

## Verify and hand off honestly

- Run focused checks while iterating, then the project-required checks and an appropriate wider set for the affected contracts. Check formatting, lint, types, build, and runtime behavior as applicable; passing one does not imply the others passed. Avoid repeating unchanged checks without a reason.
- Review the final diff against the requirements. Look for regressions, incomplete paths, unnecessary complexity, security issues, and accidental scope expansion. Separate concrete defects from style preferences; do not manufacture findings to fill a review.
- Update documentation, examples, configuration guidance, and migration notes when the change affects their accuracy. Document consequential decisions and tradeoffs where the project normally records them; do not create ceremonial documents for routine edits.
- Report what changed, why, and the verification actually performed. Name material failures, skipped checks, environmental limits, and remaining risks. Never claim a test, benchmark, security guarantee, deployment, or fix was verified without corresponding evidence.
