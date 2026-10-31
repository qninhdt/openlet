use crate::http::{ApiError, App};
use object_store::ObjectStoreExt;
use sqlx::Row;
use uuid::Uuid;

pub async fn expire_uploads(app: &App) -> Result<u32, ApiError> {
    let rows=sqlx::query("SELECT id,filesystem_id FROM uploads WHERE state IN ('open','completing') AND expires_at<=now() ORDER BY expires_at,id LIMIT 64").fetch_all(&app.pool).await?;
    let count = rows.len() as u32;
    for row in rows {
        super::uploads::expire(app, row.get("filesystem_id"), row.get("id")).await?;
    }
    let rows=sqlx::query("SELECT id,candidate_key,multipart_id FROM uploads WHERE state IN ('aborted') AND multipart_id IS NOT NULL ORDER BY updated_at,id LIMIT 64").fetch_all(&app.pool).await?;
    for row in rows {
        super::uploads::abort_multipart(
            app,
            row.get("id"),
            &row.get::<String, _>("candidate_key"),
            &row.get::<String, _>("multipart_id"),
        )
        .await?;
    }
    Ok(count)
}
pub async fn reconcile(app: &App) -> Result<u32, ApiError> {
    let mut count = super::artifacts::discard_forests(app).await?;
    let purges=sqlx::query("SELECT filesystem_id,id,actor_id FROM trash_entries WHERE state='purging' ORDER BY created_at,id LIMIT 64").fetch_all(&app.pool).await?;
    for row in purges {
        crate::temporal::start_deletion(
            app,
            super::deletion::Start {
                filesystem_id: row.get("filesystem_id"),
                actor_id: row.get("actor_id"),
                entry_id: Some(row.get("id")),
                revision: None,
            },
        )
        .await?;
    }
    count += super::processing::maintain(app).await?;
    match super::indexing::cleanup(app).await {
        Ok(cleaned) => count += cleaned,
        Err(_) => tracing::warn!("search index cleanup deferred"),
    }
    let rows=sqlx::query("SELECT result FROM idempotency_keys WHERE operation='copy-node' AND completed_at IS NULL ORDER BY result->>'id' LIMIT 64").fetch_all(&app.pool).await?;
    for row in rows {
        let admission: super::copy::Admission =
            serde_json::from_value(row.get("result")).map_err(|_| ApiError::conflict())?;
        match super::processing::workflow_status_since(app, &admission.workflow_id(), None).await? {
            Some(true) => {}
            Some(false) => {
                super::copy::complete(app, &admission).await?;
                count += 1;
            }
            None => {
                crate::temporal::start_copy(app, admission).await?;
                count += 1;
            }
        }
    }
    Ok(count)
}
pub async fn delete_objects(app: &App) -> Result<u32, ApiError> {
    let rows=sqlx::query("SELECT object_key,bucket_id FROM object_deletions WHERE eligible_at<=now() AND (state!='deleted' OR ambiguous_write OR open_writes>0) ORDER BY eligible_at,object_key LIMIT 64").fetch_all(&app.pool).await?;
    let mut count = 0;
    let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(180);
    for row in rows {
        if tokio::time::Instant::now() >= deadline {
            break;
        }
        let bucket: Uuid = row.get("bucket_id");
        let key: String = row.get("object_key");
        let mut tx = app.pool.begin().await?;
        sqlx::query("SELECT id FROM quota_buckets WHERE id=$1 FOR UPDATE")
            .bind(bucket)
            .fetch_one(&mut *tx)
            .await?;
        let claimed:Option<bool>=sqlx::query_scalar("UPDATE object_deletions d SET state='deleting',attempts=attempts+1,eligible_at=now()+interval '15 minutes',updated_at=now() WHERE d.object_key=$1 AND d.eligible_at<=now() AND (d.state!='deleted' OR d.ambiguous_write OR d.open_writes>0) AND NOT EXISTS(SELECT 1 FROM files WHERE object_key=d.object_key) AND NOT EXISTS(SELECT 1 FROM uploads WHERE candidate_key=d.object_key AND state IN ('open','completing')) RETURNING ambiguous_write OR open_writes>0")
            .bind(&key).fetch_optional(&mut *tx).await?;
        tx.commit().await?;
        let Some(ambiguous) = claimed else {
            sqlx::query("UPDATE object_deletions SET eligible_at=now()+interval '15 minutes' WHERE object_key=$1 AND eligible_at<=now()").bind(&key).execute(&app.pool).await?;
            continue;
        };
        let result = tokio::time::timeout(
            std::time::Duration::from_secs(120)
                .min(deadline.saturating_duration_since(tokio::time::Instant::now())),
            app.storage
                .delete(&object_store::path::Path::from(key.clone())),
        )
        .await;
        match result {
            Ok(Ok(())) | Ok(Err(object_store::Error::NotFound { .. })) => {
                sqlx::query("UPDATE object_deletions SET state='deleted',eligible_at=now()+interval '1 day',updated_at=now() WHERE object_key=$1 AND state='deleting'").bind(&key).execute(&app.pool).await?;
                count += 1;
                tracing::info!(ambiguous_write = ambiguous, "object cleanup completed");
            }
            Ok(Err(e)) => return Err(crate::storage::error(e)),
            Err(_) => {
                return Err(ApiError(
                    axum::http::StatusCode::SERVICE_UNAVAILABLE,
                    "DEPENDENCY_UNAVAILABLE",
                    "object cleanup timed out",
                ));
            }
        }
    }
    Ok(count)
}
