ALTER TABLE filesystems ALTER COLUMN root_id DROP NOT NULL;
ALTER TABLE filesystems ADD CONSTRAINT filesystem_live_root CHECK(state!='active' OR root_id IS NOT NULL);
ALTER TABLE operations ADD COLUMN deletion_cursor uuid NOT NULL DEFAULT '00000000-0000-0000-0000-000000000000';
CREATE TABLE deletion_items (
    operation_id uuid NOT NULL REFERENCES operations(id),
    node_id uuid NOT NULL,
    depth integer NOT NULL CHECK(depth BETWEEN 0 AND 128),
    child_cursor uuid NOT NULL DEFAULT '00000000-0000-0000-0000-000000000000',
    PRIMARY KEY(operation_id,node_id)
);
CREATE INDEX deletion_depth ON deletion_items(operation_id,depth DESC,node_id);
CREATE INDEX object_deletions_due ON object_deletions(eligible_at,object_key);
UPDATE nodes n SET staging_operation_id=NULL FROM operations o WHERE n.staging_operation_id=o.id AND o.state='succeeded';
