use super::{activity_error, with_heartbeat};
use crate::{
    fs::exports,
    http::{ApiError, App},
};
use std::{sync::Arc, time::Duration};
use temporalio_macros::{activities, workflow, workflow_methods};
use temporalio_sdk::{
    ActivityOptions, ApplicationFailure, WorkflowContext, WorkflowResult,
    activities::{ActivityContext, ActivityError},
};
use uuid::Uuid;

fn terminal_error(error: &ApiError) -> bool {
    error.0.is_client_error() && error.1 != "SOURCE_CHANGED"
}

fn export_error(error: ApiError) -> ActivityError {
    ActivityError::application(
        ApplicationFailure::builder(std::io::Error::other(error.1))
            .type_name(error.1.to_owned())
            .non_retryable(terminal_error(&error))
            .build(),
    )
}

pub struct ArchiveActivities {
    pub app: App,
}
#[activities]
impl ArchiveActivities {
    #[activity]
    pub async fn export_archive(
        self: Arc<Self>,
        ctx: ActivityContext,
        start: exports::Start,
    ) -> Result<Uuid, ActivityError> {
        let generation = i32::try_from(ctx.info().attempt)
            .map_err(|_| activity_error(ApiError::bad("invalid export attempt")))?;
        let id = Uuid::now_v7();
        let work = async {
            let Some(attempt) = exports::prepare(&self.app, &start, generation, id).await? else {
                return Ok(start.selection.request_key);
            };
            let result = tokio::time::timeout(
                Duration::from_secs(self.app.config.exports.runtime_seconds as u64),
                async {
                    let size = crate::storage::archive::build(&self.app, &attempt).await?;
                    exports::publish(&self.app, &attempt, size).await
                },
            )
            .await
            .unwrap_or(Err(ApiError::state("RESOURCE_LIMIT")));
            if let Err(error) = &result {
                tracing::warn!(code=error.1,operation=%attempt.operation,"archive attempt failed");
                if terminal_error(error) {
                    sqlx::query("UPDATE operations SET state='failed',error_code=$3,updated_at=now() WHERE id=$1 AND attempt_id=$2 AND state='running'")
                        .bind(attempt.operation).bind(attempt.id).bind(error.1).execute(&self.app.pool).await?;
                }
            }
            result?;
            Ok(start.selection.request_key)
        };
        tokio::select! {
            result = with_heartbeat(ctx.clone(),work,start.selection.request_key,export_error) => result,
            _ = ctx.cancelled() => Err(ActivityError::cancelled()),
        }
    }
}
#[workflow]
#[derive(Default)]
pub struct ExportArchive;
#[workflow_methods]
impl ExportArchive {
    #[run]
    pub async fn run(
        ctx: &mut WorkflowContext<Self>,
        start: exports::Start,
    ) -> WorkflowResult<Uuid> {
        let options = ActivityOptions::with_close_timeouts(
            temporalio_common::ActivityCloseTimeouts::ScheduleAndStartToClose {
                schedule_to_close: Duration::from_secs(7200),
                start_to_close: Duration::from_secs(1900),
            },
        )
        .heartbeat_timeout(Duration::from_secs(30))
        .retry_policy(
            temporalio_common::protos::temporal::api::common::v1::RetryPolicy {
                maximum_attempts: 3,
                ..Default::default()
            },
        )
        .build();
        Ok(ctx
            .execute_activity(ArchiveActivities::export_archive, start, options)
            .await?)
    }
}
pub fn workflow_id(start: &exports::Start) -> String {
    format!(
        "export-archive/{}/{}/{}",
        start.filesystem_id, start.scope.actor_id, start.selection.request_key
    )
}
pub async fn start(
    app: &App,
    start: exports::Start,
) -> Result<(axum::http::StatusCode, serde_json::Value), ApiError> {
    use temporalio_client::{
        WorkflowIdConflictPolicy, WorkflowIdReusePolicy, WorkflowStartOptions,
    };
    let id = workflow_id(&start);
    if let Some(value) = exports::existing(app, &start).await? {
        return Ok((axum::http::StatusCode::OK, value));
    }
    exports::preflight(app, &start).await?;
    super::retained_input(app, &id, serde_json::json!(start)).await?;
    app.temporal
        .start_workflow(
            ExportArchive::run,
            start.clone(),
            WorkflowStartOptions::new(super::QUEUE, &id)
                .id_conflict_policy(WorkflowIdConflictPolicy::UseExisting)
                .id_reuse_policy(WorkflowIdReusePolicy::AllowDuplicate)
                .execution_timeout(Duration::from_secs(7500))
                .build(),
        )
        .await
        .map_err(|_| {
            ApiError(
                axum::http::StatusCode::SERVICE_UNAVAILABLE,
                "DEPENDENCY_UNAVAILABLE",
                "Temporal unavailable",
            )
        })?;
    let wait = async {
        loop {
            if let Some(value) = exports::existing(app, &start).await? {
                return Ok((axum::http::StatusCode::ACCEPTED, value));
            }
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
    };
    match tokio::time::timeout(Duration::from_secs(2), wait).await {
        Ok(result) => result,
        Err(_) => Err(super::admission_error(app, &id).await),
    }
}
