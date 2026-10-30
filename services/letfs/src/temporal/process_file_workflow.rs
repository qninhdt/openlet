use std::time::Duration;
use temporalio_common::{ActivityCloseTimeouts, ActivityDefinition};
use temporalio_macros::{workflow, workflow_methods};
use temporalio_sdk::{ActivityOptions, WorkflowContext, WorkflowResult};
use uuid::Uuid;

pub const PROCESSING_QUEUE: &str = "openlet-letfs-processing";
struct ProcessFileActivity;
impl ActivityDefinition for ProcessFileActivity {
    type Input = Uuid;
    type Output = Uuid;
    fn name(&self) -> &str {
        "process_file"
    }
}
#[workflow]
#[derive(Default)]
pub struct ProcessFile;
#[workflow_methods]
impl ProcessFile {
    #[run]
    pub async fn run(ctx: &mut WorkflowContext<Self>, operation: Uuid) -> WorkflowResult<Uuid> {
        let options =
            ActivityOptions::with_close_timeouts(ActivityCloseTimeouts::ScheduleAndStartToClose {
                schedule_to_close: Duration::from_secs(7200),
                start_to_close: Duration::from_secs(1800),
            })
            .task_queue(PROCESSING_QUEUE.to_owned())
            .heartbeat_timeout(Duration::from_secs(30))
            .retry_policy(
                temporalio_common::protos::temporal::api::common::v1::RetryPolicy {
                    maximum_attempts: 3,
                    ..Default::default()
                },
            )
            .build();
        Ok(ctx
            .execute_activity(ProcessFileActivity, operation, options)
            .await?)
    }
}
pub async fn dispatch(app: &crate::http::App, op: Uuid) -> Result<(), crate::http::ApiError> {
    use temporalio_client::errors::WorkflowStartError;
    use temporalio_client::{
        WorkflowIdConflictPolicy, WorkflowIdReusePolicy, WorkflowStartOptions,
    };
    let result = tokio::time::timeout(
        Duration::from_secs(3),
        app.temporal.start_workflow(
            ProcessFile::run,
            op,
            WorkflowStartOptions::new(super::QUEUE, format!("process-file/{op}"))
                .id_conflict_policy(WorkflowIdConflictPolicy::UseExisting)
                .id_reuse_policy(WorkflowIdReusePolicy::RejectDuplicate)
                .execution_timeout(Duration::from_secs(7500))
                .build(),
        ),
    )
    .await;
    match result {
        Ok(Ok(_)) | Ok(Err(WorkflowStartError::AlreadyStarted { .. })) => {}
        _ => {
            return Err(crate::http::ApiError(
                axum::http::StatusCode::SERVICE_UNAVAILABLE,
                "DEPENDENCY_UNAVAILABLE",
                "processing dispatch unavailable",
            ));
        }
    }
    sqlx::query("UPDATE operations SET workflow_started_at=coalesce(workflow_started_at,now()),updated_at=now() WHERE id=$1 AND kind='process-file'")
        .bind(op).execute(&app.pool).await?;
    Ok(())
}
