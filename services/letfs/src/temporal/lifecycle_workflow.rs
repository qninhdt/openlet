use super::{activity_error, with_heartbeat};
use crate::{
    fs::{deletion, maintenance},
    http::App,
};
use serde::{Deserialize, Serialize};
use std::{sync::Arc, time::Duration};
use temporalio_common::WorkflowDefinition;
use temporalio_macros::{activities, workflow, workflow_methods};
use temporalio_sdk::{
    ActivityOptions, ApplicationFailure, ContinueAsNewOptions, WorkflowCancellationToken,
    WorkflowContext, WorkflowResult,
    activities::{ActivityContext, ActivityError},
};
use temporalio_workflow::workflows::WorkflowImplementation;
use uuid::Uuid;

pub struct LifecycleActivities {
    pub app: App,
}

#[activities]
impl LifecycleActivities {
    #[activity]
    pub async fn begin_deletion(
        self: Arc<Self>,
        _ctx: ActivityContext,
        input: deletion::Start,
    ) -> Result<Uuid, ActivityError> {
        deletion::prepare(&self.app, input)
            .await
            .map_err(activity_error)
    }
    #[activity]
    pub async fn delete_nodes_batch(
        self: Arc<Self>,
        _ctx: ActivityContext,
        op: Uuid,
    ) -> Result<bool, ActivityError> {
        deletion::batch(&self.app, op).await.map_err(activity_error)
    }
    #[activity]
    pub async fn expire_uploads_batch(
        self: Arc<Self>,
        _ctx: ActivityContext,
        _: (),
    ) -> Result<u32, ActivityError> {
        maintenance::expire_uploads(&self.app)
            .await
            .map_err(activity_error)
    }
    #[activity]
    pub async fn discard_failed_copies_batch(
        self: Arc<Self>,
        ctx: ActivityContext,
        _: (),
    ) -> Result<u32, ActivityError> {
        with_heartbeat(
            ctx,
            maintenance::discard_copies(&self.app),
            (),
            activity_error,
        )
        .await
    }
    #[activity]
    pub async fn delete_objects_batch(
        self: Arc<Self>,
        ctx: ActivityContext,
        _: (),
    ) -> Result<u32, ActivityError> {
        with_heartbeat(
            ctx,
            maintenance::delete_objects(&self.app),
            (),
            activity_error,
        )
        .await
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Continue {
    pub operation_id: Option<Uuid>,
    pub start: Option<deletion::Start>,
}
async fn delete_nodes<W>(ctx: &mut WorkflowContext<W>, input: Continue) -> WorkflowResult<Uuid>
where
    W: WorkflowImplementation,
    W::Run: WorkflowDefinition<Input = Continue>,
{
    let options = ActivityOptions::with_start_to_close_timeout(Duration::from_secs(30))
        .cancellation_token(WorkflowCancellationToken::new())
        .build();
    let op = if let Some(op) = input.operation_id {
        op
    } else {
        ctx.execute_activity(
            LifecycleActivities::begin_deletion,
            input
                .start
                .ok_or_else(|| ApplicationFailure::non_retryable("deletion input required"))?,
            ActivityOptions::start_to_close_timeout(Duration::from_secs(30)),
        )
        .await?
    };
    for _ in 0..200 {
        if ctx
            .execute_activity(LifecycleActivities::delete_nodes_batch, op, options.clone())
            .await?
        {
            return Ok(op);
        }
    }
    ctx.continue_as_new(
        Continue {
            operation_id: Some(op),
            start: None,
        },
        ContinueAsNewOptions::default(),
    )
    .map(|v| match v {})
}
#[workflow]
#[derive(Default)]
pub struct PurgeTrash;
#[workflow_methods]
impl PurgeTrash {
    #[run]
    pub async fn run(ctx: &mut WorkflowContext<Self>, input: Continue) -> WorkflowResult<Uuid> {
        delete_nodes(ctx, input).await
    }
}
#[workflow]
#[derive(Default)]
pub struct DeleteFilesystem;
#[workflow_methods]
impl DeleteFilesystem {
    #[run]
    pub async fn run(ctx: &mut WorkflowContext<Self>, input: Continue) -> WorkflowResult<Uuid> {
        delete_nodes(ctx, input).await
    }
}
#[workflow]
#[derive(Default)]
pub struct StorageMaintenance;
#[workflow_methods]
impl StorageMaintenance {
    #[run]
    pub async fn run(ctx: &mut WorkflowContext<Self>, _: ()) -> WorkflowResult<()> {
        let short = ActivityOptions::with_start_to_close_timeout(Duration::from_secs(30))
            .retry_policy(
                temporalio_common::protos::temporal::api::common::v1::RetryPolicy {
                    maximum_attempts: 3,
                    ..Default::default()
                },
            )
            .build();
        let bounded = ActivityOptions::with_start_to_close_timeout(Duration::from_secs(240))
            .heartbeat_timeout(Duration::from_secs(30))
            .retry_policy(
                temporalio_common::protos::temporal::api::common::v1::RetryPolicy {
                    maximum_attempts: 3,
                    ..Default::default()
                },
            )
            .build();
        ctx.execute_activity(LifecycleActivities::expire_uploads_batch, (), short)
            .await?;
        ctx.execute_activity(
            LifecycleActivities::discard_failed_copies_batch,
            (),
            bounded.clone(),
        )
        .await?;
        ctx.execute_activity(LifecycleActivities::delete_objects_batch, (), bounded)
            .await?;
        Ok(())
    }
}
pub async fn ensure_schedule(app: &App) -> Result<(), String> {
    use temporalio_client::schedules::{
        CreateScheduleOptions, ScheduleAction, ScheduleOverlapPolicy, ScheduleSpec,
    };
    let result = app
        .temporal
        .create_schedule(
            "openlet-storage-maintenance",
            CreateScheduleOptions::builder()
                .action(ScheduleAction::start_workflow(
                    StorageMaintenance::run,
                    (),
                    super::QUEUE,
                    "storage-maintenance",
                ))
                .spec(ScheduleSpec::from_interval(Duration::from_secs(300)))
                .overlap_policy(ScheduleOverlapPolicy::Skip)
                .build(),
        )
        .await;
    match result {
        Ok(_) => Ok(()),
        Err(temporalio_client::schedules::ScheduleError::Rpc(e))
            if e.code() == temporalio_client::tonic::Code::AlreadyExists =>
        {
            Ok(())
        }
        Err(_) => Err("maintenance schedule unavailable".into()),
    }
}
