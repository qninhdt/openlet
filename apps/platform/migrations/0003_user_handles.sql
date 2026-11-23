-- +goose Up
ALTER TABLE users ADD COLUMN handle text UNIQUE;
-- +goose StatementBegin
CREATE FUNCTION assign_user_handle() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    base text := coalesce(nullif(trim(both '-' from regexp_replace(lower(NEW.display_name), '[^a-z0-9]+', '-', 'g')), ''), 'user');
    candidate text := base;
    suffix integer := 2;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('user-handle', 0));
    WHILE EXISTS (SELECT 1 FROM users WHERE handle=candidate) LOOP
        candidate := base || '-' || suffix;
        suffix := suffix + 1;
    END LOOP;
    NEW.handle := candidate;
    RETURN NEW;
END
$$;
-- +goose StatementEnd
CREATE TRIGGER user_handle BEFORE INSERT OR UPDATE OF handle ON users
FOR EACH ROW WHEN (NEW.handle IS NULL) EXECUTE FUNCTION assign_user_handle();
UPDATE users SET handle=NULL;
ALTER TABLE users ALTER COLUMN handle SET NOT NULL;
