use super::{activity_error, with_heartbeat};
use crate::{fs::copy, http::App};
use serde::{Deserialize, Serialize};
use std::{sync::Arc, time::Duration};
use temporalio_macros::{activities, workflow, workflow_methods};
use temporalio_sdk::{
    ActivityExecutionError, ActivityOptions, ContinueAsNewOptions, WorkflowContext,
    WorkflowContextView, WorkflowResult,
    activities::{ActivityContext, ActivityError},
};
use uuid::Uuid;

pub struct StorageActivities {
    pub app: App,
}
#[activities]
impl StorageActivities {
    #[activity]
    pub async fn copy_item(
        self: Arc<Self>,
        ctx: ActivityContext,
        step: copy::Step,
    ) -> Result<(), ActivityError> {
        with_heartbeat(ctx, copy::commit_item(&self.app, step), (), activity_error).await
    }
    #[activity]
    pub async fn next_copy_item(
        self: Arc<Self>,
        _ctx: ActivityContext,
        input: copy::Next,
    ) -> Result<Option<copy::Item>, ActivityError> {
        copy::next(&self.app, input).await.map_err(activity_error)
    }
    #[activity]
    pub async fn finish_copy_file(
        self: Arc<Self>,
        _ctx: ActivityContext,
        input: copy::Next,
    ) -> Result<(), ActivityError> {
        copy::finish_file(&self.app, input)
            .await
            .map_err(activity_error)
    }
    #[activity]
    pub async fn complete_copy(
        self: Arc<Self>,
        _ctx: ActivityContext,
        admission: copy::Admission,
    ) -> Result<(), ActivityError> {
        copy::complete(&self.app, &admission)
            .await
            .map_err(activity_error)
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct State {
    pub admission: copy::Admission,
    pub frames: Vec<copy::Frame>,
    pub pending: Option<copy::Item>,
    pub committed_nodes: i64,
    pub committed_bytes: i64,
    pub status: String,
    pub error_code: Option<String>,
}
impl State {
    pub fn new(admission: copy::Admission) -> Self {
        Self {
            pending: Some(admission.root.clone()),
            admission,
            frames: vec![],
            committed_nodes: 0,
            committed_bytes: 0,
            status: "running".into(),
            error_code: None,
        }
    }
    pub fn value(&self) -> serde_json::Value {
        serde_json::json!({"id":self.admission.id,"destination_root_id":self.admission.root.destination,"status":self.status,"committed_nodes":self.committed_nodes.to_string(),"committed_bytes":self.committed_bytes.to_string(),"error_code":self.error_code})
    }
}
fn error_code(error: &ActivityExecutionError) -> String {
    if let Some(temporalio_common::error::IncomingError::Application(failure)) = error.cause() {
        failure.type_name().unwrap_or("COPY_FAILED").into()
    } else {
        "COPY_FAILED".into()
    }
}
#[workflow]
#[derive(Default)]
pub struct CopyNode {
    state: Option<State>,
}
#[workflow_methods]
impl CopyNode {
    #[query]
    pub fn progress(&self, _ctx: &WorkflowContextView) -> Option<State> {
        self.state.clone()
    }
    #[run]
    pub async fn run(ctx: &mut WorkflowContext<Self>, mut state: State) -> WorkflowResult<State> {
        let short = ActivityOptions::with_start_to_close_timeout(Duration::from_secs(30))
            .retry_policy(
                temporalio_common::protos::temporal::api::common::v1::RetryPolicy {
                    maximum_attempts: 3,
                    ..Default::default()
                },
            )
            .build();
        let storage = ActivityOptions::with_start_to_close_timeout(Duration::from_secs(150))
            .heartbeat_timeout(Duration::from_secs(30))
            .retry_policy(
                temporalio_common::protos::temporal::api::common::v1::RetryPolicy {
                    maximum_attempts: 3,
                    ..Default::default()
                },
            )
            .build();
        ctx.state_mut(|s| s.state = Some(state.clone()));
        for _ in 0..100 {
            if state.status != "running" {
                break;
            }
            let result = if let Some(item) = state.pending.clone() {
                if state.committed_nodes >= state.admission.max_nodes
                    || item.size > state.admission.max_bytes - state.committed_bytes
                {
                    state.status = "failed".into();
                    state.error_code = Some("RESOURCE_LIMIT".into());
                    break;
                }
                ctx.execute_activity(
                    StorageActivities::copy_item,
                    copy::Step {
                        admission: state.admission.clone(),
                        item: item.clone(),
                    },
                    storage.clone(),
                )
                .await
                .map(|()| {
                    state.committed_nodes += 1;
                    state.committed_bytes += item.size;
                    state.pending = None;
                    if let Some(parent) = state.frames.last_mut() {
                        parent.after = item.source;
                        parent.revision = (item
                            .parent_revision
                            .parse::<i64>()
                            .expect("captured revision")
                            + 1)
                        .to_string();
                    }
                    state.frames.push(copy::Frame {
                        item,
                        after: Uuid::nil(),
                        revision: "1".into(),
                    });
                })
            } else if let Some(frame) = state.frames.last().cloned() {
                let input = copy::Next {
                    admission: state.admission.clone(),
                    frame,
                };
                match ctx
                    .execute_activity(
                        StorageActivities::next_copy_item,
                        input.clone(),
                        short.clone(),
                    )
                    .await
                {
                    Ok(Some(item)) => {
                        state.pending = Some(item);
                        Ok(())
                    }
                    Ok(None) => ctx
                        .execute_activity(StorageActivities::finish_copy_file, input, short.clone())
                        .await
                        .map(|()| {
                            state.frames.pop();
                        }),
                    Err(e) => Err(e),
                }
            } else {
                state.status = "succeeded".into();
                Ok(())
            };
            if let Err(e) = result {
                state.status = "failed".into();
                state.error_code = Some(error_code(&e));
            }
            ctx.state_mut(|s| s.state = Some(state.clone()));
        }
        ctx.state_mut(|s| s.state = Some(state.clone()));
        if state.status == "running" {
            return ctx
                .continue_as_new(state, ContinueAsNewOptions::default())
                .map(|never| match never {});
        }
        ctx.execute_activity(
            StorageActivities::complete_copy,
            state.admission.clone(),
            short,
        )
        .await?;
        Ok(state)
    }
}

pub async fn monitor(
    app: &App,
    fs: Uuid,
    id: Uuid,
    actor: Uuid,
    owner: bool,
) -> Result<serde_json::Value, crate::http::ApiError> {
    use crate::http::ApiError;
    use temporalio_client::WorkflowQueryOptions;
    use temporalio_common::protos::temporal::api::{
        common::v1::WorkflowExecution,
        enums::v1::WorkflowExecutionStatus,
        history::v1::history_event::Attributes,
        workflowservice::v1::{
            DescribeWorkflowExecutionRequest, GetWorkflowExecutionHistoryRequest,
        },
    };
    let workflow_id = format!("copy/{fs}/{id}");
    let execution = WorkflowExecution {
        workflow_id: workflow_id.clone(),
        run_id: String::new(),
    };
    let history = app
        .temporal
        .connection()
        .workflow_service()
        .get_workflow_execution_history(temporalio_client::tonic::Request::new(
            GetWorkflowExecutionHistoryRequest {
                namespace: app.config.temporal_namespace.clone(),
                execution: Some(execution.clone()),
                maximum_page_size: 1,
                ..Default::default()
            },
        ))
        .await
        .map_err(|e| {
            if e.code() == temporalio_client::tonic::Code::NotFound {
                ApiError(
                    axum::http::StatusCode::GONE,
                    "COPY_EXPIRED",
                    "copy history unavailable",
                )
            } else {
                ApiError(
                    axum::http::StatusCode::SERVICE_UNAVAILABLE,
                    "DEPENDENCY_UNAVAILABLE",
                    "Temporal unavailable",
                )
            }
        })?
        .into_inner();
    let initial = history
        .history
        .and_then(|h| h.events.into_iter().next())
        .and_then(|e| match e.attributes {
            Some(Attributes::WorkflowExecutionStartedEventAttributes(a)) => {
                a.input.and_then(|p| p.payloads.into_iter().next())
            }
            _ => None,
        })
        .ok_or_else(ApiError::not_found)?;
    let initial: State =
        serde_json::from_slice(&initial.data).map_err(|_| ApiError::not_found())?;
    if initial.admission.filesystem_id != fs
        || initial.admission.id != id
        || (initial.admission.actor_id != actor && !owner)
    {
        return Err(ApiError::not_found());
    }
    let unavailable = || {
        ApiError(
            axum::http::StatusCode::SERVICE_UNAVAILABLE,
            "DEPENDENCY_UNAVAILABLE",
            "copy progress unavailable",
        )
    };
    let handle = app.temporal.get_workflow_handle::<CopyNode>(workflow_id);
    let mut state = handle
        .query(CopyNode::progress, (), WorkflowQueryOptions::default())
        .await
        .map_err(|_| unavailable())?
        .ok_or_else(unavailable)?;
    let info = app
        .temporal
        .connection()
        .workflow_service()
        .describe_workflow_execution(temporalio_client::tonic::Request::new(
            DescribeWorkflowExecutionRequest {
                namespace: app.config.temporal_namespace.clone(),
                execution: Some(execution),
            },
        ))
        .await
        .map_err(|_| unavailable())?
        .into_inner()
        .workflow_execution_info
        .ok_or_else(unavailable)?;
    if matches!(
        WorkflowExecutionStatus::try_from(info.status),
        Ok(WorkflowExecutionStatus::Failed
            | WorkflowExecutionStatus::Canceled
            | WorkflowExecutionStatus::Terminated
            | WorkflowExecutionStatus::TimedOut)
    ) {
        state.status = "failed".into();
        state.error_code = Some("COPY_FAILED".into());
    }
    Ok(state.value())
}
