# Generated from contracts/authz/schema.zed; DO NOT EDIT.
RESOURCE_ACTIONS = {
    "filesystem": frozenset(
        [
            "read",
            "delete",
        ]
    ),
    "leta": frozenset(
        [
            "read",
            "manage",
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
            "create_leta",
            "delete",
        ]
    ),
}
