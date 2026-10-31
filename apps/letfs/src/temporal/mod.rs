pub mod copy_workflow;
pub mod lifecycle_workflow;
pub mod process_file_workflow;
pub mod provisioning;
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
        temporalio_client::ClientOptions::new(&config.temporal_namespace)
            .plugin(
                temporalio_sdk::opentelemetry::OpenTelemetryPlugin::builder()
                    .propagator(opentelemetry_sdk::propagation::TraceContextPropagator::new())
                    .build(),
            )
            .build(),
    )
    .map_err(|_| "Temporal client configuration rejected".into())
}

pub async fn start_copy(app: &App, admission: crate::fs::copy::Admission) -> Result<(), ApiError> {
    use temporalio_client::{
        WorkflowIdConflictPolicy, WorkflowIdReusePolicy, WorkflowStartOptions,
    };
    let options = WorkflowStartOptions::new(QUEUE, admission.workflow_id())
        .id_conflict_policy(WorkflowIdConflictPolicy::UseExisting)
        .id_reuse_policy(WorkflowIdReusePolicy::RejectDuplicate)
        .execution_timeout(Duration::from_secs(3600))
        .build();
    let result = tokio::time::timeout(
        Duration::from_secs(3),
        app.temporal.start_workflow(
            copy_workflow::CopyNode::run,
            copy_workflow::State::new(admission),
            options,
        ),
    )
    .await;
    match result {
        Ok(Ok(_)) => Ok(()),
        Ok(Err(temporalio_client::errors::WorkflowStartError::AlreadyStarted { .. })) => Ok(()),
        _ => Err(ApiError(
            axum::http::StatusCode::SERVICE_UNAVAILABLE,
            "DEPENDENCY_UNAVAILABLE",
            "Temporal unavailable",
        )),
    }
}

pub async fn start_deletion(app: &App, input: crate::fs::deletion::Start) -> Result<(), ApiError> {
    use temporalio_client::{
        WorkflowIdConflictPolicy, WorkflowIdReusePolicy, WorkflowStartOptions,
    };
    let options = WorkflowStartOptions::new(QUEUE, input.workflow_id())
        .id_conflict_policy(WorkflowIdConflictPolicy::UseExisting)
        .id_reuse_policy(WorkflowIdReusePolicy::AllowDuplicate)
        .execution_timeout(Duration::from_secs(7 * 86400))
        .build();
    let result = tokio::time::timeout(Duration::from_secs(3), async {
        if input.entry_id.is_some() {
            app.temporal
                .start_workflow(lifecycle_workflow::PurgeTrash::run, input, options)
                .await
                .map(|_| ())
        } else {
            app.temporal
                .start_workflow(lifecycle_workflow::DeleteFilesystem::run, input, options)
                .await
                .map(|_| ())
        }
    })
    .await;
    match result {
        Ok(Ok(())) => Ok(()),
        _ => Err(ApiError(
            axum::http::StatusCode::SERVICE_UNAVAILABLE,
            "DEPENDENCY_UNAVAILABLE",
            "Temporal unavailable",
        )),
    }
}
