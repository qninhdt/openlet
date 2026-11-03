package letfs

import "github.com/google/uuid"

type DeletionInput struct {
	FilesystemID uuid.UUID  `json:"filesystem_id"`
	EntryID      *uuid.UUID `json:"entry_id"`
}
