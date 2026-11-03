package authz

// Action identifies a supported graph permission; callers cannot provide arbitrary names.
type Action string

const (
	AccountRead       Action = "account_read"
	AccountUpdate     Action = "account_update"
	WorkspaceRead     Action = "workspace_read"
	WorkspaceUpdate   Action = "workspace_update"
	WorkspaceDelete   Action = "workspace_delete"
	WorkspaceTransfer Action = "workspace_transfer"
	MemberRead        Action = "member_read"
	MemberManage      Action = "member_manage"
	MemberLeave       Action = "member_leave"
	InvitationRead    Action = "invitation_read"
	InvitationCreate  Action = "invitation_create"
	InvitationRevoke  Action = "invitation_revoke"
	NodeList          Action = "node_list"
	NodeRead          Action = "node_read"
	NodeResolve       Action = "node_resolve"
	NodeCreate        Action = "node_create"
	NodeUpdate        Action = "node_update"
	NodeTrash         Action = "node_trash"
	ContentRead       Action = "content_read"
	ContentWrite      Action = "content_write"
	TrashRead         Action = "trash_read"
	TrashRestore      Action = "trash_restore"
	TrashPurge        Action = "trash_purge"
	UploadCreate      Action = "upload_create"
	UploadRead        Action = "upload_read"
	UploadSign        Action = "upload_sign"
	UploadComplete    Action = "upload_complete"
	UploadAbort       Action = "upload_abort"
	CopyCreate        Action = "copy_create"
	CopyRead          Action = "copy_read"
	CopyInspectAny    Action = "copy_inspect_any"
	ProcessingRead    Action = "processing_read"
	ProcessingRun     Action = "processing_run"
	Search            Action = "search"
	Archive           Action = "archive"
	BucketRead        Action = "bucket_read"
	BucketAdmin       Action = "bucket_admin"
)

func (a Action) Valid(resource string) bool {
	switch resource {
	case "account":
		switch a {
		case AccountRead, AccountUpdate:
			return true
		}
	case "workspace":
		switch a {
		case WorkspaceRead, WorkspaceUpdate, WorkspaceDelete, WorkspaceTransfer, MemberRead, MemberManage, MemberLeave, InvitationRead, InvitationCreate, InvitationRevoke:
			return true
		}
	case "filesystem":
		switch a {
		case NodeList, NodeRead, NodeResolve, NodeCreate, NodeUpdate, NodeTrash, ContentRead, ContentWrite, TrashRead, TrashRestore, TrashPurge, UploadCreate, UploadRead, UploadSign, UploadComplete, UploadAbort, CopyCreate, CopyRead, CopyInspectAny, ProcessingRead, ProcessingRun, Search, Archive:
			return true
		}
	case "quota_bucket":
		switch a {
		case BucketRead, BucketAdmin:
			return true
		}
	}
	return false
}
