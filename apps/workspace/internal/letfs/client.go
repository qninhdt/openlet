package letfs

import "github.com/google/uuid"

const Queue = "openlet-letfs"
const ProvisionBucket = "ProvisionWorkspaceBucket"
const ProvisionFilesystem = "ProvisionWorkspaceFilesystem"
const ReleaseProvisioning = "ReleaseWorkspaceProvisioning"
const FreezeBucket = "FreezeWorkspaceBucket"
const ListFilesystems = "ListWorkspaceFilesystems"
const CompleteBucket = "CompleteWorkspaceBucketDeletion"

type BucketInput struct {
	WorkspaceID uuid.UUID `json:"workspace_id"`
	LimitBytes  string    `json:"limit_bytes"`
}
type Bucket struct {
	ID         uuid.UUID `json:"id"`
	LimitBytes string    `json:"limit_bytes"`
	UsedBytes  string    `json:"used_bytes"`
	State      string    `json:"state"`
}
type FilesystemInput struct {
	WorkspaceID uuid.UUID `json:"workspace_id"`
	BucketID    uuid.UUID `json:"bucket_id"`
}
type Filesystem struct {
	ID       uuid.UUID `json:"id"`
	BucketID uuid.UUID `json:"bucket_id"`
	RootID   uuid.UUID `json:"root_id"`
	State    string    `json:"state"`
}
type BucketScope struct {
	WorkspaceID uuid.UUID `json:"workspace_id"`
	BucketID    uuid.UUID `json:"bucket_id"`
}
type FilesystemPage struct {
	BucketScope
	After uuid.UUID `json:"after"`
}
type Provisioned struct {
	BucketScope
	FilesystemID uuid.UUID `json:"filesystem_id"`
	RootID       uuid.UUID `json:"root_id"`
}
