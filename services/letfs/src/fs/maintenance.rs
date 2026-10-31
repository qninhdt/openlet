use crate::http::{ApiError, App};
use object_store::ObjectStoreExt;
use sqlx::Row;
use uuid::Uuid;

pub async fn expire_uploads(app: &App) -> Result<u32, ApiError> {
    let rows=sqlx::query("SELECT id,filesystem_id FROM uploads WHERE state IN ('created','transferring','uploaded') AND expires_at<=now() ORDER BY expires_at,id LIMIT 64").fetch_all(&app.pool).await?;
    let count = rows.len() as u32;
    for row in rows {
        super::uploads::expire(app, row.get("filesystem_id"), row.get("id")).await?;
    }
    let rows=sqlx::query("SELECT id,candidate_key,multipart_id FROM uploads WHERE state IN ('aborted','expired') AND multipart_id IS NOT NULL ORDER BY updated_at,id LIMIT 64").fetch_all(&app.pool).await?;
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
pub async fn discard_copies(app: &App) -> Result<u32, ApiError> {
    use temporalio_common::protos::temporal::api::{
        common::v1::WorkflowExecution, enums::v1::WorkflowExecutionStatus,
        workflowservice::v1::DescribeWorkflowExecutionRequest,
    };
    let rows=sqlx::query("SELECT o.id,o.filesystem_id,o.actor_id,o.request_key,o.state FROM operations o WHERE o.kind='copy' AND o.durable AND o.state IN ('running','discarding') ORDER BY o.updated_at,o.id LIMIT 64").fetch_all(&app.pool).await?;
    let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(180);
    let mut count = super::artifacts::discard_forests(app).await?;
    count += super::processing::maintain(app).await?;
    match super::indexing::cleanup(app).await {
        Ok(cleaned) => count += cleaned,
        Err(_) => tracing::warn!("search index cleanup deferred"),
    }
    count += super::exports::maintain(app).await?;
    for row in rows {
        if tokio::time::Instant::now() >= deadline {
            break;
        }
        let id: Uuid = row.get("id");
        let discarding = row.get::<String, _>("state") == "discarding";
        let closed = if discarding {
            true
        } else {
            let workflow_id = format!(
                "copy/{}/{}/{}",
                row.get::<Uuid, _>("filesystem_id"),
                row.get::<Uuid, _>("actor_id"),
                row.get::<Uuid, _>("request_key")
            );
            let result = tokio::time::timeout(
                std::time::Duration::from_secs(3),
                app.temporal
                    .connection()
                    .workflow_service()
                    .describe_workflow_execution(temporalio_client::tonic::Request::new(
                        DescribeWorkflowExecutionRequest {
                            namespace: app.config.temporal_namespace.clone(),
                            execution: Some(WorkflowExecution {
                                workflow_id,
                                run_id: String::new(),
                            }),
                        },
                    )),
            )
            .await;
            sqlx::query("UPDATE operations SET updated_at=now() WHERE id=$1 AND state='running'")
                .bind(id)
                .execute(&app.pool)
                .await?;
            result
                .ok()
                .and_then(Result::ok)
                .and_then(|v| v.into_inner().workflow_execution_info)
                .is_some_and(|v| {
                    matches!(
                        WorkflowExecutionStatus::try_from(v.status),
                        Ok(WorkflowExecutionStatus::Completed
                            | WorkflowExecutionStatus::Failed
                            | WorkflowExecutionStatus::Canceled
                            | WorkflowExecutionStatus::Terminated
                            | WorkflowExecutionStatus::TimedOut)
                    )
                })
        };
        if closed {
            if !discarding {
                super::copy::mark_discarding(app, id, "WORKFLOW_CLOSED").await?;
            }
            super::copy::discard_batch(app, id).await?;
            count += 1;
        }
    }
    Ok(count)
}
pub async fn delete_objects(app: &App) -> Result<u32, ApiError> {
    let rows=sqlx::query("SELECT object_key,bucket_id FROM object_deletions WHERE eligible_at<=now() AND (state!='deleted' OR ambiguous_write) ORDER BY eligible_at,object_key LIMIT 64").fetch_all(&app.pool).await?;
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
        let claimed:Option<bool>=sqlx::query_scalar("UPDATE object_deletions d SET state='deleting',attempts=attempts+1,eligible_at=now()+interval '15 minutes',updated_at=now() WHERE d.object_key=$1 AND d.eligible_at<=now() AND (d.state!='deleted' OR d.ambiguous_write) AND NOT EXISTS(SELECT 1 FROM file_data WHERE object_key=d.object_key) AND NOT EXISTS(SELECT 1 FROM uploads WHERE candidate_key=d.object_key AND state IN ('created','transferring','uploaded')) AND NOT EXISTS(SELECT 1 FROM copy_items c JOIN operations o ON o.id=c.operation_id WHERE c.target_key=d.object_key AND o.state='running') AND NOT EXISTS(SELECT 1 FROM export_attempts a JOIN operations o ON o.id=a.operation_id WHERE a.object_key=d.object_key AND o.attempt_id=a.id AND ((o.state='running' AND a.deadline>now()) OR (o.state='succeeded' AND a.expires_at>now()))) RETURNING ambiguous_write")
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
