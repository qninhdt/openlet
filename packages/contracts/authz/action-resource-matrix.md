# Actions and resource ownership

Generated from `schema.zed`. Roles are fixed resource relations; no global role policy.

| Resource | Actions |
|---|---|
| account | `account:read`, `account:update` |
| filesystem | `filesystem:read`, `filesystem:delete` |
| scope | `scope:read_metadata`, `scope:read_content`, `scope:write`, `scope:trash`, `scope:restore`, `scope:purge`, `scope:manage_access` |
| workspace | `workspace:read`, `workspace:update`, `workspace:manage_members`, `workspace:delete` |
