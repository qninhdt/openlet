-- +goose Up
DROP INDEX nodes_sibling;
-- Enrichment may exchange sibling names; defer uniqueness until all names and links are committed together.
ALTER TABLE nodes ADD CONSTRAINT nodes_sibling UNIQUE (storage_id,parent_id,name) DEFERRABLE INITIALLY IMMEDIATE;

-- +goose Down
ALTER TABLE nodes DROP CONSTRAINT nodes_sibling;
CREATE UNIQUE INDEX nodes_sibling ON nodes (storage_id,parent_id,name) WHERE parent_id IS NOT NULL;
