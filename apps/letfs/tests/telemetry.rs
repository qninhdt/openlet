use opentelemetry::{
    Context, global,
    trace::{FutureExt, TraceContextExt, Tracer, TracerProvider},
};
use opentelemetry_sdk::{
    propagation::TraceContextPropagator,
    trace::{InMemorySpanExporter, SdkTracerProvider, SimpleSpanProcessor},
};
use std::time::Duration;
use temporalio_client::{
    Client, ClientOptions, Connection, ConnectionOptions, WorkflowFetchHistoryOptions,
    WorkflowGetResultOptions, WorkflowStartOptions,
};
use temporalio_macros::{activities, workflow, workflow_methods};
use temporalio_sdk::{
    ActivityOptions, ContinueAsNewOptions, Runtime, Worker, WorkerOptions, WorkflowContext,
    WorkflowResult,
    activities::{ActivityContext, ActivityError},
    opentelemetry::{OpenTelemetryPlugin, WorkflowIdGenerator, WorkflowSpanProcessor},
    workflow_replayer::{WorkflowReplayer, WorkflowReplayerOptions},
};
use testcontainers::{GenericImage, ImageExt, core::IntoContainerPort, runners::AsyncRunner};

#[workflow]
#[derive(Default)]
pub struct TraceContinuation;

#[workflow_methods]
impl TraceContinuation {
    #[run]
    pub async fn run(ctx: &mut WorkflowContext<Self>, iteration: u32) -> WorkflowResult<String> {
        let trace = ctx
            .execute_activity(
                TraceActivity::identity,
                (),
                ActivityOptions::start_to_close_timeout(Duration::from_secs(10)),
            )
            .await?;
        if iteration == 0 {
            ctx.continue_as_new(1, ContinueAsNewOptions::default())?;
        }
        Ok(trace)
    }
}

pub struct TraceActivity;

#[activities]
impl TraceActivity {
    #[activity]
    pub async fn identity(_ctx: ActivityContext) -> Result<String, ActivityError> {
        Ok(Context::current()
            .span()
            .span_context()
            .trace_id()
            .to_string())
    }
}

fn plugin() -> temporalio_sdk::SimplePlugin {
    OpenTelemetryPlugin::builder()
        .propagator(TraceContextPropagator::new())
        .build()
}

#[tokio::test]
#[ignore = "requires Docker; run pnpm --filter @openlet/letfs test:integration"]
async fn temporal_preserves_trace_across_continue_as_new_without_exporting_replay_spans() {
    let exporter = InMemorySpanExporter::default();
    let provider = SdkTracerProvider::builder()
        .with_id_generator(WorkflowIdGenerator::default())
        .with_span_processor(WorkflowSpanProcessor::new(SimpleSpanProcessor::new(
            exporter.clone(),
        )))
        .build();
    global::set_tracer_provider(provider.clone());
    let server = GenericImage::new(
        "temporalio/admin-tools",
        "1.32.1@sha256:9ef0dc5b063bf4ffd5c1512de72e0e73e225bd2c7006a18ce69bd592a8862a83",
    )
    .with_entrypoint("temporal")
    .with_exposed_port(7233.tcp())
    .with_cmd(["server", "start-dev", "--ip", "0.0.0.0", "--headless"])
    .start()
    .await
    .unwrap();
    let endpoint = format!(
        "http://{}:{}",
        server.get_host().await.unwrap(),
        server.get_host_port_ipv4(7233).await.unwrap()
    );
    let connection = tokio::time::timeout(Duration::from_secs(30), async {
        loop {
            if let Ok(connection) = Connection::connect(
                ConnectionOptions::new(url::Url::parse(&endpoint).unwrap()).build(),
            )
            .await
            {
                break connection;
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    })
    .await
    .unwrap();
    let client = Client::new(
        connection,
        ClientOptions::new("default").plugin(plugin()).build(),
    )
    .unwrap();
    let runtime = Runtime::from_current_tokio(Default::default()).unwrap();
    let mut worker = Worker::new(
        &runtime,
        client.clone(),
        WorkerOptions::new("trace-continuation")
            .register_workflow::<TraceContinuation>()
            .unwrap()
            .register_activities(TraceActivity)
            .build(),
    )
    .unwrap();
    let stop = worker.shutdown_handle();
    let root = Context::new().with_span(provider.tracer("test").start("request"));
    let expected = root.span().span_context().trace_id();
    let journey = async {
        let first = client
            .start_workflow(
                TraceContinuation::run,
                0,
                WorkflowStartOptions::new("trace-continuation", "trace-continuation").build(),
            )
            .with_context(root.clone())
            .await
            .unwrap();
        let result = first
            .get_result(WorkflowGetResultOptions::default())
            .await
            .unwrap();
        assert_eq!(result, expected.to_string());
        let first_history = first
            .fetch_history(WorkflowFetchHistoryOptions::default())
            .into_events()
            .await
            .unwrap();
        let last_history = client
            .get_workflow_handle::<TraceContinuation>("trace-continuation")
            .fetch_history(WorkflowFetchHistoryOptions::default())
            .into_events()
            .await
            .unwrap();
        stop();
        (first_history, last_history)
    };
    let (histories, worker_result) = tokio::time::timeout(Duration::from_secs(60), async {
        tokio::join!(journey, worker.run())
    })
    .await
    .unwrap();
    worker_result.unwrap();
    root.span().end();
    provider.force_flush().unwrap();
    let before = exporter.get_finished_spans().unwrap();
    assert_eq!(
        before
            .iter()
            .filter(|s| s.name == "RunWorkflow:TraceContinuation")
            .count(),
        2
    );
    assert_eq!(
        before
            .iter()
            .filter(|s| s.name == "RunActivity:TraceActivity::identity")
            .count(),
        2
    );
    assert!(before.iter().all(|s| s.span_context.trace_id() == expected));
    let replayer = WorkflowReplayer::new(
        WorkflowReplayerOptions::new()
            .register_workflow::<TraceContinuation>()
            .unwrap()
            .worker_plugin(plugin())
            .build(),
    )
    .unwrap();
    for events in [histories.0, histories.1] {
        replayer
            .replay_workflow(
                temporalio_common::protos::temporal::api::history::v1::History { events }.into(),
            )
            .await
            .unwrap();
    }
    provider.force_flush().unwrap();
    assert_eq!(exporter.get_finished_spans().unwrap().len(), before.len());
    provider.shutdown().unwrap();
}
