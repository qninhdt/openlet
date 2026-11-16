-- +goose Up
ALTER TABLE agents ADD COLUMN title text NOT NULL DEFAULT '';
ALTER TABLE agents ADD COLUMN appearance jsonb NOT NULL DEFAULT '{"shape":"squircle","color":"vert"}';
UPDATE agents SET appearance=jsonb_build_object(
    'shape',(ARRAY['cercle','galet','squircle','capsule','triangle','hexagone','nuage','goutte'])[1+get_byte(uuid_send(id),0)%8],
    'color',(ARRAY['rouge','orange','ambre','vert','turquoise','bleu','violet','rose'])[1+get_byte(uuid_send(id),1)%8]
);
ALTER TABLE agents ADD CONSTRAINT agent_appearance CHECK (
    jsonb_typeof(appearance)='object'
    AND appearance ? 'shape' AND appearance ? 'color'
    AND jsonb_typeof(appearance->'shape')='string' AND jsonb_typeof(appearance->'color')='string'
    AND appearance->>'shape' IN ('cercle','galet','squircle','capsule','triangle','hexagone','nuage','goutte')
    AND appearance->>'color' IN ('rouge','orange','ambre','vert','turquoise','bleu','violet','rose','encre','creme','brun','gris')
);
ALTER TABLE runs ADD COLUMN heartbeat_at timestamptz;

-- +goose Down
ALTER TABLE runs DROP COLUMN heartbeat_at;
ALTER TABLE agents DROP CONSTRAINT agent_appearance;
ALTER TABLE agents DROP COLUMN appearance;
ALTER TABLE agents DROP COLUMN title;
