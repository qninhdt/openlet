package storage

import "context"

func (s *Server) maintenance(ctx context.Context) error {
	if _, err := s.DB.Exec(ctx, `DELETE FROM archive_downloads WHERE ticket_hash IN(SELECT ticket_hash FROM archive_downloads WHERE expires_at<now() LIMIT 500)`); err != nil {
		return err
	}
	if _, err := s.DB.Exec(ctx, `DELETE FROM idempotency_keys WHERE (caller,method,key) IN(SELECT caller,method,key FROM idempotency_keys WHERE expires_at<now() LIMIT 500)`); err != nil {
		return err
	}
	rows, err := s.DB.Query(ctx, `DELETE FROM uploads WHERE id IN(SELECT id FROM uploads WHERE expires_at<now() LIMIT 500) RETURNING object_key,multipart_id`)
	if err != nil {
		return err
	}
	var expired []pendingS3Object
	for rows.Next() {
		var u pendingS3Object
		if err = rows.Scan(&u.key, &u.multipart); err != nil {
			rows.Close()
			return err
		}
		expired = append(expired, u)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	for _, u := range expired {
		_ = s.abortAndDeleteS3Object(ctx, u.key, u.multipart)
	}

	// Retry/sweep any unfinished blobs not marked for deletion.
	pending, err := s.DB.Query(ctx, `SELECT id::text,media_type,processing_attempt FROM blobs WHERE delete_requested_at IS NULL AND processing_stage IN ('queued','parsed','enriched') AND processing_error_code='' LIMIT 200`)
	if err != nil {
		return err
	}
	type todoBlob struct {
		id      string
		media   string
		attempt int64
	}
	var todo []todoBlob
	for pending.Next() {
		var b todoBlob
		if err = pending.Scan(&b.id, &b.media, &b.attempt); err != nil {
			pending.Close()
			return err
		}
		todo = append(todo, b)
	}
	err = pending.Err()
	pending.Close()
	if err != nil {
		return err
	}
	for _, b := range todo {
		if err = s.dispatchBlob(ctx, b.id, requiresParse(b.media), b.attempt); err != nil {
			return err
		}
	}

	// Sweep any deleted/orphaned blobs past grace window that were missed by immediate CleanupBlob.
	gcRows, err := s.DB.Query(ctx, `SELECT id::text FROM blobs WHERE delete_requested_at IS NOT NULL AND delete_requested_at<now()-($1*interval '1 second') LIMIT 500`, s.Settings.Maintenance.ObjectGCGraceSeconds)
	if err != nil {
		return err
	}
	var doomed []string
	for gcRows.Next() {
		var id string
		if err = gcRows.Scan(&id); err != nil {
			gcRows.Close()
			return err
		}
		doomed = append(doomed, id)
	}
	err = gcRows.Err()
	gcRows.Close()
	if err != nil {
		return err
	}
	for _, id := range doomed {
		if err = s.dispatchCleanupBlob(ctx, id); err != nil {
			return err
		}
	}
	return nil
}
