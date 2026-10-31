use axum::{body::Body, http::StatusCode};
use letfs::{
    config::{Config, StorageConfig},
    fs::{self, nodes},
    http::App,
};
use object_store::{ObjectStoreExt, path::Path as ObjectPath};
use serde_json::{Value, json};
use sqlx::Row;
use std::{path::Path, sync::Arc, time::Duration};
use testcontainers::{
    ContainerAsync, GenericImage, ImageExt,
    core::{
        CmdWaitFor, ExecCommand, IntoContainerPort, Mount, WaitFor, logs::LogSource,
        wait::LogWaitStrategy,
    },
    runners::AsyncRunner,
};
use uuid::Uuid;

struct Fixture {
    app: App,
    _postgres: ContainerAsync<GenericImage>,
    _storage: ContainerAsync<GenericImage>,
    _temporal: ContainerAsync<GenericImage>,
}
impl Fixture {
    async fn new() -> Self {
        let postgres = GenericImage::new(
            "postgres",
            "18.6-trixie@sha256:74935e72241653ca55e0414067e6d8763aceb8a810eb51b452253ec3dcfc4336",
        )
        .with_exposed_port(5432.tcp())
        .with_wait_for(WaitFor::log(
            LogWaitStrategy::new(
                LogSource::BothStd,
                "database system is ready to accept connections",
            )
            .with_times(2),
        ))
        .with_env_var("POSTGRES_USER", "openlet_letfs")
        .with_env_var("POSTGRES_DB", "openlet_letfs")
        .with_env_var("POSTGRES_PASSWORD", "isolated-testcontainers-password")
        .with_copy_to(
            "/migrate.sh",
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../scripts/migrate.sh"),
        )
        .with_copy_to(
            "/migrations/letfs/migrations",
            Path::new(env!("CARGO_MANIFEST_DIR")).join("migrations"),
        )
        .with_copy_to(
            "/run/secrets/letfs_db_password",
            b"isolated-testcontainers-password".to_vec(),
        )
        .with_startup_timeout(Duration::from_secs(60))
        .start()
        .await
        .unwrap();
        let migration = postgres
            .exec(
                ExecCommand::new(["sh", "/migrate.sh", "letfs"])
                    .with_cmd_ready_condition(CmdWaitFor::exit()),
            )
            .await
            .unwrap();
        assert_eq!(
            migration.exit_code().await.unwrap(),
            Some(0),
            "backup/migration failed"
        );
        let database_url = format!(
            "postgres://openlet_letfs:isolated-testcontainers-password@{}:{}/openlet_letfs?sslmode=disable",
            postgres.get_host().await.unwrap(),
            postgres.get_host_port_ipv4(5432).await.unwrap()
        );
        let pool = sqlx::postgres::PgPoolOptions::new()
            .max_connections(8)
            .acquire_timeout(Duration::from_secs(5))
            .connect(&database_url)
            .await
            .unwrap();
        let s3_config = br#"{"identities":[{"name":"integration","credentials":[{"accessKey":"integration","secretKey":"isolated-testcontainers-secret"}],"actions":["Read","Write","List","Admin"]}]}"#;
        let storage = GenericImage::new(
            "chrislusf/seaweedfs",
            "4.19@sha256:90e181977effc58a303a1b21a0d581314e142b09543a712ff739c79ed78f42cf",
        )
        .with_exposed_port(8333.tcp())
        .with_mount(Mount::tmpfs_mount("/data").with_size_bytes(256 * 1024 * 1024))
        .with_copy_to("/etc/s3.json", s3_config.to_vec())
        .with_cmd([
            "server",
            "-dir=/data",
            "-ip=127.0.0.1",
            "-ip.bind=0.0.0.0",
            "-s3",
            "-s3.config=/etc/s3.json",
            "-master.volumeSizeLimitMB=64",
            "-volume.max=8",
        ])
        .start()
        .await
        .unwrap();
        let endpoint = format!(
            "http://{}:{}",
            storage.get_host().await.unwrap(),
            storage.get_host_port_ipv4(8333).await.unwrap()
        );
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(2))
            .build()
            .unwrap();
        tokio::time::timeout(Duration::from_secs(45), async {
            loop {
                if client
                    .get(&endpoint)
                    .send()
                    .await
                    .is_ok_and(|r| r.status().as_u16() == 403)
                {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
        })
        .await
        .expect("S3 readiness deadline");
        let mut bucket = storage
            .exec(
                ExecCommand::new([
                    "sh",
                    "-c",
                    "echo 's3.bucket.create -name openlet-integration' | timeout 20 weed shell -master=127.0.0.1:9333 -filer=127.0.0.1:8888",
                ])
                .with_cmd_ready_condition(CmdWaitFor::exit()),
            )
            .await
            .unwrap();
        assert_eq!(bucket.exit_code().await.unwrap(), Some(0));
        assert!(
            String::from_utf8(bucket.stdout_to_vec().await.unwrap())
                .unwrap()
                .contains("created bucket openlet-integration")
        );
        // Ordinary file operations do not run workflows; the real dev server supplies App's client.
        let temporal = GenericImage::new(
            "temporalio/admin-tools",
            "1.32.1@sha256:9ef0dc5b063bf4ffd5c1512de72e0e73e225bd2c7006a18ce69bd592a8862a83",
        )
        .with_entrypoint("temporal")
        .with_exposed_port(7233.tcp())
        .with_cmd(["server", "start-dev", "--ip", "0.0.0.0", "--headless"])
        .start()
        .await
        .unwrap();
        let config = Config {
            listen: "127.0.0.1:0".parse().unwrap(),
            database_url,
            workspace_token: "integration-service-token-0123456789abcdef".into(),
            processor_token: "processor-service-token-0123456789abcdef".into(),
            exports: Default::default(),
            processing_max_outputs: 512,
            processing_max_output_bytes: 268435456,
            temporal_address: format!(
                "http://{}:{}",
                temporal.get_host().await.unwrap(),
                temporal.get_host_port_ipv4(7233).await.unwrap()
            ),
            temporal_namespace: "default".into(),
            max_nodes: 1000,
            inline_limit: 262144,
            max_file_bytes: 104857600,
            max_outstanding: 16,
            max_cleanup_backlog: 10000,
            max_copy_nodes: 64,
            search: Default::default(),
            storage: StorageConfig {
                signing_endpoint: endpoint.clone(),
                download_url_ttl_seconds: 300,
                upload_url_ttl_seconds: 900,
                upload_transfer_grace_seconds: 3600,
                multipart_threshold_bytes: 16777216,
                multipart_part_bytes: 8388608,
                endpoint,
                region: "us-east-1".into(),
                bucket: "openlet-integration".into(),
                access_key: "integration".into(),
                secret_key: "isolated-testcontainers-secret".into(),
                allow_http: true,
            },
        };
        let temporal_client = tokio::time::timeout(Duration::from_secs(30), async {
            loop {
                if let Ok(client) = letfs::temporal::client(&config).await {
                    break client;
                }
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
        })
        .await
        .expect("Temporal readiness deadline");
        let (store, signer) = letfs::storage::build(&config).unwrap();
        let app = App {
            storage: store,
            signer,
            pool,
            config: Arc::new(config),
            temporal: temporal_client,
        };
        Self {
            app,
            _postgres: postgres,
            _storage: storage,
            _temporal: temporal,
        }
    }

    async fn filesystem(&self, bucket: Uuid) -> (Uuid, Uuid) {
        let (fs, root) = (Uuid::now_v7(), Uuid::now_v7());
        fs::ensure_filesystem(
            &self.app.pool,
            fs::EnsureFilesystem {
                id: fs,
                bucket_id: bucket,
                root_id: root,
                provision_key: fs.to_string(),
                root_name: "root".into(),
            },
            1000,
        )
        .await
        .unwrap();
        (fs, root)
    }
}

fn request(fs: Uuid, actor: Uuid, input: Value) -> nodes::Request {
    serde_json::from_value(json!({
        "scope": {
            "actor_id": actor,
            "mounts": [{"path": "/drive", "filesystem_id": fs}]
        },
        "input": input
    }))
    .unwrap()
}

async fn usage(app: &App, bucket: Uuid) -> i64 {
    sqlx::query_scalar("SELECT used_bytes FROM quota_buckets WHERE id=$1")
        .bind(bucket)
        .fetch_one(&app.pool)
        .await
        .unwrap()
}

#[tokio::test]
#[ignore = "requires Docker; run make test-integration SERVICE=letfs"]
async fn file_input_boundaries() {
    let fixture = Fixture::new().await;
    let mut app = fixture.app.clone();
    let mut config = (*app.config).clone();
    config.max_file_bytes = 4;
    app.config = Arc::new(config);
    let bucket = Uuid::now_v7();
    fs::ensure_bucket(
        &app.pool,
        fs::EnsureBucket {
            id: bucket,
            provision_key: bucket.to_string(),
            limit_bytes: "1000".into(),
        },
    )
    .await
    .unwrap();
    let (fs, root) = fixture.filesystem(bucket).await;
    let actor = Uuid::now_v7();
    let node = nodes::create(
        &app,
        fs,
        "text",
        request(
            fs,
            actor,
            json!({"parent":{"node_id":root},"name":"note","text":"1234"}),
        ),
    )
    .await
    .unwrap();
    for path in [
        "/drive/note/.",
        "/drive/note/./",
        "/drive/note/",
        "/drive/note/./.",
    ] {
        assert_eq!(
            nodes::read(
                &app,
                fs,
                "stat",
                request(fs, actor, json!({"locator":{"path":path}})),
            )
            .await
            .unwrap()["id"],
            json!(node.id),
            "container syntax changed file identity: {path}"
        );
        assert_eq!(nodes::create(&app,fs,"text",request(fs,actor,json!({"parent":{"path":path,"expected_parent_id":node.id},"name":"forbidden","text":"x"}))).await.unwrap_err().1,"NOT_DIRECTORY");
    }
    let root_by_dot = nodes::read(
        &app,
        fs,
        "stat",
        request(fs, actor, json!({"locator":{"path":"/drive/./."}})),
    )
    .await
    .unwrap();
    assert_eq!(root_by_dot["id"], json!(root));
    let copy = fs::copy::inline(&app, fs, request(fs, actor,
        json!({"locator":{"node_id":node.id},"parent":{"node_id":root},"name":"copy", "revision":"1", "request_key":Uuid::now_v7(), "text":"unexpected body"})
    )).await;
    assert!(matches!(copy, Err(ref error) if error.1 == "VALIDATION"));
    let oversized = nodes::create(
        &app,
        fs,
        "text",
        request(
            fs,
            actor,
            json!({"parent":{"node_id":root},"name":"large","text":"12345"}),
        ),
    )
    .await;
    assert!(matches!(oversized, Err(ref error) if error.0 == StatusCode::PAYLOAD_TOO_LARGE));
    let oversized = nodes::modify(
        &app,
        fs,
        "replace-text",
        request(
            fs,
            actor,
            json!({"locator":{"node_id":node.id},"revision":"1","text":"12345"}),
        ),
    )
    .await;
    assert!(matches!(oversized, Err(ref error) if error.0 == StatusCode::PAYLOAD_TOO_LARGE));
    let upload = fs::uploads::create(
        &app,
        fs,
        request(
            fs,
            actor,
            json!({"parent":{"node_id":root},"name":"upload", "text":"unexpected body"}),
        ),
    )
    .await;
    assert!(matches!(upload, Err(ref error) if error.1 == "VALIDATION"));
    assert_eq!(usage(&app, bucket).await, 4);
    app.pool.close().await;
}

#[tokio::test]
#[ignore = "requires Docker; run make test-integration SERVICE=letfs"]
async fn filesystem_and_storage_integration() {
    let fixture = Fixture::new().await;
    let app = &fixture.app;
    let bucket = Uuid::now_v7();
    fs::ensure_bucket(
        &app.pool,
        fs::EnsureBucket {
            id: bucket,
            provision_key: bucket.to_string(),
            limit_bytes: "10000000".into(),
        },
    )
    .await
    .unwrap();
    let (fs, root) = fixture.filesystem(bucket).await;
    let actor = Uuid::now_v7();
    let text = "\u{feff}exact\r\nTiếng Việt";
    let node = nodes::create(
        app,
        fs,
        "text",
        request(
            fs,
            actor,
            json!({"parent":{"node_id":root},"name":"note.txt","text":text,"request_key":Uuid::now_v7()}),
        ),
    )
    .await
    .unwrap();
    assert_eq!(usage(app, bucket).await, text.len() as i64);
    let by_path = nodes::read(
        app,
        fs,
        "stat",
        request(fs, actor, json!({"locator":{"path":"/drive/note.txt"}})),
    )
    .await
    .unwrap();
    assert_eq!(by_path["id"], json!(node.id));
    let bytes: Vec<u8> = sqlx::query_scalar("SELECT inline_bytes FROM file_data WHERE node_id=$1")
        .bind(node.id)
        .fetch_one(&app.pool)
        .await
        .unwrap();
    assert_eq!(bytes, text.as_bytes());
    let stale = nodes::modify(
        app,
        fs,
        "replace-text",
        request(
            fs,
            actor,
            json!({"locator":{"node_id":node.id},"revision":"0","text":"lost"}),
        ),
    )
    .await
    .unwrap_err();
    assert_eq!(stale.1, "REVISION_MISMATCH");
    let wrong_identity = nodes::modify(
        app,
        fs,
        "replace-text",
        request(
            fs,
            actor,
            json!({"locator":{"path":"/drive/note.txt","expected_node_id":Uuid::now_v7()},"revision":node.revision,"text":"lost"}),
        ),
    )
    .await
    .unwrap_err();
    assert_eq!(wrong_identity.1, "TARGET_MISMATCH");
    let duplicate = nodes::create(
        app,
        fs,
        "text",
        request(
            fs,
            actor,
            json!({"parent":{"node_id":root},"name":"note.txt","text":"duplicate","request_key":Uuid::now_v7()}),
        ),
    )
    .await
    .unwrap_err();
    assert_eq!(duplicate.0, StatusCode::CONFLICT);
    let escaped = nodes::read(
        app,
        fs,
        "stat",
        request(fs, actor, json!({"locator":{"path":"/drive/../note.txt"}})),
    )
    .await;
    assert!(escaped.is_err());
    let (foreign, _) = fixture.filesystem(bucket).await;
    assert!(
        nodes::read(
            app,
            foreign,
            "stat",
            request(foreign, actor, json!({"locator":{"node_id":node.id}}))
        )
        .await
        .is_err()
    );

    // Shared hard quota admits exactly one writer across different filesystems.
    let tight = Uuid::now_v7();
    fs::ensure_bucket(
        &app.pool,
        fs::EnsureBucket {
            id: tight,
            provision_key: tight.to_string(),
            limit_bytes: "5".into(),
        },
    )
    .await
    .unwrap();
    let (left, left_root) = fixture.filesystem(tight).await;
    let (right, right_root) = fixture.filesystem(tight).await;
    let (a, b) = tokio::join!(
        nodes::create(
            app,
            left,
            "text",
            request(
                left,
                actor,
                json!({"parent":{"node_id":left_root},"name":"a","text":"1234","request_key":Uuid::now_v7()})
            )
        ),
        nodes::create(
            app,
            right,
            "text",
            request(
                right,
                actor,
                json!({"parent":{"node_id":right_root},"name":"b","text":"5678","request_key":Uuid::now_v7()})
            )
        )
    );
    assert_eq!(usize::from(a.is_ok()) + usize::from(b.is_ok()), 1);
    let loser = a.as_ref().err().or(b.as_ref().err()).unwrap();
    assert_eq!(loser.1, "QUOTA_EXCEEDED");
    assert_eq!(usage(app, tight).await, 4);
    let charged = a.or(b).unwrap();
    fs::trash::trash(
        app,
        charged.filesystem_id,
        request(
            charged.filesystem_id,
            actor,
            json!({"locator":{"node_id":charged.id},"revision":charged.revision}),
        ),
    )
    .await
    .unwrap();
    assert_eq!(usage(app, tight).await, 4);

    for (i, data) in [
        b"\xef\xbb\xbfexact\r\n".to_vec(),
        vec![0, 1, 2, 255],
        vec![b'x'; 6 * 1024 * 1024],
    ]
    .into_iter()
    .enumerate()
    {
        let mode = if i < 2 { "inline" } else { "object" };
        let (id, transferred) = create_and_transfer(
            app,
            fs,
            actor,
            json!({"parent":{"node_id":root},"name":format!("upload-{i}")}),
            &data,
            mode,
        )
        .await;
        assert_eq!(transferred["state"], "uploaded");
        let finalized = fs::uploads::finalize(app, fs, id, actor, None)
            .await
            .unwrap();
        let repeated = fs::uploads::finalize(app, fs, id, actor, None)
            .await
            .unwrap();
        assert_eq!(finalized, repeated);
        let node: Uuid = serde_json::from_value(finalized["node_id"].clone()).unwrap();
        let row = sqlx::query(
            "SELECT storage_kind,inline_bytes,object_key FROM file_data WHERE node_id=$1",
        )
        .bind(node)
        .fetch_one(&app.pool)
        .await
        .unwrap();
        if i < 2 {
            assert_eq!(row.get::<String, _>("storage_kind"), "inline");
            assert_eq!(row.get::<Vec<u8>, _>("inline_bytes"), data);
        } else {
            assert_eq!(row.get::<String, _>("storage_kind"), "object");
            let key = ObjectPath::from(row.get::<String, _>("object_key"));
            assert_eq!(
                app.storage
                    .get(&key)
                    .await
                    .unwrap()
                    .bytes()
                    .await
                    .unwrap()
                    .as_ref(),
                data
            );
            assert_eq!(
                app.storage.get_range(&key, 1..3).await.unwrap().as_ref(),
                &data[1..3]
            );
        }
        assert!(
            fs::uploads::transfer(app, fs, id, actor, Body::from("again"))
                .await
                .is_err()
        );
        assert!(
            fs::uploads::finalize(app, fs, id, Uuid::now_v7(), None)
                .await
                .is_err()
        );
    }
    assert_eq!(
        usage(app, bucket).await,
        text.len() as i64 + 10 + 4 + 6 * 1024 * 1024
    );
    let count: i64 = sqlx::query_scalar("SELECT node_count FROM filesystems WHERE id=$1")
        .bind(fs)
        .fetch_one(&app.pool)
        .await
        .unwrap();
    assert_eq!(count, 5);
    app.pool.close().await;
}

#[tokio::test]
#[ignore = "requires Docker; run make test-integration SERVICE=letfs TEST=direct-storage"]
async fn direct_storage_download() {
    let fixture = Fixture::new().await;
    let app = &fixture.app;
    let bucket = Uuid::now_v7();
    fs::ensure_bucket(
        &app.pool,
        fs::EnsureBucket {
            id: bucket,
            provision_key: bucket.to_string(),
            limit_bytes: "1000000".into(),
        },
    )
    .await
    .unwrap();
    let (filesystem, root) = fixture.filesystem(bucket).await;
    let actor = Uuid::now_v7();
    let bytes = vec![0, 255, 42, 17];
    let (upload_id, _) = create_and_transfer(
        app,
        filesystem,
        actor,
        json!({"parent":{"node_id":root},"name":"report ü.pdf"}),
        &bytes,
        "object",
    )
    .await;
    let published = fs::uploads::finalize(app, filesystem, upload_id, actor, None)
        .await
        .unwrap();
    let node: Uuid = serde_json::from_value(published["node_id"].clone()).unwrap();
    let inline = nodes::create(
        app,
        filesystem,
        "text",
        request(
            filesystem,
            actor,
            json!({"parent":{"node_id":root},"name":"note.txt","text":"hello"}),
        ),
    )
    .await
    .unwrap();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let router = letfs::http::router(app.clone());
    let (shutdown, stop) = tokio::sync::oneshot::channel::<()>();
    let server = tokio::spawn(async move {
        axum::serve(listener, router)
            .with_graceful_shutdown(async {
                let _ = stop.await;
            })
            .await
            .unwrap();
    });
    let client = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(10))
        .build()
        .unwrap();
    let endpoint = format!("http://{address}/internal/v1/filesystems/{filesystem}/files/content");
    let result = async {
        let response = client
            .post(&endpoint)
            .bearer_auth(&app.config.workspace_token)
            .json(&request(
                filesystem,
                actor,
                json!({"locator":{"node_id":node},"revision":"1"}),
            ))
            .header("range", "bytes=1-2")
            .send()
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::TEMPORARY_REDIRECT);
        assert_eq!(response.headers()["etag"], "\"1\"");
        let location = response.headers()["location"].to_str().unwrap().to_owned();
        assert!(
            response.bytes().await.unwrap().is_empty(),
            "letfs relayed object bytes"
        );
        let url = url::Url::parse(&location).unwrap();
        assert_eq!(
            url.host_str(),
            url::Url::parse(&app.config.storage.signing_endpoint)
                .unwrap()
                .host_str()
        );
        let object = client
            .get(&location)
            .header("range", "bytes=1-2")
            .send()
            .await
            .unwrap();
        assert_eq!(object.status(), StatusCode::PARTIAL_CONTENT);
        assert_eq!(object.headers()["content-type"], "application/octet-stream");
        assert!(
            object.headers()["content-disposition"]
                .to_str()
                .unwrap()
                .contains("report%20%C3%BC.pdf")
        );
        assert_eq!(object.bytes().await.unwrap().as_ref(), &bytes[1..3]);
        let renewed = client
            .post(&endpoint)
            .bearer_auth(&app.config.workspace_token)
            .json(&request(
                filesystem,
                actor,
                json!({"locator":{"node_id":node},"revision":"1"}),
            ))
            .send()
            .await
            .unwrap();
        let renewed = url::Url::parse(renewed.headers()["location"].to_str().unwrap()).unwrap();
        assert_eq!(
            renewed.path(),
            url.path(),
            "renewal changed immutable content"
        );
        let mismatch = client
            .post(&endpoint)
            .bearer_auth(&app.config.workspace_token)
            .json(&request(
                filesystem,
                actor,
                json!({"locator":{"node_id":node},"revision":"2"}),
            ))
            .send()
            .await
            .unwrap();
        assert_eq!(mismatch.status(), StatusCode::PRECONDITION_FAILED);
        let inline_response = client
            .post(&endpoint)
            .bearer_auth(&app.config.workspace_token)
            .json(&request(
                filesystem,
                actor,
                json!({"locator":{"node_id":inline.id}}),
            ))
            .header("range", "bytes=1-2")
            .send()
            .await
            .unwrap();
        assert_eq!(inline_response.status(), StatusCode::PARTIAL_CONTENT);
        assert_eq!(
            inline_response.headers()["content-type"],
            "application/octet-stream"
        );
        assert_eq!(inline_response.bytes().await.unwrap().as_ref(), b"el");
    };
    // Always close the task, including assertion failures, before Testcontainers tear down.
    use futures::FutureExt;
    let outcome = std::panic::AssertUnwindSafe(result).catch_unwind().await;
    let _ = shutdown.send(());
    server.await.unwrap();
    app.pool.close().await;
    if let Err(panic) = outcome {
        std::panic::resume_unwind(panic);
    }
}

#[tokio::test]
#[ignore = "requires Docker; run make test-integration SERVICE=letfs TEST=direct-storage"]
async fn direct_storage_provider_contract() {
    let fixture = Fixture::new().await;
    letfs::storage::provider_smoke::direct_upload_contract(
        &fixture.app.storage,
        &fixture.app.config.storage,
        &format!("smoke/{}", Uuid::now_v7()),
    )
    .await
    .unwrap();
}

async fn create_and_transfer(
    app: &App,
    filesystem: Uuid,
    actor: Uuid,
    mut metadata: Value,
    data: &[u8],
    mode: &str,
) -> (Uuid, Value) {
    use base64::{Engine, prelude::BASE64_STANDARD};
    use md5::{Digest, Md5};
    metadata["storage"] = json!(mode);
    metadata["size_bytes"] = json!(data.len().to_string());
    metadata["request_key"] = json!(Uuid::now_v7());
    if mode == "object" {
        metadata["content_md5"] = json!(BASE64_STANDARD.encode(Md5::digest(data)));
    }
    let prepared = fs::uploads::create(app, filesystem, request(filesystem, actor, metadata))
        .await
        .unwrap();
    let id = serde_json::from_value(prepared["id"].clone()).unwrap();
    let transferred = if mode == "inline" {
        fs::uploads::transfer(app, filesystem, id, actor, Body::from(data.to_vec()))
            .await
            .unwrap()
    } else {
        let transfer = &prepared["transfer"];
        let mut put = reqwest::Client::new()
            .put(transfer["url"].as_str().unwrap())
            .body(data.to_vec());
        for (key, value) in transfer["headers"].as_object().unwrap() {
            put = put.header(key, value.as_str().unwrap());
        }
        assert!(put.send().await.unwrap().status().is_success());
        json!({"state":"uploaded"})
    };
    (id, transferred)
}

#[tokio::test]
#[ignore = "requires Docker; run make test-integration SERVICE=letfs TEST=direct-storage"]
async fn direct_storage_sessions_and_publication() {
    use base64::{Engine, prelude::BASE64_STANDARD};
    use md5::{Digest, Md5};
    let fixture = Fixture::new().await;
    let app = &fixture.app;
    let bucket = Uuid::now_v7();
    fs::ensure_bucket(
        &app.pool,
        fs::EnsureBucket {
            id: bucket,
            provision_key: bucket.to_string(),
            limit_bytes: "100000000".into(),
        },
    )
    .await
    .unwrap();
    let (filesystem, root) = fixture.filesystem(bucket).await;
    let actor = Uuid::now_v7();
    for data in [
        vec![],
        vec![0, 255, 128, 42],
        vec![b'a'; app.config.inline_limit],
    ] {
        let key = Uuid::now_v7();
        let input = json!({"parent":{"node_id":root},"name":key.to_string(),"storage":"inline","size_bytes":data.len().to_string(),"request_key":key});
        let prepared =
            fs::uploads::create(app, filesystem, request(filesystem, actor, input.clone()))
                .await
                .unwrap();
        let repeated =
            fs::uploads::create(app, filesystem, request(filesystem, actor, input.clone()))
                .await
                .unwrap();
        assert_eq!(prepared["id"], repeated["id"]);
        let id = serde_json::from_value(prepared["id"].clone()).unwrap();
        let candidate: Option<String> =
            sqlx::query_scalar("SELECT candidate_key FROM uploads WHERE id=$1")
                .bind(id)
                .fetch_one(&app.pool)
                .await
                .unwrap();
        assert!(candidate.is_none());
        let mut changed = input.clone();
        changed["name"] = json!("changed");
        assert_eq!(
            fs::uploads::create(app, filesystem, request(filesystem, actor, changed))
                .await
                .unwrap_err()
                .1,
            "IDEMPOTENCY_CONFLICT"
        );
        fs::uploads::transfer(app, filesystem, id, actor, Body::from(data.clone()))
            .await
            .unwrap();
        fs::uploads::transfer(app, filesystem, id, actor, Body::from(data.clone()))
            .await
            .unwrap();
        let done = fs::uploads::finalize(app, filesystem, id, actor, None)
            .await
            .unwrap();
        assert_eq!(
            done,
            fs::uploads::finalize(app, filesystem, id, actor, None)
                .await
                .unwrap()
        );
        let node: Uuid = serde_json::from_value(done["node_id"].clone()).unwrap();
        let bytes: Vec<u8> =
            sqlx::query_scalar("SELECT inline_bytes FROM file_data WHERE node_id=$1")
                .bind(node)
                .fetch_one(&app.pool)
                .await
                .unwrap();
        assert_eq!(bytes, data);
        assert_eq!(
            fs::uploads::status(app, filesystem, id, actor)
                .await
                .unwrap()["result"],
            done
        );
        let mut limited = app.clone();
        let config = std::sync::Arc::make_mut(&mut limited.config);
        config.inline_limit = 1;
        config.max_file_bytes = 1;
        let retried = fs::uploads::create(&limited, filesystem, request(filesystem, actor, input))
            .await
            .unwrap();
        assert_eq!(retried["id"], prepared["id"]);
        assert_eq!(retried["result"], done);
    }
    for input in [
        json!({"storage":"inline","size_bytes":(app.config.inline_limit+1).to_string()}),
        json!({"storage":"object","size_bytes":"5","content_md5":"invalid"}),
        json!({"storage":"inline","size_bytes":"01"}),
        json!({"storage":"inline","size_bytes":"-1"}),
    ] {
        let mut input = input;
        input["parent"] = json!({"node_id":root});
        input["name"] = json!(Uuid::now_v7().to_string());
        input["request_key"] = json!(Uuid::now_v7());
        assert!(
            fs::uploads::create(app, filesystem, request(filesystem, actor, input))
                .await
                .is_err()
        );
    }
    let source = nodes::create(
        app,
        filesystem,
        "text",
        request(
            filesystem,
            actor,
            json!({"parent":{"node_id":root},"name":"source","text":"old"}),
        ),
    )
    .await
    .unwrap();
    let (id, _) = create_and_transfer(
        app,
        filesystem,
        actor,
        json!({"locator":{"node_id":source.id},"revision":"1"}),
        b"new",
        "object",
    )
    .await;
    let before: Vec<u8> = sqlx::query_scalar("SELECT inline_bytes FROM file_data WHERE node_id=$1")
        .bind(source.id)
        .fetch_one(&app.pool)
        .await
        .unwrap();
    assert_eq!(before, b"old");
    nodes::modify(
        app,
        filesystem,
        "replace-text",
        request(
            filesystem,
            actor,
            json!({"locator":{"node_id":source.id},"revision":"1","text":"concurrent"}),
        ),
    )
    .await
    .unwrap();
    assert_eq!(
        fs::uploads::finalize(app, filesystem, id, actor, None)
            .await
            .unwrap_err()
            .0,
        StatusCode::PRECONDITION_FAILED
    );
    let cleanup=sqlx::query("SELECT d.ambiguous_write,d.eligible_at>=u.transfer_deadline AS retained FROM uploads u JOIN object_deletions d ON d.object_key=u.candidate_key WHERE u.id=$1").bind(id).fetch_one(&app.pool).await.unwrap();
    assert!(cleanup.get::<bool, _>("ambiguous_write") && cleanup.get::<bool, _>("retained"));
    let current: Vec<u8> =
        sqlx::query_scalar("SELECT inline_bytes FROM file_data WHERE node_id=$1")
            .bind(source.id)
            .fetch_one(&app.pool)
            .await
            .unwrap();
    assert_eq!(current, b"concurrent");
    let (id, _) = create_and_transfer(
        app,
        filesystem,
        actor,
        json!({"locator":{"node_id":source.id},"revision":"2"}),
        b"fresh",
        "object",
    )
    .await;
    assert_eq!(
        fs::uploads::finalize(app, filesystem, id, actor, None)
            .await
            .unwrap()["node_id"],
        json!(source.id)
    );
    let previous_key: String =
        sqlx::query_scalar("SELECT object_key FROM file_data WHERE node_id=$1")
            .bind(source.id)
            .fetch_one(&app.pool)
            .await
            .unwrap();
    let (id, _) = create_and_transfer(
        app,
        filesystem,
        actor,
        json!({"locator":{"node_id":source.id},"revision":"3"}),
        b"next",
        "object",
    )
    .await;
    fs::uploads::finalize(app, filesystem, id, actor, None)
        .await
        .unwrap();
    let next_key: String = sqlx::query_scalar("SELECT object_key FROM file_data WHERE node_id=$1")
        .bind(source.id)
        .fetch_one(&app.pool)
        .await
        .unwrap();
    assert_ne!(next_key, previous_key);
    assert!(next_key.starts_with(&format!("objects/{bucket}/")));

    let data = vec![b'm'; 17 * 1024 * 1024];
    let prepared=fs::uploads::create(app,filesystem,request(filesystem,actor,json!({"parent":{"node_id":root},"name":"multipart","storage":"object","size_bytes":data.len().to_string(),"request_key":Uuid::now_v7()}))).await.unwrap();
    assert_eq!(prepared["transport"], "multipart");
    let id = serde_json::from_value(prepared["id"].clone()).unwrap();
    let part_size = prepared["part_size_bytes"]
        .as_str()
        .unwrap()
        .parse::<usize>()
        .unwrap();
    let checksums: Vec<_> = data
        .chunks(part_size)
        .enumerate()
        .map(|(index, bytes)| fs::uploads::PartRequest {
            part_number: index as u32 + 1,
            content_md5: BASE64_STANDARD.encode(Md5::digest(bytes)),
        })
        .collect();
    for invalid in [
        json!([]),
        json!([{"part_number":0,"content_md5":"XUFAKrxLKna5cZ2REBfFkg=="}]),
        json!([{"part_number":4,"content_md5":"XUFAKrxLKna5cZ2REBfFkg=="}]),
        json!([{"part_number":1,"content_md5":"bad"}]),
        json!([{"part_number":1,"content_md5":"XUFAKrxLKna5cZ2REBfFkg=="},{"part_number":1,"content_md5":"XUFAKrxLKna5cZ2REBfFkg=="}]),
        json!(vec![
            json!({"part_number":1,"content_md5":"XUFAKrxLKna5cZ2REBfFkg=="});
            65
        ]),
    ] {
        assert_eq!(
            fs::uploads::part_urls(
                app,
                filesystem,
                id,
                actor,
                serde_json::from_value(invalid).unwrap()
            )
            .await
            .unwrap_err()
            .0,
            StatusCode::BAD_REQUEST,
        );
    }
    let urls = fs::uploads::part_urls(app, filesystem, id, actor, checksums)
        .await
        .unwrap();
    let mut receipts = Vec::new();
    for (part, bytes) in urls["items"]
        .as_array()
        .unwrap()
        .iter()
        .zip(data.chunks(part_size))
    {
        let transfer = &part["transfer"];
        let mut put = reqwest::Client::new()
            .put(transfer["url"].as_str().unwrap())
            .body(bytes.to_vec());
        for (key, value) in transfer["headers"].as_object().unwrap() {
            put = put.header(key, value.as_str().unwrap());
        }
        let response = put.send().await.unwrap();
        assert!(response.status().is_success());
        receipts.push(fs::uploads::Receipt {
            part_number: part["part_number"].as_u64().unwrap() as u32,
            etag: response.headers()["etag"].to_str().unwrap().to_owned(),
        });
    }
    let done = fs::uploads::finalize(app, filesystem, id, actor, Some(receipts.clone()))
        .await
        .unwrap();
    let mut changed = receipts;
    changed[0].etag = "\"00000000000000000000000000000000\"".into();
    assert_eq!(
        fs::uploads::finalize(app, filesystem, id, actor, Some(changed))
            .await
            .unwrap_err()
            .1,
        "IDEMPOTENCY_CONFLICT",
    );
    assert_eq!(
        done,
        fs::uploads::finalize(app, filesystem, id, actor, None)
            .await
            .unwrap()
    );
    let node: Uuid = serde_json::from_value(done["node_id"].clone()).unwrap();
    let key: String = sqlx::query_scalar("SELECT object_key FROM file_data WHERE node_id=$1")
        .bind(node)
        .fetch_one(&app.pool)
        .await
        .unwrap();
    assert_eq!(
        app.storage
            .get(&ObjectPath::from(key))
            .await
            .unwrap()
            .bytes()
            .await
            .unwrap()
            .as_ref(),
        data
    );
    assert!(
        fs::uploads::part_urls(
            app,
            filesystem,
            id,
            actor,
            vec![fs::uploads::PartRequest {
                part_number: 1,
                content_md5: "XUFAKrxLKna5cZ2REBfFkg==".into()
            }]
        )
        .await
        .is_err()
    );
}

#[tokio::test]
#[ignore = "requires Docker, AWS CLI, Python Playwright and Chromium; run make test-integration SERVICE=letfs TEST=direct-storage"]
async fn direct_storage_browser() {
    let fixture = Fixture::new().await;
    let config = &fixture.app.config.storage;
    let configured = tokio::process::Command::new("aws")
        .args([
            "--endpoint-url",
            &config.endpoint,
            "s3api",
            "put-bucket-cors",
            "--bucket",
            &config.bucket,
            "--cors-configuration",
        ])
        .arg(format!(
            "file://{}",
            std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../../tests/storage/cors.json")
                .display()
        ))
        .env("AWS_ACCESS_KEY_ID", &config.access_key)
        .env("AWS_SECRET_ACCESS_KEY", &config.secret_key)
        .env("AWS_DEFAULT_REGION", &config.region)
        .env("AWS_EC2_METADATA_DISABLED", "true")
        .env("AWS_PAGER", "")
        .output()
        .await
        .unwrap();
    assert!(
        configured.status.success(),
        "local test CORS configuration failed"
    );
    letfs::storage::provider_smoke::browser_contract(
        config,
        &fixture.app.storage,
        &fixture.app.signer,
    )
    .await
    .unwrap();
}

#[tokio::test]
#[ignore = "requires Docker; run make test-integration SERVICE=letfs TEST=direct-storage"]
async fn direct_storage_commit_quota_and_abort() {
    let fixture = Fixture::new().await;
    let app = &fixture.app;
    let bucket = Uuid::now_v7();
    fs::ensure_bucket(
        &app.pool,
        fs::EnsureBucket {
            id: bucket,
            provision_key: bucket.to_string(),
            limit_bytes: "3".into(),
        },
    )
    .await
    .unwrap();
    let (filesystem, root) = fixture.filesystem(bucket).await;
    let actor = Uuid::now_v7();
    let (first, _) = create_and_transfer(
        app,
        filesystem,
        actor,
        json!({"parent":{"node_id":root},"name":"first"}),
        b"ab",
        "object",
    )
    .await;
    let (second, _) = create_and_transfer(
        app,
        filesystem,
        actor,
        json!({"parent":{"node_id":root},"name":"second"}),
        b"cd",
        "object",
    )
    .await;
    assert_eq!(
        usage(app, bucket).await,
        0,
        "prepare/transfer reserved logical quota"
    );
    fs::uploads::finalize(app, filesystem, first, actor, None)
        .await
        .unwrap();
    assert_eq!(
        fs::uploads::finalize(app, filesystem, second, actor, None)
            .await
            .unwrap_err()
            .1,
        "QUOTA_EXCEEDED"
    );
    assert_eq!(usage(app, bucket).await, 2);
    let visible = nodes::read(
        app,
        filesystem,
        "list",
        request(filesystem, actor, json!({"locator":{"node_id":root}})),
    )
    .await
    .unwrap();
    assert_eq!(visible["items"].as_array().unwrap().len(), 1);
    let state = fs::uploads::status(app, filesystem, second, actor)
        .await
        .unwrap();
    assert_eq!(state["state"], "aborted");
    let cleanup:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM object_deletions d JOIN uploads u ON u.candidate_key=d.object_key WHERE u.id=$1)").bind(second).fetch_one(&app.pool).await.unwrap();
    assert!(cleanup, "quota rejection lost candidate cleanup evidence");
    fs::uploads::abort(app, filesystem, second, actor)
        .await
        .unwrap();
    assert_eq!(
        fs::uploads::finalize(app, filesystem, second, actor, None)
            .await
            .unwrap_err()
            .1,
        "UPLOAD_NOT_ACTIVE"
    );
    let prepared=fs::uploads::create(app,filesystem,request(filesystem,actor,json!({"parent":{"node_id":root},"name":"aborted-multipart","storage":"object","size_bytes":"16777216","request_key":Uuid::now_v7()}))).await.unwrap();
    let id = serde_json::from_value(prepared["id"].clone()).unwrap();
    fs::uploads::abort(app, filesystem, id, actor)
        .await
        .unwrap();
    let remote: Option<String> = sqlx::query_scalar("SELECT multipart_id FROM uploads WHERE id=$1")
        .bind(id)
        .fetch_one(&app.pool)
        .await
        .unwrap();
    assert!(remote.is_none(), "native abort not acknowledged/persisted");

    let (id, _) = create_and_transfer(
        app,
        filesystem,
        actor,
        json!({"parent":{"node_id":root},"name":"racing"}),
        b"r",
        "object",
    )
    .await;
    let (completed, aborted) = tokio::join!(
        fs::uploads::finalize(app, filesystem, id, actor, None),
        fs::uploads::abort(app, filesystem, id, actor),
    );
    let state = fs::uploads::status(app, filesystem, id, actor)
        .await
        .unwrap();
    match completed {
        Ok(_) => {
            assert_eq!(state["state"], "finalized");
            assert_eq!(aborted.unwrap_err().1, "UPLOAD_FINALIZED");
            assert_eq!(usage(app, bucket).await, 3);
        }
        Err(error) => {
            aborted.unwrap();
            assert_eq!(state["state"], "aborted");
            assert_eq!(error.1, "UPLOAD_NOT_ACTIVE");
            assert_eq!(usage(app, bucket).await, 2);
        }
    }
}

mod artifacts;

mod search;
