# Generated from contracts/authz/schema.zed; DO NOT EDIT.
RESOURCE_ACTIONS = {
    "account": frozenset(
        [
            "read",
            "update",
        ]
    ),
    "filesystem": frozenset(
        [
            "read",
            "delete",
        ]
    ),
    "scope": frozenset(
        [
            "read_metadata",
            "read_content",
            "write",
            "trash",
            "restore",
            "purge",
            "manage_access",
        ]
    ),
    "workspace": frozenset(
        [
            "read",
            "update",
            "manage_members",
            "delete",
        ]
    ),
}
