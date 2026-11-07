// Code generated from contracts/authz/schema.zed; DO NOT EDIT.
package authz

type Action string

const (
	AccountRead            Action = "read"
	AccountUpdate          Action = "update"
	FilesystemRead         Action = "read"
	FilesystemDelete       Action = "delete"
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
	WorkspaceDelete        Action = "delete"
)

func (a Action) Valid(resource string) bool {
	switch resource {
	case "account":
		switch a {
		case AccountRead, AccountUpdate:
			return true
		}
	case "filesystem":
		switch a {
		case FilesystemRead, FilesystemDelete:
			return true
		}
	case "scope":
		switch a {
		case ScopeReadMetadata, ScopeReadContent, ScopeWrite, ScopeTrash, ScopeRestore, ScopePurge, ScopeManageAccess:
			return true
		}
	case "workspace":
		switch a {
		case WorkspaceRead, WorkspaceUpdate, WorkspaceManageMembers, WorkspaceDelete:
			return true
		}
	}
	return false
}
