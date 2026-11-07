package temporal

import "github.com/google/uuid"

const (
	AccountQueue             = "openlet-account"
	WorkspaceQueue           = "openlet-workspace"
	LetFSQueue               = "openlet-letfs"
	CreateWorkspaceWorkflow  = "CreateWorkspace"
	DeleteFilesystemWorkflow = "DeleteFilesystem"
	DeleteScopeWorkflow      = "DeleteScope"
	CreateFilesystemActivity = "CreateFilesystem"
	CreateScopesActivity     = "CreateScopes"
)

type WorkspaceCreation struct {
	ActorID uuid.UUID
	Key     uuid.UUID
	Name    string
}

type FilesystemCreation struct {
	ID         uuid.UUID
	Key        uuid.UUID
	LimitBytes int64
}

type ScopesCreation struct {
	FilesystemID   uuid.UUID
	Key            uuid.UUID
	IDs            []uuid.UUID
	AllowBlobFiles bool
	AllowIndexing  bool
}

type FilesystemDeletion struct {
	FilesystemID uuid.UUID
	After        uuid.UUID
}
type ScopeDeletion struct {
	FilesystemID uuid.UUID
	ScopeID      uuid.UUID
}
