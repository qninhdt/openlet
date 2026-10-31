use crate::fs::processing::Generation;
use std::time::Duration;
use temporalio_common::{ActivityCloseTimeouts, ActivityDefinition};
use temporalio_macros::{workflow, workflow_methods};
use temporalio_sdk::{ActivityOptions, WorkflowContext, WorkflowResult};

pub const CPU_QUEUE: &str = "openlet-letfs-cpu";
pub const IO_QUEUE: &str = "openlet-letfs-io";
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Input {
    pub source: Generation,
    pub parse_required: bool,
    pub enrichment_required: bool,
}
struct ProcessFileActivity(&'static str);
impl ActivityDefinition for ProcessFileActivity {
    type Input = Generation;
    type Output = Generation;
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
    pub async fn run(ctx: &mut WorkflowContext<Self>, input: Input) -> WorkflowResult<Generation> {
        let options =
            ActivityOptions::with_close_timeouts(ActivityCloseTimeouts::ScheduleAndStartToClose {
                schedule_to_close: Duration::from_secs(7200),
                start_to_close: Duration::from_secs(1800),
            })
            .task_queue(IO_QUEUE.to_owned())
            .heartbeat_timeout(Duration::from_secs(30))
            .retry_policy(
                temporalio_common::protos::temporal::api::common::v1::RetryPolicy {
                    maximum_attempts: 3,
                    ..Default::default()
                },
            )
            .build();
        if input.parse_required {
            let mut cpu = options.clone();
            cpu.task_queue = Some(CPU_QUEUE.to_owned());
            ctx.execute_activity(ProcessFileActivity("process_file"), input.source, cpu)
                .await?;
        }
        if input.enrichment_required {
            ctx.execute_activity(
                ProcessFileActivity("enrich_file"),
                input.source,
                options.clone(),
            )
            .await?;
        }
        Ok(ctx
            .execute_activity(ProcessFileActivity("index_file"), input.source, options)
            .await?)
    }
}
pub fn index_workflow_id(
    source: Generation,
    space: &crate::fs::indexing::VectorSpace,
) -> Result<String, crate::http::ApiError> {
    Ok(format!(
        "index-file/{}/{}/{}",
        source.file_id,
        source.generation,
        crate::fs::processing::hash(space)?
    ))
}
pub async fn dispatch(
    app: &crate::http::App,
    source: Generation,
) -> Result<(), crate::http::ApiError> {
    use sqlx::Row;
    use temporalio_client::errors::WorkflowStartError;
    use temporalio_client::{
        WorkflowIdConflictPolicy, WorkflowIdReusePolicy, WorkflowStartOptions,
    };
    let row=sqlx::query("SELECT publication_status,index_status FROM files WHERE node_id=$1 AND desired_generation=$2")
        .bind(source.file_id).bind(source.generation).fetch_optional(&app.pool).await?.ok_or_else(crate::http::ApiError::not_found)?;
    let publication = row.get::<&str, _>("publication_status");
    if !matches!(publication, "pending" | "parsed" | "ready")
        || row.get::<&str, _>("index_status") != "pending"
    {
        return Ok(());
    }
    let index_only = publication == "ready";
    if index_only && crate::fs::processing::workflow_running(app, source).await? {
        return Ok(());
    }
    let workflow_id = if index_only {
        index_workflow_id(source, &crate::fs::indexing::VectorSpace::configured(app))?
    } else {
        source.workflow_id()
    };
    let input = Input {
        source,
        parse_required: publication == "pending",
        enrichment_required: publication != "ready",
    };
    let result = tokio::time::timeout(
        Duration::from_secs(3),
        app.temporal.start_workflow(
            ProcessFile::run,
            input,
            WorkflowStartOptions::new(super::QUEUE, workflow_id)
                .id_conflict_policy(WorkflowIdConflictPolicy::UseExisting)
                .id_reuse_policy(if index_only {
                    WorkflowIdReusePolicy::AllowDuplicate
                } else {
                    WorkflowIdReusePolicy::RejectDuplicate
                })
                .execution_timeout(Duration::from_secs(22500))
                .build(),
        ),
    )
    .await;
    match result {
        Ok(Ok(_)) | Ok(Err(WorkflowStartError::AlreadyStarted { .. })) => Ok(()),
        _ => Err(crate::http::ApiError(
            axum::http::StatusCode::SERVICE_UNAVAILABLE,
            "DEPENDENCY_UNAVAILABLE",
            "processing dispatch unavailable",
        )),
    }
}
