package storage

import (
	"context"
	"encoding/base64"
	"errors"
	"mime"
	"net/http"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
	"github.com/aws/smithy-go"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/emptypb"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type upload struct {
	ID, Storage, Actor, Root, Key, Media, Checksum string
	Parent, Name, Target, Multipart                *string
	Expected                                       *int64
	Size                                           int64
	Result                                         []byte
	Expires                                        time.Time
}

const uploadColumns = `u.id,u.storage_id,u.actor,u.root_id,u.parent_id,u.name,u.target_node_id,u.expected_version,u.object_key,u.size_bytes,u.media_type,u.checksum,u.multipart_id,u.result,u.expires_at`

func blobMediaType(value string) (string, error) {
	media, _, err := mime.ParseMediaType(value)
	if err != nil {
		return "", invalid("invalid media type")
	}
	if strings.HasPrefix(media, "text/") || media == "application/json" || media == "application/xml" || media == "application/javascript" || media == "application/yaml" || media == "application/toml" || strings.HasSuffix(media, "+json") || strings.HasPrefix(media, "application/") && strings.HasSuffix(media, "+xml") {
		return "", invalid("text must use CreateNode or MutateText and is stored in PostgreSQL")
	}
	return media, nil
}

func getUpload(ctx context.Context, q queryer, workspace, storage, id, actor string, lock bool) (upload, error) {
	var u upload
	sql := `SELECT ` + uploadColumns + ` FROM uploads u JOIN storages s ON s.id=u.storage_id WHERE u.id=$1 AND u.storage_id=$2 AND s.workspace_id=$3 AND u.actor=$4 AND u.source_file_id IS NULL AND u.expires_at>now()`
	if lock {
		sql += ` FOR UPDATE OF u`
	}
	err := q.QueryRow(ctx, sql, id, storage, workspace, actor).Scan(&u.ID, &u.Storage, &u.Actor, &u.Root, &u.Parent, &u.Name, &u.Target, &u.Expected, &u.Key, &u.Size, &u.Media, &u.Checksum, &u.Multipart, &u.Result, &u.Expires)
	return u, err
}
func (s *Server) signedPut(ctx context.Context, key, media, checksum string, size int64, ttl time.Duration) (*pb.TransferDescriptor, error) {
	signed, err := s.Presign.PresignPutObject(ctx, &s3.PutObjectInput{Bucket: &s.Bucket, Key: &key, ContentType: &media, ContentLength: &size, ChecksumCRC32C: &checksum, IfNoneMatch: aws.String("*")}, func(o *s3.PresignOptions) { o.Expires = ttl })
	if err != nil {
		return nil, err
	}
	return &pb.TransferDescriptor{PutUrl: signed.URL, Headers: signedHeaders(signed.SignedHeader)}, nil
}
func signedHeaders(signed http.Header) map[string]string {
	headers := map[string]string{}
	for k, v := range signed {
		if len(v) > 0 && k != "Host" {
			headers[k] = v[0]
		}
	}
	return headers
}
func (s *Server) uploadView(ctx context.Context, u upload) (*pb.Upload, error) {
	out := &pb.Upload{Id: u.ID, ExpiresAt: timestamppb.New(u.Expires)}
	if u.Result != nil {
		out.Completed = new(pb.Node)
		return out, proto.Unmarshal(u.Result, out.Completed)
	}
	if u.Multipart != nil {
		out.Transfer = &pb.TransferDescriptor{Multipart: true, PartSizeBytes: s.Settings.MultipartPartBytes}
		return out, nil
	}
	ttl := min(time.Until(u.Expires), time.Duration(s.Settings.UploadURLTTLSeconds)*time.Second)
	transfer, err := s.signedPut(ctx, u.Key, u.Media, u.Checksum, u.Size, ttl)
	out.Transfer = transfer
	return out, err
}
func (s *Server) CreateUpload(ctx context.Context, r *pb.CreateUploadRequest) (*pb.Upload, error) {
	a, err := s.check(ctx, "storage", r.StorageId, "write")
	if err != nil {
		return nil, err
	}
	if r.SizeBytes > s.Settings.MaxBlobBytes {
		return nil, status.Error(codes.ResourceExhausted, "blob exceeds configured limit")
	}
	media, err := blobMediaType(r.MediaType)
	if err != nil {
		return nil, err
	}
	checksum, err := base64.StdEncoding.DecodeString(r.Checksum)
	if err != nil || len(checksum) != 4 {
		return nil, invalid("checksum must be base64 CRC32C of the complete object")
	}
	out := new(pb.Upload)
	if duplicate, err := sdk.Replay(ctx, s.DB, a.String(), "CreateUpload", r.RequestId, r, out); err != nil || duplicate {
		return out, err
	}
	var locator *pb.NodeLocator
	var name *string
	var expected *int64
	switch d := r.Destination.(type) {
	case *pb.CreateUploadRequest_Create:
		locator = d.Create.Parent
		name = &d.Create.Name
	case *pb.CreateUploadRequest_Replace:
		locator = d.Replace.Target
		expected = &d.Replace.ExpectedVersion
	}
	target, err := oneResolved(ctx, s.DB, r.WorkspaceId, r.StorageId, locator, false, false)
	if err != nil {
		return nil, err
	}
	if !target.AllowBlob {
		return nil, status.Error(codes.FailedPrecondition, "storage does not allow blob files")
	}
	if err = writable(target); err != nil {
		return nil, err
	}
	var parent, node *string
	if name != nil {
		if err = directory(target); err != nil {
			return nil, err
		}
		parent = &target.Node.Id
	} else {
		if target.Node.File == nil {
			return nil, invalid("upload replacement requires a file")
		}
		if target.Node.File.Version != *expected {
			return nil, conflict("content version changed")
		}
		node = &target.Node.Id
	}
	id := uuid.NewString()
	key := "objects/" + id
	u := upload{ID: id, Storage: r.StorageId, Actor: a.String(), Root: target.Root, Parent: parent, Name: name, Target: node, Expected: expected, Key: key, Size: r.SizeBytes, Media: media, Checksum: r.Checksum, Expires: time.Now().Add(time.Duration(s.Settings.UploadURLTTLSeconds) * time.Second)}
	if r.SizeBytes >= s.Settings.MultipartThresholdBytes {
		created, err := s.S3.CreateMultipartUpload(ctx, &s3.CreateMultipartUploadInput{Bucket: &s.Bucket, Key: &key, ContentType: &media, ChecksumAlgorithm: types.ChecksumAlgorithmCrc32c, ChecksumType: types.ChecksumTypeFullObject})
		if err != nil {
			return nil, err
		}
		u.Multipart = created.UploadId
	}
	view, err := s.uploadView(ctx, u)
	if err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	duplicate, err := sdk.Claim(ctx, tx, a.String(), "CreateUpload", r.RequestId, r, out, s.ttl())
	if err != nil {
		return nil, err
	}
	if duplicate {
		return out, tx.Commit(ctx)
	}
	_, err = tx.Exec(ctx, `INSERT INTO uploads(id,storage_id,actor,root_id,parent_id,name,target_node_id,expected_version,object_key,size_bytes,media_type,checksum,multipart_id,expires_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)`, u.ID, u.Storage, u.Actor, u.Root, u.Parent, u.Name, u.Target, u.Expected, u.Key, u.Size, u.Media, u.Checksum, u.Multipart, u.Expires)
	if err != nil {
		return nil, err
	}
	if err = sdk.Finish(ctx, tx, a.String(), "CreateUpload", r.RequestId, view); err != nil {
		return nil, err
	}
	return view, tx.Commit(ctx)
}
func (s *Server) GetUpload(ctx context.Context, r *pb.UploadRequest) (*pb.Upload, error) {
	a, err := s.check(ctx, "storage", r.StorageId, "write")
	if err != nil {
		return nil, err
	}
	u, err := getUpload(ctx, s.DB, r.WorkspaceId, r.StorageId, r.UploadId, a.String(), false)
	if err != nil {
		return nil, err
	}
	return s.uploadView(ctx, u)
}
func (s *Server) SignParts(ctx context.Context, r *pb.SignPartsRequest) (*pb.SignPartsResponse, error) {
	a, err := s.check(ctx, "storage", r.StorageId, "write")
	if err != nil {
		return nil, err
	}
	u, err := getUpload(ctx, s.DB, r.WorkspaceId, r.StorageId, r.UploadId, a.String(), false)
	if err != nil {
		return nil, err
	}
	if u.Multipart == nil || u.Result != nil {
		return nil, invalid("upload is not an open multipart transfer")
	}
	out := new(pb.SignPartsResponse)
	for _, part := range r.Parts {
		checksum, err := base64.StdEncoding.DecodeString(part.Checksum)
		if err != nil || len(checksum) != 4 {
			return nil, invalid("part checksum must be base64 CRC32C")
		}
		if int64(part.PartNumber) > max(int64(1), (u.Size+s.Settings.MultipartPartBytes-1)/s.Settings.MultipartPartBytes) {
			return nil, invalid("part number exceeds object size")
		}
		signed, err := s.Presign.PresignUploadPart(ctx, &s3.UploadPartInput{Bucket: &s.Bucket, Key: &u.Key, UploadId: u.Multipart, PartNumber: aws.Int32(int32(part.PartNumber)), ChecksumCRC32C: &part.Checksum}, func(o *s3.PresignOptions) {
			o.Expires = min(time.Until(u.Expires), time.Duration(s.Settings.UploadURLTTLSeconds)*time.Second)
		})
		if err != nil {
			return nil, err
		}
		out.Parts = append(out.Parts, &pb.SignedPart{PartNumber: part.PartNumber, Url: signed.URL, Headers: signedHeaders(signed.SignedHeader)})
	}
	return out, nil
}
func (s *Server) verifyObject(ctx context.Context, u upload, parts []*pb.CompletedPart) error {
	head, err := s.S3.HeadObject(ctx, &s3.HeadObjectInput{Bucket: &s.Bucket, Key: &u.Key, ChecksumMode: types.ChecksumModeEnabled})
	if err != nil && u.Multipart != nil {
		var api smithy.APIError
		if !errors.As(err, &api) || (api.ErrorCode() != "NotFound" && api.ErrorCode() != "NoSuchKey") {
			return err
		}
		native := make([]types.CompletedPart, len(parts))
		for i, p := range parts {
			native[i] = types.CompletedPart{PartNumber: aws.Int32(int32(p.PartNumber)), ETag: &p.Etag, ChecksumCRC32C: &p.Checksum}
		}
		_, err = s.S3.CompleteMultipartUpload(ctx, &s3.CompleteMultipartUploadInput{Bucket: &s.Bucket, Key: &u.Key, UploadId: u.Multipart, MultipartUpload: &types.CompletedMultipartUpload{Parts: native}, ChecksumCRC32C: &u.Checksum, ChecksumType: types.ChecksumTypeFullObject, IfNoneMatch: aws.String("*")})
		if err != nil {
			return err
		}
		head, err = s.S3.HeadObject(ctx, &s3.HeadObjectInput{Bucket: &s.Bucket, Key: &u.Key, ChecksumMode: types.ChecksumModeEnabled})
	}
	if err != nil {
		return err
	}
	if aws.ToInt64(head.ContentLength) != u.Size || aws.ToString(head.ChecksumCRC32C) != u.Checksum {
		return status.Error(codes.FailedPrecondition, "uploaded bytes or CRC32C do not match descriptor")
	}
	return nil
}
func (s *Server) CompleteUpload(ctx context.Context, r *pb.CompleteUploadRequest) (*pb.Node, error) {
	a, err := s.check(ctx, "storage", r.StorageId, "write")
	if err != nil {
		return nil, err
	}
	u, err := getUpload(ctx, s.DB, r.WorkspaceId, r.StorageId, r.UploadId, a.String(), false)
	if err != nil {
		return nil, err
	}
	if u.Result != nil {
		out := new(pb.Node)
		return out, proto.Unmarshal(u.Result, out)
	}
	if err = s.verifyObject(ctx, u, r.Parts); err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	target := u.Parent
	lock := false
	if u.Target != nil {
		target = u.Target
		lock = true
	}
	current, err := oneResolved(ctx, tx, r.WorkspaceId, r.StorageId, &pb.NodeLocator{Locator: &pb.NodeLocator_NodeId{NodeId: *target}, RootNodeId: &u.Root}, false, lock)
	if err != nil {
		return nil, err
	}
	if err = writable(current); err != nil {
		return nil, err
	}
	u, err = getUpload(ctx, tx, r.WorkspaceId, r.StorageId, r.UploadId, a.String(), true)
	if err != nil {
		return nil, err
	}
	if u.Result != nil {
		out := new(pb.Node)
		return out, proto.Unmarshal(u.Result, out)
	}
	var out *pb.Node
	var delta int64
	if u.Target == nil {
		if err = directory(current); err != nil {
			return nil, err
		}
		id := uuid.NewString()
		var at time.Time
		err = tx.QueryRow(ctx, `WITH n AS(INSERT INTO nodes(id,storage_id,parent_id,name,kind) VALUES($1,$2,$3,$4,'file') RETURNING id,created_at),f AS(INSERT INTO files(node_id,version,size_bytes,media_type,object_key) SELECT id,1,$5,$6,$7 FROM n) SELECT created_at FROM n`, id, r.StorageId, current.Node.Id, u.Name, u.Size, u.Media, u.Key).Scan(&at)
		if err != nil {
			return nil, err
		}
		out = &pb.Node{Id: id, StorageId: r.StorageId, ParentId: &current.Node.Id, Name: *u.Name, Kind: pb.NodeKind_NODE_KIND_FILE, CreatedAt: timestamppb.New(at), UpdatedAt: timestamppb.New(at), File: &pb.FileHeader{Version: 1, SizeBytes: u.Size, MediaType: u.Media, Type: pb.FileType_FILE_TYPE_BLOB}}
		delta = u.Size
	} else {
		if current.Node.File == nil || current.Node.File.Version != *u.Expected {
			return nil, conflict("content version changed")
		}
		out = current.Node
		oldSize := out.File.SizeBytes
		var deleted int64
		var at time.Time
		err = tx.QueryRow(ctx, `WITH RECURSIVE descendants AS(SELECT id FROM nodes WHERE parent_id=$1 UNION ALL SELECT n.id FROM nodes n JOIN descendants d ON n.parent_id=d.id),deleted AS(DELETE FROM nodes n USING descendants d LEFT JOIN files f ON f.node_id=d.id WHERE n.id=d.id RETURNING coalesce(f.size_bytes,0) AS bytes),metadata AS(DELETE FROM file_metadata WHERE node_id=$1),stage AS(DELETE FROM processing WHERE file_id=$1),changed AS(UPDATE files SET text_content=NULL,object_key=$2,size_bytes=$3,media_type=$4,version=version+1 WHERE node_id=$1 RETURNING version),touched AS(UPDATE nodes SET updated_at=now() WHERE id=$1 RETURNING updated_at) SELECT c.version,t.updated_at,(SELECT coalesce(sum(bytes),0) FROM deleted) FROM changed c CROSS JOIN touched t`, out.Id, u.Key, u.Size, u.Media).Scan(&out.File.Version, &at, &deleted)
		if err != nil {
			return nil, err
		}
		out.UpdatedAt = timestamppb.New(at)
		delta = u.Size - oldSize - deleted
		out.File = &pb.FileHeader{Version: out.File.Version, SizeBytes: u.Size, MediaType: u.Media, Type: pb.FileType_FILE_TYPE_BLOB}
	}
	if supportedMedia(u.Media) {
		if _, err = tx.Exec(ctx, `INSERT INTO processing(file_id,stage) VALUES($1,$2)`, out.Id, processingStage(u.Media)); err != nil {
			return nil, err
		}
		out.File.Processing = &pb.ProcessingSummary{Stage: processingStage(u.Media)}
	}
	b, err := proto.Marshal(out)
	if err != nil {
		return nil, err
	}
	if _, err = tx.Exec(ctx, `UPDATE uploads SET result=$2,expires_at=$3 WHERE id=$1`, u.ID, b, time.Now().Add(s.ttl())); err != nil {
		return nil, err
	}
	if err = s.quota(ctx, tx, r.WorkspaceId, delta); err != nil {
		return nil, err
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	if supportedMedia(u.Media) {
		if err = s.dispatch(ctx, out.Id, out.File.Version, requiresParse(u.Media)); err != nil {
			return nil, err
		}
	}
	return out, nil
}
func (s *Server) AbortUpload(ctx context.Context, r *pb.UploadRequest) (*emptypb.Empty, error) {
	a, err := s.check(ctx, "storage", r.StorageId, "write")
	if err != nil {
		return nil, err
	}
	var key string
	var multipart *string
	err = s.DB.QueryRow(ctx, `DELETE FROM uploads u USING storages s WHERE u.id=$1 AND u.storage_id=$2 AND s.id=u.storage_id AND s.workspace_id=$3 AND u.actor=$4 AND u.result IS NULL RETURNING u.object_key,u.multipart_id`, r.UploadId, r.StorageId, r.WorkspaceId, a.String()).Scan(&key, &multipart)
	if err == pgx.ErrNoRows {
		return &emptypb.Empty{}, nil
	}
	if err != nil {
		return nil, err
	}
	if multipart != nil {
		_, err = s.S3.AbortMultipartUpload(ctx, &s3.AbortMultipartUploadInput{Bucket: &s.Bucket, Key: &key, UploadId: multipart})
	}
	return &emptypb.Empty{}, err
}
