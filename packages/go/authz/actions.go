// Code generated from contracts/authz/schema.zed; DO NOT EDIT.
package authz

type Action string

const (
	FilesystemRead         Action = "read"
	FilesystemDelete       Action = "delete"
	LetaRead               Action = "read"
	LetaManage             Action = "manage"
	ScopeReadMetadata      Action = "read_metadata"
	ScopeReadContent       Action = "read_content"
	ScopeWrite             Action = "write"
	ScopeTrash             Action = "trash"
	ScopeRestore           Action = "restore"
	ScopePurge             Action = "purge"
	ScopeManageAccess      Action = "manage_access"
	WorkspaceRead          Action = "read"
	WorkspaceUpdate        Action = "update"
	WorkspaceManageMembers Action = "manage_members"
	WorkspaceCreateLeta    Action = "create_leta"
	WorkspaceDelete        Action = "delete"
)

func (a Action) Valid(resource string) bool {
	switch resource {
	case "filesystem":
		switch a {
		case FilesystemRead, FilesystemDelete:
			return true
		}
	case "leta":
		switch a {
		case LetaRead, LetaManage:
			return true
		}
	case "scope":
		switch a {
		case ScopeReadMetadata, ScopeReadContent, ScopeWrite, ScopeTrash, ScopeRestore, ScopePurge, ScopeManageAccess:
			return true
		}
	case "workspace":
		switch a {
		case WorkspaceRead, WorkspaceUpdate, WorkspaceManageMembers, WorkspaceCreateLeta, WorkspaceDelete:
			return true
		}
	}
	return false
}
