package sdk

// WorkspaceCleanup is the shared Go/Python activity payload.
type WorkspaceCleanup struct {
	WorkspaceID string `json:"workspace_id"`
}

type InitialStoragesInput struct {
	WorkspaceID, UserID, SharedStorageID, SharedRootID, PrivateStorageID, PrivateRootID string
	Quota                                                                               int64
	ZedToken                                                                            string
}

type MemberStorageInput struct {
	WorkspaceID, UserID, StorageID, RootID, ZedToken string
	LetFSQueue                                       string
}
