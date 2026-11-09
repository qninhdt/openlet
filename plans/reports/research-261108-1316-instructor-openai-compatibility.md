# Instructor and OpenAI compatibility

Verified against PyPI metadata and uv 0.13.7 on 2026-11-08.

## Result

Instructor 1.17.0 can run with OpenAI SDK 3.3.0, jiter 0.14.0 and Pydantic 2.14.3 on Python 3.14.10. OpenAI 3.3.0 is the newest stable version selected by an unrestricted `openai<4` resolution with Instructor 1.17.0.

OpenAI 3.3.0 requires `jiter>=0.10.0,<1`. The next stable release, 3.3.1, and the latest release checked, 3.46.0, require `jiter>=0.16.0,<1`. Instructor 1.17.0 requires `jiter>=0.6.1,<0.15`, so those newer OpenAI releases cannot coexist without changing an upstream constraint. The resolver also retains Rich 14.3.4 because Instructor requires Rich <15.

## Verification

- A fresh Python 3.14.10 environment installed the compatible versions. The local test explicitly included Openlet's HTTPX 0.28.1.
- An async `instructor.from_openai(AsyncOpenAI(...), mode=instructor.Mode.JSON_SCHEMA)` request passed through HTTPX MockTransport. The test asserted `response_format.type == json_schema`, verified the transmitted field schema and received a validated Pydantic result. No application-side schema insertion was used.
- The combined current direct requirements of all three Python workspace packages, with Instructor restored and OpenAI changed to 3.3.0, resolved successfully. CPU Torch 2.15.0 and TorchVision 0.29.1 remained selected. This establishes dependency resolution, not full runtime acceptance.
- No paid provider request or full parser/service regression suite was run for this investigation.

## Sources

- [Instructor 1.17.0 metadata](https://pypi.org/pypi/instructor/1.17.0/json)
- [OpenAI 3.3.0 metadata](https://pypi.org/pypi/openai/3.3.0/json)
- [OpenAI 3.3.1 metadata](https://pypi.org/pypi/openai/3.3.1/json)
- [OpenAI 3.46.0 metadata](https://pypi.org/pypi/openai/3.46.0/json)
- [Instructor 1.17.0 native JSON Schema mode](https://github.com/567-labs/instructor/blob/v1.17.0/docs/modes-comparison.md)

## Worktree checkpoint

The earlier upgrade attempt removed Instructor and added manual JSON-schema prompting/validation to `clients/openrouter.py`. That interim change is not the recommended resolution. The current user request authorized checking compatibility; no application source or manifest was changed during this investigation. Keeping Instructor requires restoring its wrapper, pinning OpenAI 3.3.0 and regenerating the lockfile. Switching the existing JSON mode to native JSON Schema also requires updating its HTTP contract test and confirming support from the configured provider/model.

The broader repository dependency upgrade is unfinished. Direct and transitive Go upgrades have been applied, including the OpenAPI generator's upstream module rename to `connectrpc.com/protoc-gen-connect-openapi`. Infra and Node version inventories exist in temporary artifacts, but their configuration changes and verification remain pending. There are no surviving background processes from this compatibility test.

## Subsequent implementation

The user approved the compatible pair. Instructor 1.17.0 and OpenAI 3.3.0 are now locked, native JSON Schema mode replaces the interim manual implementation, and the corresponding semantic tests and real API E2E suite passed. The earlier worktree checkpoint above describes the investigation boundary, not the current upgrade state. See the [implementation report](implementation-261108-dependency-upgrade.md) for the complete upgrade and verification results.
