use std::time::Duration;
use temporalio_common::{ActivityCloseTimeouts, ActivityDefinition};
use temporalio_macros::{workflow, workflow_methods};
use temporalio_sdk::{ActivityOptions, WorkflowContext, WorkflowResult};
use uuid::Uuid;

pub const PROCESSING_QUEUE: &str = "openlet-letfs-processing";
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Input {
    pub operation_id: Uuid,
    pub parse_required: bool,
    pub enrichment_required: bool,
}
struct ProcessFileActivity(&'static str);
impl ActivityDefinition for ProcessFileActivity {
    type Input = Uuid;
    type Output = Uuid;
    fn name(&self) -> &str {
        self.0
    }
}
#[workflow]
#[derive(Default)]
pub struct ProcessFile;
#[workflow_methods]
impl ProcessFile {
    #[run]
    pub async fn run(ctx: &mut WorkflowContext<Self>, input: Input) -> WorkflowResult<Uuid> {
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
        if input.parse_required {
            ctx.execute_activity(
                ProcessFileActivity("process_file"),
                input.operation_id,
                options.clone(),
            )
            .await?;
        }
        if input.enrichment_required {
            ctx.execute_activity(
                ProcessFileActivity("enrich_file"),
                input.operation_id,
                options.clone(),
            )
            .await?;
        }
        Ok(ctx
            .execute_activity(
                ProcessFileActivity("index_file"),
                input.operation_id,
                options,
            )
            .await?)
    }
}
pub async fn dispatch(app: &crate::http::App, op: Uuid) -> Result<(), crate::http::ApiError> {
    use sqlx::Row;
    use temporalio_client::errors::WorkflowStartError;
    use temporalio_client::{
        WorkflowIdConflictPolicy, WorkflowIdReusePolicy, WorkflowStartOptions,
    };
    let row = sqlx::query("SELECT state,enrichment_state,index_state FROM operations WHERE id=$1 AND kind='process-file' AND superseded_at IS NULL")
        .bind(op).fetch_optional(&app.pool).await?.ok_or_else(crate::http::ApiError::not_found)?;
    if row.get::<&str, _>("index_state") == "succeeded" {
        return Ok(());
    }
    let input = Input {
        operation_id: op,
        parse_required: row.get::<&str, _>("state") != "succeeded",
        enrichment_required: row.get::<&str, _>("enrichment_state") != "succeeded",
    };
    let result = tokio::time::timeout(
        Duration::from_secs(3),
        app.temporal.start_workflow(
            ProcessFile::run,
            input,
            WorkflowStartOptions::new(super::QUEUE, format!("process-file/{op}"))
                .id_conflict_policy(WorkflowIdConflictPolicy::UseExisting)
                .id_reuse_policy(WorkflowIdReusePolicy::AllowDuplicate)
                .execution_timeout(Duration::from_secs(22500))
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
