# Actions and resource ownership

Generated from `schema.zed`. Roles are fixed resource relations; no global role policy.

| Resource | Actions |
|---|---|
| filesystem | `filesystem:read`, `filesystem:delete` |
| leta | `leta:read`, `leta:manage` |
| scope | `scope:read_metadata`, `scope:read_content`, `scope:write`, `scope:trash`, `scope:restore`, `scope:purge`, `scope:manage_access` |
| workspace | `workspace:read`, `workspace:update`, `workspace:manage_members`, `workspace:create_leta`, `workspace:delete` |
