package letfs

// Activity names are the generic letfs contracts in the private Temporal namespace.
const (
	Queue               = "openlet-letfs"
	CreateBucket        = "CreateBucket"
	CreateFilesystem    = "CreateFilesystem"
	ReleaseProvisioning = "ReleaseProvisioning"
	FreezeBucket        = "FreezeBucket"
	ListFilesystems     = "ListBucketFilesystems"
	PrepareDeletion     = "PrepareFilesystemDeletion"
	CompleteBucket      = "CompleteBucketDeletion"
)
