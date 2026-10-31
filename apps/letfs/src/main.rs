use letfs::{
    config::Config,
    http::{App, router},
};
use std::sync::Arc;
#[tokio::main]
async fn main() {
    if std::env::args().nth(1).as_deref() == Some("--healthcheck") {
        let healthy = match reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(4))
            .build()
        {
            Ok(client) => client
                .get("http://127.0.0.1:8080/ready")
                .send()
                .await
                .is_ok_and(|r| r.status() == 204),
            Err(_) => false,
        };
        std::process::exit(if healthy { 0 } else { 1 });
    }
    let telemetry = match letfs::telemetry::Telemetry::init() {
        Ok(telemetry) => telemetry,
        Err(message) => {
            eprintln!("{message}");
            std::process::exit(1);
        }
    };
    let result = run().await;
    if let Err(ref message) = result {
        tracing::error!(error=%message,"startup failed");
    }
    let _ = tokio::task::spawn_blocking(move || telemetry.shutdown()).await;
    if result.is_err() {
        std::process::exit(1);
    }
}
async fn run() -> Result<(), String> {
    if std::env::args().nth(1).as_deref() == Some("--provider-smoke") {
        return letfs::storage::provider_smoke::run().await;
    }
    let config = Config::load()?;
    let pool = sqlx::postgres::PgPoolOptions::new()
        .max_connections(16)
        .acquire_timeout(std::time::Duration::from_secs(5))
        .connect(&config.database_url)
        .await
        .map_err(|_| "database connection failed")?;
    let temporal = letfs::temporal::client(&config).await?;
    let (storage, signer) = letfs::storage::build(&config)?;
    let app = App {
        archive_slots: Arc::new(tokio::sync::Semaphore::new(
            config.archive.max_concurrent as usize,
        )),
        pool,
        storage,
        signer,
        temporal: temporal.clone(),
        config: Arc::new(config),
    };
    if std::env::args().nth(1).as_deref() == Some("--backfill-processing") {
        return letfs::fs::backfill::run(&app, &std::env::args().skip(2).collect::<Vec<_>>()).await;
    }
    let listener = tokio::net::TcpListener::bind(app.config.listen)
        .await
        .map_err(|_| "listen failed")?;
    letfs::temporal::lifecycle_workflow::ensure_schedule(&app).await?;
    let runtime = temporalio_sdk::Runtime::from_current_tokio(Default::default())
        .map_err(|_| "Temporal runtime failed")?;
    use temporalio_sdk::runtime::worker_tuner::{FixedSizeSlotSupplier, TunerHolder};
    let tuner = TunerHolder::builder()
        .workflow_task_slot_supplier(FixedSizeSlotSupplier::new(16))
        .activity_task_slot_supplier(FixedSizeSlotSupplier::new(8))
        .local_activity_task_slot_supplier(FixedSizeSlotSupplier::new(8))
        .nexus_task_slot_supplier(FixedSizeSlotSupplier::new(1))
        .build();
    let options = temporalio_sdk::WorkerOptions::new(letfs::temporal::QUEUE)
        .max_cached_workflows(128)
        .tuner(tuner)
        .graceful_shutdown_period(std::time::Duration::from_secs(20))
        .register_workflow::<letfs::temporal::copy_workflow::CopyNode>()
        .map_err(|_| "workflow registration failed")?
        .register_workflow::<letfs::temporal::process_file_workflow::ProcessFile>()
        .map_err(|_| "workflow registration failed")?
        .register_workflow::<letfs::temporal::lifecycle_workflow::PurgeTrash>()
        .map_err(|_| "workflow registration failed")?
        .register_workflow::<letfs::temporal::lifecycle_workflow::DeleteFilesystem>()
        .map_err(|_| "workflow registration failed")?
        .register_workflow::<letfs::temporal::lifecycle_workflow::StorageMaintenance>()
        .map_err(|_| "workflow registration failed")?
        .register_activities(letfs::temporal::lifecycle_workflow::LifecycleActivities {
            app: app.clone(),
        })
        .register_activities(letfs::temporal::provisioning::ProvisioningActivities {
            app: app.clone(),
        })
        .register_activities(letfs::temporal::copy_workflow::StorageActivities { app: app.clone() })
        .build();
    let mut worker = temporalio_sdk::Worker::new(&runtime, temporal, options)
        .map_err(|_| "worker initialization failed")?;
    let shutdown_worker = worker.shutdown_handle();
    let (shutdown_tx, mut shutdown_rx) = tokio::sync::watch::channel(false);
    let server = axum::serve(listener, router(app)).with_graceful_shutdown(async move {
        let _ = shutdown_rx.changed().await;
    });
    use std::future::IntoFuture;
    let http = server.into_future();
    let work = worker.run();
    tokio::pin!(http, work);
    let mut term = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
        .map_err(|_| "signal handler failed")?;
    tokio::select! {
      _=tokio::signal::ctrl_c()=>{},_=term.recv()=>{},
      result=&mut http=>{shutdown_worker();return result.map_err(|_|"HTTP server failed".into())},
      result=&mut work=>{let _=shutdown_tx.send(true);return result.map_err(|_|"Temporal worker failed".into())},
    }
    let _ = shutdown_tx.send(true);
    shutdown_worker();
    tokio::time::timeout(std::time::Duration::from_secs(125), async {
        let (http, worker) = tokio::join!(http, work);
        http.map_err(|_| "HTTP shutdown failed")?;
        worker.map_err(|_| "worker shutdown failed")?;
        Ok(())
    })
    .await
    .map_err(|_| "shutdown deadline exceeded")?
}
