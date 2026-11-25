package storage

import (
	"context"
	"encoding/base64"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/types/known/emptypb"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type upload struct {
	ID, Storage, Actor, Root, BlobID, Key, Media, Checksum string
	Parent, Name, Target, Multipart                        *string
	Expected                                               *int64
	Size                                                   int64
	Result                                                 []byte
	Expires                                                time.Time
}

const uploadColumns = `u.id,u.storage_id,u.actor,u.root_id,u.parent_id,u.name,u.target_node_id,u.expected_version,u.blob_id::text,u.object_key,u.size_bytes,u.media_type,u.checksum,u.multipart_id,u.result,u.expires_at`

func (s *Server) fileMedia(name string, expected sdk.FileKind) (string, error) {
	kind, media := s.FileTypes.ClassifyFile(name)
	if kind == sdk.FileUnsupported {
		return "", invalid("unsupported file extension")
	}
	if kind != expected {
		return "", invalid("file extension does not match storage type")
	}
	return media, nil
}

func getUpload(ctx context.Context, q queryer, workspace, storage, id, actor string, lock bool) (upload, error) {
	var u upload
	sql := `SELECT ` + uploadColumns + ` FROM uploads u JOIN storages s ON s.id=u.storage_id WHERE u.id=$1 AND u.storage_id=$2 AND s.workspace_id=$3 AND u.actor=$4 AND u.expires_at>now()`
	if lock {
		sql += ` FOR UPDATE`
	}
	err := q.QueryRow(ctx, sql, id, storage, workspace, actor).Scan(&u.ID, &u.Storage, &u.Actor, &u.Root, &u.Parent, &u.Name, &u.Target, &u.Expected, &u.BlobID, &u.Key, &u.Size, &u.Media, &u.Checksum, &u.Multipart, &u.Result, &u.Expires)
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
	out := make(map[string]string, len(signed))
	for name, values := range signed {
		if len(values) > 0 {
			out[name] = strings.Join(values, ",")
		}
	}
	return out
}

func (s *Server) uploadView(ctx context.Context, u upload) (*pb.Upload, error) {
	ttl := time.Until(u.Expires)
	if ttl < time.Second {
		ttl = time.Second
	}
	out := &pb.Upload{Id: u.ID, ExpiresAt: timestamppb.New(u.Expires)}
	if u.Multipart != nil {
		out.Transfer = &pb.TransferDescriptor{Multipart: true, PartSizeBytes: s.Settings.MultipartPartBytes}
		return out, nil
	}
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
	checksum, err := base64.StdEncoding.DecodeString(r.Checksum)
	if err != nil || len(checksum) != 4 {
		return nil, invalid("checksum must be base64 CRC32C of the complete object")
	}
	var locator *pb.NodeLocator
	var parent, name, node *string
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
		return nil, invalid("storage does not allow blob files")
	}
	if err = writable(target); err != nil {
		return nil, err
	}
	var filename string
	if name != nil {
		if err = directory(target); err != nil {
			return nil, err
		}
		parent = &target.Node.Id
		filename = *name
	} else {
		if target.Node.GetFile().GetType() != pb.FileType_FILE_TYPE_BLOB {
			return nil, invalid("upload replacement requires a blob")
		}
		filename = target.Node.Name
		if target.Node.File.Version != *expected {
			return nil, conflict("content version changed")
		}
		node = &target.Node.Id
		parent = &target.Root
	}
	media, err := s.fileMedia(filename, sdk.FileBlob)
	if err != nil {
		return nil, err
	}
	id := uuid.NewString()
	blobID := uuid.NewString()
	key := fmt.Sprintf("workspaces/%s/blobs/%s/source", r.WorkspaceId, blobID)
	u := upload{
		ID: id, Storage: r.StorageId, Actor: a.String(), Root: target.Root,
		Parent: parent, Name: name, Target: node, Expected: expected,
		BlobID: blobID, Key: key, Size: r.SizeBytes, Media: media, Checksum: r.Checksum,
		Expires: time.Now().Add(time.Duration(s.Settings.UploadURLTTLSeconds) * time.Second),
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	out := new(pb.Upload)
	duplicate, err := sdk.Claim(ctx, tx, a.String(), "CreateUpload", r.RequestId, r, out, s.ttl())
	if err != nil {
		return nil, err
	}
	if duplicate {
		return out, tx.Commit(ctx)
	}
	committed := false
	defer func() {
		if !committed && u.Multipart != nil {
			_ = s.abortAndDeleteS3Object(context.WithoutCancel(ctx), u.Key, u.Multipart)
		}
	}()
	if r.SizeBytes >= s.Settings.MultipartThresholdBytes {
		created, err := s.S3.CreateMultipartUpload(ctx, &s3.CreateMultipartUploadInput{
			Bucket: &s.Bucket, Key: &key, ContentType: &media,
			ChecksumAlgorithm: types.ChecksumAlgorithmCrc32c, ChecksumType: types.ChecksumTypeFullObject,
		})
		if err != nil {
			return nil, err
		}
		u.Multipart = created.UploadId
	}
	view, err := s.uploadView(ctx, u)
	if err != nil {
		return nil, err
	}
	_, err = tx.Exec(ctx, `INSERT INTO uploads(id,storage_id,actor,root_id,parent_id,name,target_node_id,expected_version,blob_id,object_key,size_bytes,media_type,checksum,multipart_id,expires_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)`,
		u.ID, u.Storage, u.Actor, u.Root, u.Parent, u.Name, u.Target, u.Expected, u.BlobID, u.Key, u.Size, u.Media, u.Checksum, u.Multipart, u.Expires)
	if err != nil {
		return nil, err
	}
	if err = sdk.Finish(ctx, tx, a.String(), "CreateUpload", r.RequestId, view); err != nil {
		return nil, err
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	committed = true
	return view, nil
}

func (s *Server) GetUpload(ctx context.Context, r *pb.UploadRequest) (*pb.Upload, error) {
	a, err := s.check(ctx, "storage", r.StorageId, "write")
	if err != nil {
		return nil, err
	}
	u, err := getUpload(ctx, s.DB, r.WorkspaceId, r.StorageId, r.UploadId, a.String(), false)
	if err == pgx.ErrNoRows {
		return nil, notFound()
	}
	if err != nil {
		return nil, err
	}
	out, err := s.uploadView(ctx, u)
	if err != nil {
		return nil, err
	}
	if u.Result != nil {
		out.Completed = new(pb.Node)
		if err = protojson.Unmarshal(u.Result, out.Completed); err != nil {
			return nil, err
		}
		out.Transferred = true
		return out, nil
	}
	head, err := s.S3.HeadObject(ctx, &s3.HeadObjectInput{Bucket: &s.Bucket, Key: &u.Key, ChecksumMode: types.ChecksumModeEnabled})
	if err == nil {
		if aws.ToInt64(head.ContentLength) != u.Size || aws.ToString(head.ChecksumCRC32C) != u.Checksum {
			return nil, invalid("uploaded object does not match session")
		}
		out.Transferred = true
		return out, nil
	}
	if u.Multipart != nil {
		pages := s3.NewListPartsPaginator(s.S3, &s3.ListPartsInput{Bucket: &s.Bucket, Key: &u.Key, UploadId: u.Multipart})
		for pages.HasMorePages() {
			page, err := pages.NextPage(ctx)
			if err != nil {
				return nil, err
			}
			for _, part := range page.Parts {
				out.CompletedParts = append(out.CompletedParts, &pb.CompletedPart{
					PartNumber: uint32(aws.ToInt32(part.PartNumber)),
					Etag:       aws.ToString(part.ETag),
					Checksum:   aws.ToString(part.ChecksumCRC32C),
				})
			}
		}
	}
	return out, nil
}

func (s *Server) SignParts(ctx context.Context, r *pb.SignPartsRequest) (*pb.SignPartsResponse, error) {
	a, err := s.check(ctx, "storage", r.StorageId, "write")
	if err != nil {
		return nil, err
	}
	u, err := getUpload(ctx, s.DB, r.WorkspaceId, r.StorageId, r.UploadId, a.String(), false)
	if err == pgx.ErrNoRows {
		return nil, notFound()
	}
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
		signed, err := s.Presign.PresignUploadPart(ctx, &s3.UploadPartInput{
			Bucket: &s.Bucket, Key: &u.Key, UploadId: u.Multipart,
			PartNumber: aws.Int32(int32(part.PartNumber)), ChecksumCRC32C: &part.Checksum,
		}, func(o *s3.PresignOptions) {
			o.Expires = time.Duration(s.Settings.UploadURLTTLSeconds) * time.Second
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
		if len(parts) == 0 {
			return invalid("multipart upload requires completed parts")
		}
		native := make([]types.CompletedPart, len(parts))
		for i, p := range parts {
			native[i] = types.CompletedPart{PartNumber: aws.Int32(int32(p.PartNumber)), ETag: &p.Etag, ChecksumCRC32C: &p.Checksum}
		}
		_, err = s.S3.CompleteMultipartUpload(ctx, &s3.CompleteMultipartUploadInput{
			Bucket: &s.Bucket, Key: &u.Key, UploadId: u.Multipart,
			MultipartUpload: &types.CompletedMultipartUpload{Parts: native},
			ChecksumCRC32C:  &u.Checksum, ChecksumType: types.ChecksumTypeFullObject, IfNoneMatch: aws.String("*"),
		})
		if err != nil {
			return err
		}
		head, err = s.S3.HeadObject(ctx, &s3.HeadObjectInput{Bucket: &s.Bucket, Key: &u.Key, ChecksumMode: types.ChecksumModeEnabled})
	}
	if err != nil {
		return status.Error(codes.FailedPrecondition, "object has not been uploaded")
	}
	if aws.ToInt64(head.ContentLength) != u.Size || aws.ToString(head.ChecksumCRC32C) != u.Checksum {
		return invalid("uploaded object does not match session")
	}
	return nil
}

func (s *Server) CompleteUpload(ctx context.Context, r *pb.CompleteUploadRequest) (*pb.Node, error) {
	a, err := s.check(ctx, "storage", r.StorageId, "write")
	if err != nil {
		return nil, err
	}
	u, err := getUpload(ctx, s.DB, r.WorkspaceId, r.StorageId, r.UploadId, a.String(), false)
	if err == pgx.ErrNoRows {
		return nil, notFound()
	}
	if err != nil {
		return nil, err
	}
	if u.Result != nil {
		out := new(pb.Node)
		return out, protojson.Unmarshal(u.Result, out)
	}
	if err = s.verifyObject(ctx, u, r.Parts); err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	out := new(pb.Node)
	u, err = getUpload(ctx, tx, r.WorkspaceId, r.StorageId, r.UploadId, a.String(), true)
	if err == pgx.ErrNoRows {
		return nil, notFound()
	}
	if err != nil {
		return nil, err
	}
	if u.Result != nil {
		if err = protojson.Unmarshal(u.Result, out); err != nil {
			return nil, err
		}
		return out, tx.Commit(ctx)
	}
	var target *string
	lock := true
	if u.Target != nil {
		target = u.Target
	} else {
		target = u.Parent
		lock = false
	}
	current, err := oneResolved(ctx, tx, r.WorkspaceId, r.StorageId, &pb.NodeLocator{Locator: &pb.NodeLocator_NodeId{NodeId: *target}, RootNodeId: &u.Root}, false, lock)
	if err != nil {
		return nil, err
	}
	if !current.AllowBlob {
		return nil, invalid("storage does not allow blob files")
	}

	var stage *string
	var summary *pb.ProcessingSummary
	if supportedMedia(u.Media) {
		st := processingStage(u.Media)
		stage = &st
		summary = &pb.ProcessingSummary{Stage: st}
	}
	sourceName := current.Node.Name
	if u.Name != nil {
		sourceName = *u.Name
	}
	if _, err = tx.Exec(ctx, `INSERT INTO blobs(id,workspace_id,object_key,size_bytes,media_type,checksum,source_name,processing_stage) VALUES($1,$2,$3,$4,$5,$6,$7,$8)`,
		u.BlobID, r.WorkspaceId, u.Key, u.Size, u.Media, u.Checksum, sourceName, stage); err != nil {
		return nil, err
	}

	var at time.Time
	var delta int64
	var orphaned []string
	if u.Target == nil {
		if err = directory(current); err != nil {
			return nil, err
		}
		id := uuid.NewString()
		err = tx.QueryRow(ctx, `WITH n AS(INSERT INTO nodes(id,storage_id,parent_id,name,kind) VALUES($1,$2,$3,$4,'file') RETURNING id,created_at),f AS(INSERT INTO files(node_id,version,blob_id,size_bytes,media_type) SELECT id,1,$5,$6,$7 FROM n) SELECT created_at FROM n`,
			id, r.StorageId, current.Node.Id, *u.Name, u.BlobID, u.Size, u.Media).Scan(&at)
		if err != nil {
			return nil, err
		}
		out = &pb.Node{
			Id: id, StorageId: r.StorageId, ParentId: &current.Node.Id, Name: *u.Name,
			Kind: pb.NodeKind_NODE_KIND_FILE, CreatedAt: timestamppb.New(at), UpdatedAt: timestamppb.New(at),
			File: &pb.FileHeader{Version: 1, SizeBytes: u.Size, MediaType: u.Media, Type: pb.FileType_FILE_TYPE_BLOB, Processing: summary},
		}
		delta = u.Size
	} else {
		if current.Node.GetFile().GetType() != pb.FileType_FILE_TYPE_BLOB || current.Node.File.Version != *u.Expected {
			return nil, conflict("content version changed")
		}
		if _, err = s.fileMedia(current.Node.Name, sdk.FileBlob); err != nil {
			return nil, conflict("upload destination format changed")
		}
		oldSize := current.Node.File.SizeBytes
		oldBlobID := current.BlobID
		out = current.Node
		err = tx.QueryRow(ctx, `WITH changed AS(UPDATE files SET text_content=NULL,blob_id=$2,size_bytes=$3,media_type=$4,version=version+1 WHERE node_id=$1 RETURNING version),
			touched AS(UPDATE nodes SET updated_at=now() WHERE id=$1 RETURNING updated_at)
			SELECT c.version,t.updated_at FROM changed c CROSS JOIN touched t`,
			out.Id, u.BlobID, u.Size, u.Media).Scan(&out.File.Version, &at)
		if err != nil {
			return nil, err
		}
		delta = u.Size - oldSize
		out.File = &pb.FileHeader{Version: out.File.Version, SizeBytes: u.Size, MediaType: u.Media, Type: pb.FileType_FILE_TYPE_BLOB, Processing: summary}
		out.UpdatedAt = timestamppb.New(at)
		if oldBlobID != nil && *oldBlobID != u.BlobID {
			orphaned, err = markOrphanBlobs(ctx, tx, []string{*oldBlobID})
			if err != nil {
				return nil, err
			}
		}
	}

	b, err := protojson.Marshal(out)
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
		if err = s.dispatchBlob(ctx, u.BlobID, requiresParse(u.Media), 0); err != nil {
			return nil, err
		}
	}
	for _, oldID := range orphaned {
		if err = s.dispatchCleanupBlob(ctx, oldID); err != nil {
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
	err = s.DB.QueryRow(ctx, `DELETE FROM uploads u USING storages s WHERE u.id=$1 AND u.storage_id=$2 AND s.id=u.storage_id AND s.workspace_id=$3 AND u.actor=$4 AND u.result IS NULL RETURNING u.object_key,u.multipart_id`,
		r.UploadId, r.StorageId, r.WorkspaceId, a.String()).Scan(&key, &multipart)
	if err == pgx.ErrNoRows {
		return nil, notFound()
	}
	if err != nil {
		return nil, err
	}
	return &emptypb.Empty{}, s.abortAndDeleteS3Object(ctx, key, multipart)
}
