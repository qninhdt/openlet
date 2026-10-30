package letfs

import (
	"context"
	"github.com/google/uuid"
)

type DeletionInput struct {
	FilesystemID uuid.UUID `json:"filesystem_id"`
	ActorID      uuid.UUID `json:"actor_id"`
	RequestKey   uuid.UUID `json:"request_key"`
}
type Operation struct {
	ID        uuid.UUID `json:"operation_id"`
	State     string    `json:"state"`
	ErrorCode *string   `json:"error_code"`
}

func (c *Client) FreezeBucket(ctx context.Context, id uuid.UUID) error {
	var out map[string]any
	return c.post(ctx, "/internal/v1/quota-buckets/"+id.String()+"/freeze", struct{}{}, &out)
}
func (c *Client) CompleteBucketDeletion(ctx context.Context, id uuid.UUID) error {
	var out map[string]any
	return c.post(ctx, "/internal/v1/quota-buckets/"+id.String()+"/complete-deletion", struct{}{}, &out)
}
func (c *Client) DeleteFilesystem(ctx context.Context, in DeletionInput) (Operation, error) {
	var out Operation
	e := c.post(ctx, "/internal/v1/filesystems/"+in.FilesystemID.String()+"/delete", in, &out)
	return out, e
}

func (c *Client) Filesystems(ctx context.Context, bucket, after uuid.UUID) ([]uuid.UUID, error) {
	var out struct {
		Items []uuid.UUID `json:"items"`
	}
	e := c.request(ctx, "GET", "/internal/v1/quota-buckets/"+bucket.String()+"/filesystems?after="+after.String(), nil, &out)
	return out.Items, e
}
