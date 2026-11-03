# letfs service refactor

Status: DONE

## Result

- Removed the `internal/app` implementation and made `filesystem.Service` the single mutation/orchestration boundary used by HTTP and gRPC.
- Kept Temporal SDK types out of `filesystem`; narrow processing, copy, and deletion scheduler interfaces are owned by the domain package.
- Moved `CopyState`, its initializer, and deletion workflow input into `filesystem` without changing their JSON history shape.
- Removed duplicate gRPC copy, purge, processing-dispatch, upload-publication, and filesystem-deletion orchestration.
- Wired `cmd/server` to one shared service and the shared Temporal error/tracing helpers.
- Replaced the removed provisioning workflow coverage with authenticated RPC storage creation/deletion lifecycle coverage, including replay and durable workflow completion.
- Updated the embedded Python integration to use native `openlet.clients.letfs` DTOs and `RpcClient`, with no handwritten protobuf use.
- Verified delegated service actors remain non-gateway principals and still pass through filesystem SpiceDB authorization.

## Verification

- `go test ./...`
- `go test -tags workflow ./...`
- `go test -tags integration -run '^$' ./...`
- `go test -tags integration ./internal/transport/grpc -run '^(TestIntegrationStorageLifecycleOverAuthenticatedRPC|TestIntegrationCopyAndPurgeJobsOverAuthenticatedRPC)$' -count=1`
- `go test -tags integration ./internal/transport/grpc -run '^TestIntegrationPythonNativeClientPublishesParseViaGoRPC$' -count=1`
- `go test -tags integration ./internal/transport/grpc -run '^TestIntegrationFilesystemOperationsOverAuthenticatedRPC$' -count=1`
- `git diff --check -- apps/letfs`
