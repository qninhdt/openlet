-- +goose Up
ALTER TABLE boxes RENAME COLUMN representative_agent_id TO leader_agent_id;
ALTER TABLE box_edges RENAME TO box_links;
DELETE FROM box_links link USING boxes box
WHERE link.box_id=box.id AND box.leader_agent_id IN (link.agent_low_id,link.agent_high_id);
ALTER TABLE boxes ADD COLUMN workflow text NOT NULL DEFAULT '';
ALTER TABLE boxes ADD COLUMN handle text;
UPDATE boxes SET handle=name
WHERE state<>'archived';
UPDATE boxes SET handle=name || '-' || id::text
WHERE handle IS NULL;
ALTER TABLE boxes ALTER COLUMN handle SET NOT NULL;
ALTER TABLE boxes ADD CONSTRAINT boxes_handle UNIQUE (leta_id,handle);
DROP INDEX boxes_live_name;

ALTER TABLE agents ADD COLUMN handle text;
WITH labels AS (
    SELECT id, leta_id,
        coalesce(nullif(trim(both '-' from regexp_replace(lower(name), '[^a-z0-9]+', '-', 'g')), ''), 'agent')
        || '-the-' ||
        coalesce(nullif(trim(both '-' from regexp_replace(lower(title), '[^a-z0-9]+', '-', 'g')), ''), 'agent') AS handle
    FROM agents
), ranked AS (
    SELECT id, handle, row_number() OVER (PARTITION BY leta_id,handle ORDER BY id) AS n
    FROM labels
)
UPDATE agents SET handle=ranked.handle || CASE WHEN ranked.n=1 THEN '' ELSE '-' || agents.id::text END
FROM ranked WHERE ranked.id=agents.id;
ALTER TABLE agents ALTER COLUMN handle SET NOT NULL;
ALTER TABLE agents ADD CONSTRAINT agents_handle UNIQUE (leta_id,handle);

UPDATE agent_messages m SET source_kind='agent',source_id=b.leader_agent_id
FROM boxes b WHERE m.source_kind='box' AND m.source_id=b.id;
UPDATE agent_messages SET conversation_id=md5(
    least(source_id,recipient_agent_id)::text || greatest(source_id,recipient_agent_id)::text
)::uuid WHERE source_kind='agent';
ALTER TABLE agent_messages DROP CONSTRAINT agent_messages_source_kind_check;
ALTER TABLE agent_messages ADD CHECK (source_kind IN ('user','agent','hitl','schedule'));
ALTER TABLE agent_messages ADD COLUMN task_label text;
