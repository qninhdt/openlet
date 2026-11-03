package letfs

// Activity names are the generic letfs contracts in the private Temporal namespace.
const (
	CreateStorage   = "CreateStorage"
	Queue           = "openlet-letfs"
	FreezeBucket    = "FreezeBucket"
	ListFilesystems = "ListBucketFilesystems"
	PrepareDeletion = "PrepareFilesystemDeletion"
	CompleteBucket  = "CompleteBucketDeletion"
)
