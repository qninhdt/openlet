ALTER TABLE operations
    ADD COLUMN durable boolean NOT NULL DEFAULT false,
    ADD COLUMN input jsonb,
    ADD COLUMN source_id uuid,
    ADD COLUMN destination_parent_id uuid,
    ADD COLUMN destination_name text,
    ADD COLUMN staging_root_id uuid,
    ADD COLUMN total_nodes bigint NOT NULL DEFAULT 0 CHECK(total_nodes>=0),
    ADD COLUMN total_bytes bigint NOT NULL DEFAULT 0 CHECK(total_bytes>=0),
    ADD COLUMN max_copy_bytes bigint CHECK(max_copy_bytes>=0),
    ADD COLUMN max_copy_nodes bigint CHECK(max_copy_nodes>0),
    ADD COLUMN deadline timestamptz;
ALTER TABLE nodes ADD CONSTRAINT node_staging_operation FOREIGN KEY(staging_operation_id) REFERENCES operations(id);
CREATE INDEX nodes_staging ON nodes(staging_operation_id,id) WHERE staging_operation_id IS NOT NULL;
CREATE TABLE copy_items (
    operation_id uuid NOT NULL REFERENCES operations(id),
    source_id uuid NOT NULL,
    source_parent_id uuid,
    source_name text NOT NULL,
    source_revision bigint NOT NULL,
    size_bytes bigint NOT NULL,
    kind text NOT NULL CHECK(kind IN ('file','directory')),
    destination_id uuid NOT NULL,
    destination_parent_id uuid,
    depth integer NOT NULL CHECK(depth BETWEEN 0 AND 128),
    source_key text,
    target_key text UNIQUE,
    state text NOT NULL CHECK(state IN ('unopened','enumerating','pending','ready')),
    upper_child_id uuid,
    last_child_id uuid NOT NULL DEFAULT '00000000-0000-0000-0000-000000000000',
    PRIMARY KEY(operation_id,source_id),
    UNIQUE(operation_id,destination_id)
);
CREATE INDEX copy_work ON copy_items(operation_id,state,source_id);
