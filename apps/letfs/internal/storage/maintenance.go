package storage

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
	"github.com/qdrant/go-client/qdrant"
)

func (s *Server) maintenance(ctx context.Context) error {
	if _, err := s.DB.Exec(ctx, `DELETE FROM idempotency_keys WHERE (caller,method,key) IN(SELECT caller,method,key FROM idempotency_keys WHERE expires_at<now() LIMIT 500)`); err != nil {
		return err
	}
	rows, err := s.DB.Query(ctx, `DELETE FROM uploads WHERE id IN(SELECT id FROM uploads WHERE expires_at<now() LIMIT 500) RETURNING object_key,multipart_id`)
	if err != nil {
		return err
	}
	type multipart struct {
		key string
		id  *string
	}
	expired := []multipart{}
	for rows.Next() {
		var v multipart
		if err = rows.Scan(&v.key, &v.id); err != nil {
			rows.Close()
			return err
		}
		expired = append(expired, v)
	}
	rows.Close()
	if err = rows.Err(); err != nil {
		return err
	}
	for _, u := range expired {
		if u.id != nil {
			if _, err = s.S3.AbortMultipartUpload(ctx, &s3.AbortMultipartUploadInput{Bucket: &s.Bucket, Key: &u.key, UploadId: u.id}); err != nil {
				return err
			}
		}
	}
	rows, err = s.DB.Query(ctx, `WITH RECURSIVE candidates AS(SELECT p.file_id,f.version FROM processing p JOIN files f ON f.node_id=p.file_id WHERE p.stage<>'ready' AND p.error_code IS NULL ORDER BY p.file_id LIMIT 100),ancestry AS(SELECT c.file_id,c.version,n.id,n.parent_id,n.storage_id FROM candidates c JOIN nodes n ON n.id=c.file_id UNION ALL SELECT a.file_id,a.version,n.id,n.parent_id,n.storage_id FROM ancestry a JOIN nodes n ON n.id=a.parent_id) SELECT a.file_id,max(a.version),max(f.media_type) FROM ancestry a JOIN storages s ON s.id=a.storage_id JOIN files f ON f.node_id=a.file_id GROUP BY a.file_id HAVING bool_or(a.id=s.root_node_id)`)
	if err != nil {
		return err
	}
	type source struct {
		id      string
		version int64
		media   string
	}
	sources := []source{}
	for rows.Next() {
		var v source
		if err = rows.Scan(&v.id, &v.version, &v.media); err != nil {
			rows.Close()
			return err
		}
		sources = append(sources, v)
	}
	rows.Close()
	if err = rows.Err(); err != nil {
		return err
	}
	for _, v := range sources {
		if err = s.dispatch(ctx, v.id, v.version, requiresParse(v.media)); err != nil {
			return err
		}
	}
	if err = s.collectObjects(ctx); err != nil {
		return err
	}
	return s.collectIndex(ctx)
}
func (s *Server) collectObjects(ctx context.Context) error {
	pages := s3.NewListObjectsV2Paginator(s.S3, &s3.ListObjectsV2Input{Bucket: &s.Bucket, Prefix: aws.String("objects/"), MaxKeys: aws.Int32(1000)})
	before := time.Now().Add(-time.Duration(s.Settings.Maintenance.ObjectGCGraceSeconds) * time.Second)
	for pages.HasMorePages() {
		page, err := pages.NextPage(ctx)
		if err != nil {
			return err
		}
		keys := []string{}
		for _, v := range page.Contents {
			if v.LastModified != nil && v.LastModified.Before(before) {
				keys = append(keys, aws.ToString(v.Key))
			}
		}
		if len(keys) == 0 {
			continue
		}
		rows, err := s.DB.Query(ctx, `SELECT k.key FROM unnest($1::text[]) k(key) WHERE NOT EXISTS(SELECT 1 FROM files f WHERE f.object_key=k.key) AND NOT EXISTS(SELECT 1 FROM uploads u WHERE u.object_key=k.key AND u.result IS NULL AND u.expires_at>now())`, keys)
		if err != nil {
			return err
		}
		objects := []types.ObjectIdentifier{}
		for rows.Next() {
			var key string
			if err = rows.Scan(&key); err != nil {
				rows.Close()
				return err
			}
			objects = append(objects, types.ObjectIdentifier{Key: &key})
		}
		rows.Close()
		if err = rows.Err(); err != nil {
			return err
		}
		if len(objects) > 0 {
			result, err := s.S3.DeleteObjects(ctx, &s3.DeleteObjectsInput{Bucket: &s.Bucket, Delete: &types.Delete{Objects: objects, Quiet: aws.Bool(true)}})
			if err != nil {
				return err
			}
			if len(result.Errors) > 0 {
				return fmt.Errorf("S3 rejected %d garbage deletions", len(result.Errors))
			}
		}
	}
	return nil
}
func (s *Server) collectIndex(ctx context.Context) error {
	var offset *qdrant.PointId
	for {
		points, next, err := s.Qdrant.ScrollAndOffset(ctx, &qdrant.ScrollPoints{CollectionName: s.Collection, Offset: offset, Limit: aws.Uint32(1000), WithPayload: qdrant.NewWithPayload(true)})
		if err != nil {
			return err
		}
		if len(points) == 0 {
			return nil
		}
		records := []map[string]any{}
		byPoint := map[string]*qdrant.PointId{}
		for _, point := range points {
			id := point.Id.GetUuid()
			byPoint[id] = point.Id
			records = append(records, map[string]any{"point": id, "file": point.Payload["file_id"].GetStringValue(), "source": point.Payload["source_id"].GetStringValue(), "version": point.Payload["source_version"].GetIntegerValue()})
		}
		raw, err := json.Marshal(records)
		if err != nil {
			return err
		}
		rows, err := s.DB.Query(ctx, `WITH RECURSIVE candidates AS(SELECT * FROM jsonb_to_recordset($1::jsonb) x(point text,file uuid,source uuid,version bigint)),ancestry AS(SELECT c.*,n.id,n.parent_id,n.storage_id FROM candidates c JOIN nodes n ON n.id=c.file UNION ALL SELECT a.point,a.file,a.source,a.version,n.id,n.parent_id,n.storage_id FROM ancestry a JOIN nodes n ON n.id=a.parent_id),valid AS(SELECT a.point FROM ancestry a JOIN storages s ON s.id=a.storage_id JOIN files f ON f.node_id=a.source AND f.version=a.version GROUP BY a.point,a.source HAVING bool_or(a.id=s.root_node_id) AND bool_or(a.id=a.source)) SELECT c.point FROM candidates c WHERE NOT EXISTS(SELECT 1 FROM valid v WHERE v.point=c.point)`, raw)
		if err != nil {
			return err
		}
		ids := []*qdrant.PointId{}
		for rows.Next() {
			var id string
			if err = rows.Scan(&id); err != nil {
				rows.Close()
				return err
			}
			ids = append(ids, byPoint[id])
		}
		rows.Close()
		if err = rows.Err(); err != nil {
			return err
		}
		if len(ids) > 0 {
			if _, err = s.Qdrant.Delete(ctx, &qdrant.DeletePoints{CollectionName: s.Collection, Points: qdrant.NewPointsSelectorIDs(ids), Wait: aws.Bool(true)}); err != nil {
				return err
			}
		}
		offset = next
		if offset == nil {
			return nil
		}
	}
}
