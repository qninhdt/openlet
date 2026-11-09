package filesystem

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
)

// Components are names relative to an observed parent, never an unguarded path to create.
func (s *Store) CreateDirectories(ctx context.Context, scope uuid.UUID, parent Locator, components []string, parents bool) (Node, error) {
	if len(components) == 0 || len(components) > maxDepth || !parents && len(components) != 1 {
		return Node{}, apperr.New(apperr.Invalid, "VALIDATION", "invalid directory components")
	}
	pathBytes := 0
	for _, name := range components {
		if err := ValidateName(name); err != nil {
			return Node{}, err
		}
		pathBytes += len(name) + 1
	}
	if pathBytes > 4096 {
		return Node{}, apperr.New(apperr.Invalid, "VALIDATION", "directory path exceeds limit")
	}
	if _, err := s.authorize(ctx, scope, "scope", authz.ScopeWrite); err != nil {
		return Node{}, err
	}
	session, err := s.openSession(ctx, scope, true)
	if err != nil {
		return Node{}, err
	}
	defer session.tx.Rollback(ctx)
	node, err := session.resolveOne(ctx, parent)
	if err != nil {
		return Node{}, err
	}
	if err = guard(parent, node.ID, true); err != nil {
		return Node{}, err
	}
	if err = node.writable(); err != nil {
		return Node{}, err
	}
	if err = node.directory(); err != nil {
		return Node{}, err
	}
	depth, err := session.depth(ctx, node.ID)
	if err != nil {
		return Node{}, err
	}
	if depth+int64(len(components)) > maxDepth {
		return Node{}, apperr.New(apperr.Conflict, "RESOURCE_LIMIT", "tree depth limit exceeded")
	}
	for _, name := range components {
		if err = session.name(node.ID, name, parent.RootID); err != nil {
			return Node{}, err
		}
		var id uuid.UUID
		err = session.tx.QueryRow(ctx, `SELECT id FROM nodes WHERE scope_id=$1 AND parent_id=$2 AND name=$3`, scope, node.ID, name).Scan(&id)
		if err == nil {
			if !parents {
				return Node{}, apperr.New(apperr.Exists, "NAME_CONFLICT", "name already exists")
			}
			node, err = session.fetch(ctx, id)
			if err != nil {
				return Node{}, err
			}
			if err = node.directory(); err != nil {
				return Node{}, err
			}
			continue
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return Node{}, databaseError(err)
		}
		if err = session.addNodes(ctx, 1); err != nil {
			return Node{}, err
		}
		id = uuid.Must(uuid.NewV7())
		_, err = session.tx.Exec(ctx, `INSERT INTO nodes(id,scope_id,parent_id,name,kind) VALUES($1,$2,$3,$4,'directory')`, id, scope, node.ID, name)
		if err != nil {
			return Node{}, databaseError(err)
		}
		if err = session.bump(ctx, node.ID); err != nil {
			return Node{}, err
		}
		node, err = session.fetch(ctx, id)
		if err != nil {
			return Node{}, err
		}
	}
	return node, databaseError(session.tx.Commit(ctx))
}
