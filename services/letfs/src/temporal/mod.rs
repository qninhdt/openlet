pub mod copy_workflow;
pub mod export_archive_workflow;
pub mod lifecycle_workflow;
pub mod process_file_workflow;
pub const QUEUE: &str = "openlet-letfs";
use crate::config::Config;
use crate::http::{ApiError, App};
use std::{future::Future, time::Duration};
use temporalio_client::{Connection, ConnectionOptions};
use temporalio_common::data_converters::TemporalSerializable;
use temporalio_common::protos::temporal::api::workflowservice::v1::DescribeNamespaceRequest;
use temporalio_sdk::{
    ApplicationFailure,
    activities::{ActivityContext, ActivityError},
};

fn activity_error(e: ApiError) -> ActivityError {
    let failure = ApplicationFailure::builder(std::io::Error::other(e.1))
        .type_name(e.1.to_owned())
        .non_retryable(e.0.is_client_error())
        .build();
    ActivityError::application(failure)
}

async fn with_heartbeat<T>(
    ctx: ActivityContext,
    work: impl Future<Output = Result<T, ApiError>>,
    details: impl TemporalSerializable + Clone + 'static,
    map_error: fn(ApiError) -> ActivityError,
) -> Result<T, ActivityError> {
    tokio::pin!(work);
    let mut timer = tokio::time::interval(Duration::from_secs(10));
    loop {
        tokio::select! {
            result = &mut work => return result.map_err(map_error),
            _ = timer.tick() => {
                ctx.record_heartbeat(details.clone()).await.map_err(|_| {
                    ActivityError::application(ApplicationFailure::new("heartbeat unavailable"))
                })?;
            }
        }
    }
}

pub async fn check(app: &App) -> Result<(), ()> {
    tokio::time::timeout(std::time::Duration::from_secs(3), async {
        app.temporal
            .connection()
            .workflow_service()
            .describe_namespace(temporalio_client::tonic::Request::new(
                DescribeNamespaceRequest {
                    namespace: app.config.temporal_namespace.clone(),
                    ..Default::default()
                },
            ))
            .await
            .map_err(|_| ())?;
        Ok(())
    })
    .await
    .map_err(|_| ())?
}

pub async fn client(config: &Config) -> Result<temporalio_client::Client, String> {
    let options = ConnectionOptions::new(
        url::Url::parse(&config.temporal_address).map_err(|_| "invalid Temporal URL")?,
    )
    .build();
    let connection = Connection::connect(options)
        .await
        .map_err(|_| "Temporal unavailable")?;
    temporalio_client::Client::new(
        connection,
        temporalio_client::ClientOptions::new(&config.temporal_namespace).build(),
    )
    .map_err(|_| "Temporal client configuration rejected".into())
}

pub async fn start_copy(
    app: &crate::http::App,
    start: crate::fs::copy::Start,
) -> Result<(axum::http::StatusCode, serde_json::Value), crate::http::ApiError> {
    use crate::{fs::copy, http::ApiError};
    use temporalio_client::{
        WorkflowIdConflictPolicy, WorkflowIdReusePolicy, WorkflowStartOptions,
    };
    use temporalio_common::protos::temporal::api::{
        common::v1::WorkflowExecution, history::v1::history_event::Attributes,
        workflowservice::v1::GetWorkflowExecutionHistoryRequest,
    };
    let key = crate::fs::nodes::needed(start.request.input.request_key)?;
    if key.is_nil() || start.request.input.text.is_some() || start.request.input.locators.is_some()
    {
        return Err(ApiError::bad("invalid copy input"));
    }
    if let Some(v) = copy::existing(app, &start).await? {
        return Ok((
            if v["state"] == "running" {
                axum::http::StatusCode::ACCEPTED
            } else {
                axum::http::StatusCode::OK
            },
            v,
        ));
    }
    copy::preflight(app, &start).await?;
    let id = format!(
        "copy/{}/{}/{}",
        start.filesystem_id, start.request.scope.actor_id, key
    );
    let history = app
        .temporal
        .connection()
        .workflow_service()
        .get_workflow_execution_history(temporalio_client::tonic::Request::new(
            GetWorkflowExecutionHistoryRequest {
                namespace: app.config.temporal_namespace.clone(),
                execution: Some(WorkflowExecution {
                    workflow_id: id.clone(),
                    run_id: String::new(),
                }),
                maximum_page_size: 1,
                ..Default::default()
            },
        ))
        .await;
    match history {
        Ok(result) => {
            if let Some(event) = result
                .into_inner()
                .history
                .and_then(|h| h.events.into_iter().next())
                && let Some(Attributes::WorkflowExecutionStartedEventAttributes(attributes)) =
                    event.attributes
                && let Some(payload) = attributes.input.and_then(|p| p.payloads.into_iter().next())
            {
                let original: copy::Continue =
                    serde_json::from_slice(&payload.data).map_err(|_| ApiError::conflict())?;
                if original
                    .start
                    .as_ref()
                    .map(|s| serde_json::json!(&s.request.input))
                    != Some(serde_json::json!(&start.request.input))
                {
                    return Err(ApiError::state("IDEMPOTENCY_CONFLICT"));
                }
            }
        }
        Err(status) if status.code() == temporalio_client::tonic::Code::NotFound => {}
        Err(_) => {
            return Err(ApiError(
                axum::http::StatusCode::SERVICE_UNAVAILABLE,
                "DEPENDENCY_UNAVAILABLE",
                "Temporal unavailable",
            ));
        }
    }
    let options = WorkflowStartOptions::new(QUEUE, id)
        .id_conflict_policy(WorkflowIdConflictPolicy::UseExisting)
        .id_reuse_policy(WorkflowIdReusePolicy::AllowDuplicate)
        .execution_timeout(std::time::Duration::from_secs(7 * 86400))
        .build();
    app.temporal
        .start_workflow(
            copy_workflow::CopyNode::run,
            copy::Continue {
                operation_id: None,
                start: Some(start.clone()),
            },
            options,
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
            if let Some(v) = copy::existing(app, &start).await? {
                return Ok((axum::http::StatusCode::ACCEPTED, v));
            }
            tokio::time::sleep(std::time::Duration::from_millis(50)).await;
        }
    };
    match tokio::time::timeout(std::time::Duration::from_secs(2), wait).await {
        Ok(v) => v,
        Err(_) => Err(admission_error(
            app,
            &format!(
                "copy/{}/{}/{}",
                start.filesystem_id, start.request.scope.actor_id, key
            ),
        )
        .await),
    }
}

async fn retained_input(
    app: &crate::http::App,
    id: &str,
    expected: serde_json::Value,
) -> Result<(), crate::http::ApiError> {
    use crate::http::ApiError;
    use temporalio_common::protos::temporal::api::{
        common::v1::WorkflowExecution, history::v1::history_event::Attributes,
        workflowservice::v1::GetWorkflowExecutionHistoryRequest,
    };
    let result = app
        .temporal
        .connection()
        .workflow_service()
        .get_workflow_execution_history(temporalio_client::tonic::Request::new(
            GetWorkflowExecutionHistoryRequest {
                namespace: app.config.temporal_namespace.clone(),
                execution: Some(WorkflowExecution {
                    workflow_id: id.into(),
                    run_id: String::new(),
                }),
                maximum_page_size: 1,
                ..Default::default()
            },
        ))
        .await;
    match result {
        Ok(result) => {
            let event = result
                .into_inner()
                .history
                .and_then(|h| h.events.into_iter().next())
                .ok_or_else(ApiError::conflict)?;
            let Some(Attributes::WorkflowExecutionStartedEventAttributes(started)) =
                event.attributes
            else {
                return Err(ApiError::conflict());
            };
            let payload = started
                .input
                .and_then(|p| p.payloads.into_iter().next())
                .ok_or_else(ApiError::conflict)?;
            let original: serde_json::Value =
                serde_json::from_slice(&payload.data).map_err(|_| ApiError::conflict())?;
            if original != expected {
                return Err(ApiError::state("IDEMPOTENCY_CONFLICT"));
            }
            Ok(())
        }
        Err(e) if e.code() == temporalio_client::tonic::Code::NotFound => Ok(()),
        Err(_) => Err(ApiError(
            axum::http::StatusCode::SERVICE_UNAVAILABLE,
            "DEPENDENCY_UNAVAILABLE",
            "Temporal unavailable",
        )),
    }
}
async fn admission_error(app: &crate::http::App, id: &str) -> crate::http::ApiError {
    use crate::http::ApiError;
    use temporalio_common::protos::temporal::api::{
        common::v1::WorkflowExecution, enums::v1::HistoryEventFilterType,
        failure::v1::failure::FailureInfo, history::v1::history_event::Attributes,
        workflowservice::v1::GetWorkflowExecutionHistoryRequest,
    };
    let result = app
        .temporal
        .connection()
        .workflow_service()
        .get_workflow_execution_history(temporalio_client::tonic::Request::new(
            GetWorkflowExecutionHistoryRequest {
                namespace: app.config.temporal_namespace.clone(),
                execution: Some(WorkflowExecution {
                    workflow_id: id.into(),
                    run_id: String::new(),
                }),
                history_event_filter_type: HistoryEventFilterType::CloseEvent.into(),
                ..Default::default()
            },
        ))
        .await;
    if let Ok(result) = result
        && let Some(event) = result
            .into_inner()
            .history
            .and_then(|h| h.events.into_iter().next())
        && let Some(Attributes::WorkflowExecutionFailedEventAttributes(failed)) = event.attributes
    {
        let mut failure = failed.failure;
        while let Some(value) = failure {
            if let Some(FailureInfo::ApplicationFailureInfo(info)) = value.failure_info {
                let code = match info.r#type.as_str() {
                    "NOT_FOUND" => return ApiError::not_found(),
                    "VALIDATION" => return ApiError::bad("invalid operation"),
                    "REVISION_MISMATCH" => return ApiError::revision_mismatch(),
                    "TARGET_MISMATCH" => return ApiError::target_mismatch(),
                    "PRECONDITION_REQUIRED" => return ApiError::precondition_required(),
                    "TRASH_PURGING" => "TRASH_PURGING",
                    "FILESYSTEM_DELETING" => "FILESYSTEM_DELETING",
                    "BUCKET_FROZEN" => "BUCKET_FROZEN",
                    "RESOURCE_LIMIT" => "RESOURCE_LIMIT",
                    "NAME_CONFLICT" => "NAME_CONFLICT",
                    "CYCLE" => "CYCLE",
                    "SCOPE_CONFLICT" => "SCOPE_CONFLICT",
                    "IDEMPOTENCY_CONFLICT" => "IDEMPOTENCY_CONFLICT",
                    _ => {
                        failure = value.cause.map(|v| *v);
                        continue;
                    }
                };
                return ApiError::state(code);
            }
            failure = value.cause.map(|v| *v);
        }
    }
    ApiError(
        axum::http::StatusCode::SERVICE_UNAVAILABLE,
        "ADMISSION_PENDING",
        "retry with the same key",
    )
}
pub async fn start_deletion(
    app: &crate::http::App,
    input: crate::fs::deletion::Start,
) -> Result<(axum::http::StatusCode, serde_json::Value), crate::http::ApiError> {
    use crate::{fs::deletion, http::ApiError};
    use temporalio_client::{
        WorkflowIdConflictPolicy, WorkflowIdReusePolicy, WorkflowStartOptions,
    };
    let existing = deletion::existing(app, &input).await?;
    if let Some(ref value) = existing
        && value["state"] != "running"
    {
        return Ok((axum::http::StatusCode::OK, value.clone()));
    }
    let op = existing
        .as_ref()
        .and_then(|v| v["operation_id"].as_str())
        .and_then(|v| uuid::Uuid::parse_str(v).ok());
    let id = input.workflow_id();
    let argument = lifecycle_workflow::Continue {
        operation_id: op,
        start: if op.is_none() {
            Some(input.clone())
        } else {
            None
        },
    };
    if op.is_none() {
        retained_input(app, &id, serde_json::json!(&argument)).await?;
    }
    let options = WorkflowStartOptions::new(QUEUE, id.clone())
        .id_conflict_policy(WorkflowIdConflictPolicy::UseExisting)
        .id_reuse_policy(WorkflowIdReusePolicy::AllowDuplicate)
        .execution_timeout(std::time::Duration::from_secs(7 * 86400))
        .build();
    let result = if input.entry_id.is_some() {
        app.temporal
            .start_workflow(lifecycle_workflow::PurgeTrash::run, argument, options)
            .await
            .map(|_| ())
    } else {
        app.temporal
            .start_workflow(lifecycle_workflow::DeleteFilesystem::run, argument, options)
            .await
            .map(|_| ())
    };
    result.map_err(|_| {
        ApiError(
            axum::http::StatusCode::SERVICE_UNAVAILABLE,
            "DEPENDENCY_UNAVAILABLE",
            "Temporal unavailable",
        )
    })?;
    let wait = async {
        loop {
            if let Some(value) = deletion::existing(app, &input).await? {
                return Ok((
                    if value["state"] == "running" {
                        axum::http::StatusCode::ACCEPTED
                    } else {
                        axum::http::StatusCode::OK
                    },
                    value,
                ));
            }
            tokio::time::sleep(std::time::Duration::from_millis(50)).await;
        }
    };
    match tokio::time::timeout(std::time::Duration::from_secs(2), wait).await {
        Ok(v) => v,
        Err(_) => Err(admission_error(app, &id).await),
    }
}
