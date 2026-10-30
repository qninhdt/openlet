use super::{activity_error, with_heartbeat};
use crate::{fs::copy, http::App};
use serde::{Deserialize, Serialize};
use std::{sync::Arc, time::Duration};
use temporalio_macros::{activities, workflow, workflow_methods};
use temporalio_sdk::{
    ActivityExecutionError, ActivityOptions, ApplicationFailure, ContinueAsNewOptions,
    WorkflowCancellationToken, WorkflowContext, WorkflowResult,
    activities::{ActivityContext, ActivityError},
};
use uuid::Uuid;

pub struct StorageActivities {
    pub app: App,
}
#[derive(Serialize, Deserialize)]
pub struct Discard {
    pub operation_id: Uuid,
    pub code: String,
}
#[activities]
impl StorageActivities {
    #[activity]
    pub async fn prepare_copy(
        self: Arc<Self>,
        _ctx: ActivityContext,
        start: copy::Start,
    ) -> Result<Uuid, ActivityError> {
        copy::prepare(&self.app, start)
            .await
            .map_err(activity_error)
    }
    #[activity]
    pub async fn copy_batch(
        self: Arc<Self>,
        ctx: ActivityContext,
        op: Uuid,
    ) -> Result<bool, ActivityError> {
        with_heartbeat(ctx, copy::batch(&self.app, op), op, activity_error).await
    }
    #[activity]
    pub async fn publish_copy(
        self: Arc<Self>,
        _ctx: ActivityContext,
        op: Uuid,
    ) -> Result<(), ActivityError> {
        copy::publish(&self.app, op).await.map_err(activity_error)
    }
    #[activity]
    pub async fn mark_copy_discarding(
        self: Arc<Self>,
        _ctx: ActivityContext,
        input: Discard,
    ) -> Result<(), ActivityError> {
        copy::mark_discarding(&self.app, input.operation_id, &input.code)
            .await
            .map_err(activity_error)
    }
    #[activity]
    pub async fn discard_copy_batch(
        self: Arc<Self>,
        _ctx: ActivityContext,
        op: Uuid,
    ) -> Result<bool, ActivityError> {
        copy::discard_batch(&self.app, op)
            .await
            .map_err(activity_error)
    }
}
fn error_code(e: &ActivityExecutionError) -> String {
    if let Some(temporalio_common::error::IncomingError::Application(app)) = e.cause() {
        app.type_name().unwrap_or("COPY_FAILED").to_owned()
    } else {
        "COPY_FAILED".into()
    }
}
#[workflow]
#[derive(Default)]
pub struct CopyNode;
#[workflow_methods]
impl CopyNode {
    #[run]
    pub async fn run(
        ctx: &mut WorkflowContext<Self>,
        input: copy::Continue,
    ) -> WorkflowResult<Uuid> {
        let short = ActivityOptions::start_to_close_timeout(Duration::from_secs(30));
        let op = if let Some(id) = input.operation_id {
            id
        } else {
            let start = input
                .start
                .ok_or_else(|| ApplicationFailure::non_retryable("copy input required"))?;
            ctx.execute_activity(StorageActivities::prepare_copy, start, short.clone())
                .await?
        };
        let batch_options = ActivityOptions::with_start_to_close_timeout(Duration::from_secs(180))
            .heartbeat_timeout(Duration::from_secs(30))
            .build();
        let mut failure = None;
        for _ in 0..200 {
            match ctx
                .execute_activity(StorageActivities::copy_batch, op, batch_options.clone())
                .await
            {
                Ok(false) => {}
                Ok(true) => {
                    match ctx
                        .execute_activity(StorageActivities::publish_copy, op, short.clone())
                        .await
                    {
                        Ok(()) => return Ok(op),
                        Err(e) => {
                            failure = Some(e);
                            break;
                        }
                    }
                }
                Err(e) => {
                    failure = Some(e);
                    break;
                }
            }
        }
        let Some(error) = failure else {
            return ctx
                .continue_as_new(
                    copy::Continue {
                        operation_id: Some(op),
                        start: None,
                    },
                    ContinueAsNewOptions::default(),
                )
                .map(|never| match never {});
        };
        let shielded = ActivityOptions::with_start_to_close_timeout(Duration::from_secs(30))
            .cancellation_token(WorkflowCancellationToken::new())
            .build();
        ctx.execute_activity(
            StorageActivities::mark_copy_discarding,
            Discard {
                operation_id: op,
                code: error_code(&error),
            },
            shielded.clone(),
        )
        .await?;
        for _ in 0..200 {
            if ctx
                .execute_activity(StorageActivities::discard_copy_batch, op, shielded.clone())
                .await?
            {
                return Err(error.into());
            }
        }
        ctx.continue_as_new(
            copy::Continue {
                operation_id: Some(op),
                start: None,
            },
            ContinueAsNewOptions::default(),
        )
        .map(|never| match never {})
    }
}
