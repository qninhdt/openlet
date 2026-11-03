package temporal

import (
	"context"

	"github.com/google/uuid"
)

type BackfillOptions struct {
	Mode  string
	Apply bool
	After uuid.UUID
	Limit int
}

type BackfillResult struct {
	Mode       string     `json:"mode"`
	Apply      bool       `json:"apply"`
	Scanned    int        `json:"scanned"`
	Eligible   int        `json:"eligible"`
	Applied    int        `json:"applied"`
	NextCursor *uuid.UUID `json:"next_cursor"`
}

func (a *Activities) Backfill(ctx context.Context, input BackfillOptions) (BackfillResult, error) {
	result := BackfillResult{Mode: input.Mode, Apply: input.Apply}
	rows, err := a.Store.BackfillCandidates(ctx, input.Mode, input.After, input.Limit)
	if err != nil {
		return result, err
	}
	result.Scanned = min(len(rows), input.Limit)
	actor := uuid.New()
	for _, c := range rows[:result.Scanned] {
		if !c.Eligible() {
			continue
		}
		result.Eligible++
		if !input.Apply {
			continue
		}
		if c.Dispatch.Source.Generation > 0 {
			running, err := a.Jobs.WorkflowStatus(ctx, c.Dispatch.Source.WorkflowID(), nil)
			if err != nil {
				return result, err
			}
			if running != nil && *running {
				continue
			}
		}
		applied, err := a.Store.AdmitBackfill(ctx, c, actor)
		if err != nil {
			return result, err
		}
		if !applied {
			continue
		}
		result.Applied++
		dispatch, err := a.Store.PendingProcessing(ctx, c.Dispatch.Source.FileID)
		if err != nil {
			return result, err
		}
		if err = a.Jobs.StartProcessing(ctx, dispatch); err != nil {
			return result, err
		}
	}
	if len(rows) > input.Limit {
		id := rows[result.Scanned-1].Dispatch.Source.FileID
		result.NextCursor = &id
	}
	return result, nil
}
