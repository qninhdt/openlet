package letfs

import "github.com/google/uuid"

type DeletionInput struct {
	FilesystemID uuid.UUID  `json:"filesystem_id"`
	ActorID      uuid.UUID  `json:"actor_id"`
	EntryID      *uuid.UUID `json:"entry_id"`
	Revision     *string    `json:"revision"`
}
