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
mod copy;
mod deletion;

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
            "/docker-entrypoint-initdb.d/10-baseline.sql",
            Path::new(env!("CARGO_MANIFEST_DIR")).join("migrations/0001_initial.sql"),
        )
        .with_startup_timeout(Duration::from_secs(60))
        .start()
        .await
        .unwrap();
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
            archive: Default::default(),
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
            archive_slots: Arc::new(tokio::sync::Semaphore::new(
                config.archive.max_concurrent as usize,
            )),
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
        let filesystem = fs::ensure_filesystem(
            &self.app.pool,
            fs::EnsureFilesystem {
                bucket_id: bucket,
                provision_key: Uuid::now_v7().to_string(),
                root_name: "root".into(),
            },
            1000,
        )
        .await
        .unwrap();
        (filesystem.id, filesystem.root_id.unwrap())
    }
}

fn request(fs: Uuid, actor: Uuid, mut input: Value) -> nodes::Request {
    let content = input
        .as_object_mut()
        .and_then(|v| v.remove("text"))
        .map(|v| v.as_str().unwrap().as_bytes().to_vec());
    let mut request: nodes::Request = serde_json::from_value(json!({
        "scope": {
            "actor_id": actor,
            "mounts": [{"path": "/drive", "filesystem_id": fs}]
        },
        "input": input
    }))
    .unwrap();
    request.input.content = content;
    request
}

fn create_request(kind: &str, r: nodes::Request) -> nodes::Create {
    use base64::{Engine, prelude::BASE64_STANDARD};
    let mut input = json!({"kind":if kind=="text" {"file"} else {"directory"},"parent":r.input.parent,"name":r.input.name,"request_key":r.input.request_key.unwrap_or_else(Uuid::now_v7)});
    if kind == "text" {
        input["content_base64"] = json!(BASE64_STANDARD.encode(r.input.content.unwrap()));
        input["media_type"] = json!(fs::enrichment::media_type(input["name"].as_str().unwrap()));
    }
    serde_json::from_value(json!({"scope":r.scope,"input":input})).unwrap()
}

async fn usage(app: &App, bucket: Uuid) -> i64 {
    sqlx::query_scalar("SELECT used_bytes FROM quota_buckets WHERE id=$1")
        .bind(bucket)
        .fetch_one(&app.pool)
        .await
        .unwrap()
}

#[tokio::test]
#[ignore = "requires Docker; run pnpm --filter @openlet/letfs test:integration"]
async fn file_input_boundaries() {
    let fixture = Fixture::new().await;
    let mut app = fixture.app.clone();
    let mut config = (*app.config).clone();
    config.max_file_bytes = 4;
    app.config = Arc::new(config);
    let bucket = fs::ensure_bucket(
        &app.pool,
        fs::EnsureBucket {
            provision_key: Uuid::now_v7().to_string(),
            limit_bytes: "1000".into(),
        },
    )
    .await
    .unwrap()
    .id;
    let (fs, root) = fixture.filesystem(bucket).await;
    let actor = Uuid::now_v7();
    let node = nodes::create(
        &app,
        fs,
        create_request(
            "text",
            request(
                fs,
                actor,
                json!({"parent":{"node_id":root},"name":"note","text":"1234"}),
            ),
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
        assert_eq!(nodes::create(&app,fs,create_request("text",request(fs,actor,json!({"parent":{"path":path,"expected_parent_id":node.id},"name":"forbidden","text":"x"})))).await.unwrap_err().1,"NOT_DIRECTORY");
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
    let malformed = serde_json::from_value::<fs::copy::Input>(
        json!({"source_id":node.id,"parent_id":root,"name":"copy","revision":"1","request_key":Uuid::now_v7(),"text":"unexpected body"}),
    );
    assert!(malformed.is_err());
    let oversized = nodes::create(
        &app,
        fs,
        create_request(
            "text",
            request(
                fs,
                actor,
                json!({"parent":{"node_id":root},"name":"large","text":"12345"}),
            ),
        ),
    )
    .await;
    assert!(matches!(oversized, Err(ref error) if error.0 == StatusCode::PAYLOAD_TOO_LARGE));
    let oversized = nodes::modify(
        &app,
        fs,
        "replace-content",
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
#[ignore = "requires Docker; run pnpm --filter @openlet/letfs test:integration"]
async fn filesystem_and_storage_integration() {
    let fixture = Fixture::new().await;
    let app = &fixture.app;
    let bucket = fs::ensure_bucket(
        &app.pool,
        fs::EnsureBucket {
            provision_key: Uuid::now_v7().to_string(),
            limit_bytes: "10000000".into(),
        },
    )
    .await
    .unwrap()
    .id;
    let (fs, root) = fixture.filesystem(bucket).await;
    let actor = Uuid::now_v7();
    let text = "\u{feff}exact\r\nTiếng Việt";
    let node = nodes::create(app,fs,create_request("text",request(
            fs,
            actor,
            json!({"parent":{"node_id":root},"name":"note.txt","text":text,"request_key":Uuid::now_v7()}),
        )))
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
    let bytes: Vec<u8> = sqlx::query_scalar("SELECT inline_bytes FROM files WHERE node_id=$1")
        .bind(node.id)
        .fetch_one(&app.pool)
        .await
        .unwrap();
    assert_eq!(bytes, text.as_bytes());
    let stale = nodes::modify(
        app,
        fs,
        "replace-content",
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
        "replace-content",
        request(
            fs,
            actor,
            json!({"locator":{"path":"/drive/note.txt","expected_node_id":Uuid::now_v7()},"revision":node.revision,"text":"lost"}),
        ),
    )
    .await
    .unwrap_err();
    assert_eq!(wrong_identity.1, "TARGET_MISMATCH");
    let duplicate = nodes::create(app,fs,create_request("text",request(
            fs,
            actor,
            json!({"parent":{"node_id":root},"name":"note.txt","text":"duplicate","request_key":Uuid::now_v7()}),
        )))
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
    let tight = fs::ensure_bucket(
        &app.pool,
        fs::EnsureBucket {
            provision_key: Uuid::now_v7().to_string(),
            limit_bytes: "5".into(),
        },
    )
    .await
    .unwrap()
    .id;
    let (left, left_root) = fixture.filesystem(tight).await;
    let (right, right_root) = fixture.filesystem(tight).await;
    let (a, b) = tokio::join!(
        nodes::create(
            app,
            left,
            create_request(
                "text",
                request(
                    left,
                    actor,
                    json!({"parent":{"node_id":left_root},"name":"a","text":"1234","request_key":Uuid::now_v7()})
                )
            )
        ),
        nodes::create(
            app,
            right,
            create_request(
                "text",
                request(
                    right,
                    actor,
                    json!({"parent":{"node_id":right_root},"name":"b","text":"5678","request_key":Uuid::now_v7()})
                )
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
        assert_eq!(transferred["status"], "open");
        let finalized = fs::uploads::finalize(app, fs, id, actor, None)
            .await
            .unwrap();
        let repeated = fs::uploads::finalize(app, fs, id, actor, None)
            .await
            .unwrap();
        assert_eq!(finalized, repeated);
        let node: Uuid = serde_json::from_value(finalized["node_id"].clone()).unwrap();
        let row =
            sqlx::query("SELECT storage_kind,inline_bytes,object_key FROM files WHERE node_id=$1")
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
#[ignore = "requires Docker; run pnpm --filter @openlet/letfs test:integration"]
async fn direct_storage_download() {
    let fixture = Fixture::new().await;
    let app = &fixture.app;
    let bucket = fs::ensure_bucket(
        &app.pool,
        fs::EnsureBucket {
            provision_key: Uuid::now_v7().to_string(),
            limit_bytes: "1000000".into(),
        },
    )
    .await
    .unwrap()
    .id;
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
        create_request(
            "text",
            request(
                filesystem,
                actor,
                json!({"parent":{"node_id":root},"name":"note.txt","text":"hello"}),
            ),
        ),
    )
    .await
    .unwrap();
    // Worker descriptors must work when the browser-facing S3 hostname is unreachable here.
    let mut internal = app.clone();
    Arc::make_mut(&mut internal.config).storage.signing_endpoint =
        "http://external.invalid:8333".into();
    let (_, public_signer) = letfs::storage::build(&internal.config).unwrap();
    internal.signer = public_signer;
    let generation = sqlx::query_scalar("SELECT desired_generation FROM files WHERE node_id=$1")
        .bind(node)
        .fetch_one(&app.pool)
        .await
        .unwrap();
    let attempt = fs::processing::Attempt {
        source: fs::processing::Generation {
            file_id: node,
            generation,
        },
        number: 1,
        attempt_id: Uuid::now_v7(),
    };
    let source = fs::processing::prepare(&internal, &attempt).await.unwrap();
    let body = reqwest::get(source["source"]["url"].as_str().unwrap())
        .await
        .unwrap();
    assert_eq!(body.status(), StatusCode::OK);
    assert_eq!(body.bytes().await.unwrap().as_ref(), bytes);
    let output = fs::processing::prepare_output(&internal,&attempt,serde_json::from_value(json!({
        "path":"image.png","storage":"object","size_bytes":"5","content_md5":"XUFAKrxLKna5cZ2REBfFkg=="
    })).unwrap()).await.unwrap();
    let mut put = reqwest::Client::new()
        .put(output["transfer"]["url"].as_str().unwrap())
        .body("hello");
    for (key, value) in output["transfer"]["headers"].as_object().unwrap() {
        put = put.header(key, value.as_str().unwrap());
    }
    assert_eq!(put.send().await.unwrap().status(), StatusCode::OK);
    fs::processing::abort(&internal, &attempt, "PROCESSING_CANCELLED")
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
    let endpoint =
        format!("http://{address}/internal/v1/filesystems/{filesystem}/nodes/{node}/content");
    let result = async {
        let response = client
            .get(format!("{endpoint}?revision=1"))
            .bearer_auth(&app.config.workspace_token)
            .header("x-actor-id", actor.to_string())
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
            .get(format!("{endpoint}?revision=1"))
            .bearer_auth(&app.config.workspace_token)
            .header("x-actor-id", actor.to_string())
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
            .get(format!("{endpoint}?revision=2"))
            .bearer_auth(&app.config.workspace_token)
            .header("x-actor-id", actor.to_string())
            .send()
            .await
            .unwrap();
        assert_eq!(mismatch.status(), StatusCode::PRECONDITION_FAILED);
        let inline_response = client
            .get(format!(
                "http://{address}/internal/v1/filesystems/{filesystem}/nodes/{}/content",
                inline.id
            ))
            .bearer_auth(&app.config.workspace_token)
            .header("x-actor-id", actor.to_string())
            .header("range", "bytes=1-2")
            .send()
            .await
            .unwrap();
        assert_eq!(inline_response.status(), StatusCode::PARTIAL_CONTENT);
        assert_eq!(inline_response.headers()["content-type"], "text/plain");
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
#[ignore = "requires Docker; run pnpm --filter @openlet/letfs test:integration"]
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
        fs::uploads::status(app, filesystem, id, actor)
            .await
            .unwrap()
    };
    (id, transferred)
}

#[tokio::test]
#[ignore = "requires Docker; run pnpm --filter @openlet/letfs test:integration"]
async fn direct_storage_sessions_and_publication() {
    let fixture = Fixture::new().await;
    let app = &fixture.app;
    let bucket = fs::ensure_bucket(
        &app.pool,
        fs::EnsureBucket {
            provision_key: Uuid::now_v7().to_string(),
            limit_bytes: "100000000".into(),
        },
    )
    .await
    .unwrap()
    .id;
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
        let pinned: bool = sqlx::query_scalar("SELECT completed_at IS NULL AND expires_at IS NULL FROM idempotency_keys WHERE operation='create-upload' AND request_key=$1")
            .bind(key.to_string()).fetch_one(&app.pool).await.unwrap();
        assert!(pinned);
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
        let bytes: Vec<u8> = sqlx::query_scalar("SELECT inline_bytes FROM files WHERE node_id=$1")
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
        let retained: bool = sqlx::query_scalar("SELECT completed_at IS NOT NULL AND expires_at-completed_at=interval '24 hours' FROM idempotency_keys WHERE operation='create-upload' AND request_key=$1")
            .bind(key.to_string()).fetch_one(&app.pool).await.unwrap();
        assert!(retained);
        sqlx::query("UPDATE idempotency_keys SET completed_at=now()-interval '24 hours 1 second',expires_at=now()-interval '1 second' WHERE operation='create-upload' AND request_key=$1")
            .bind(key.to_string()).execute(&app.pool).await.unwrap();
        let fresh = fs::uploads::create(app,filesystem,request(filesystem,actor,json!({
            "parent":{"node_id":root},"name":format!("renewed-{key}"),"storage":"inline","size_bytes":"0","request_key":key
        }))).await.unwrap();
        assert_ne!(fresh["id"], prepared["id"]);
        let fresh_id = serde_json::from_value(fresh["id"].clone()).unwrap();
        fs::uploads::abort(app, filesystem, fresh_id, actor)
            .await
            .unwrap();
        let before: chrono::DateTime<chrono::Utc> = sqlx::query_scalar("SELECT expires_at FROM idempotency_keys WHERE operation='create-upload' AND request_key=$1")
            .bind(key.to_string()).fetch_one(&app.pool).await.unwrap();
        fs::uploads::abort(app, filesystem, fresh_id, actor)
            .await
            .unwrap();
        let after: chrono::DateTime<chrono::Utc> = sqlx::query_scalar("SELECT expires_at FROM idempotency_keys WHERE operation='create-upload' AND request_key=$1")
            .bind(key.to_string()).fetch_one(&app.pool).await.unwrap();
        assert_eq!(before, after);
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
        create_request(
            "text",
            request(
                filesystem,
                actor,
                json!({"parent":{"node_id":root},"name":"source","text":"old"}),
            ),
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
    let before: Vec<u8> = sqlx::query_scalar("SELECT inline_bytes FROM files WHERE node_id=$1")
        .bind(source.id)
        .fetch_one(&app.pool)
        .await
        .unwrap();
    assert_eq!(before, b"old");
    nodes::modify(
        app,
        filesystem,
        "replace-content",
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
    let current: Vec<u8> = sqlx::query_scalar("SELECT inline_bytes FROM files WHERE node_id=$1")
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
    let previous_key: String = sqlx::query_scalar("SELECT object_key FROM files WHERE node_id=$1")
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
    let next_key: String = sqlx::query_scalar("SELECT object_key FROM files WHERE node_id=$1")
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
    let numbers = (1..=data.chunks(part_size).len() as u32).collect();
    for invalid in [vec![], vec![0], vec![4], vec![1, 1], vec![1; 65]] {
        assert_eq!(
            fs::uploads::part_urls(app, filesystem, id, actor, invalid)
                .await
                .unwrap_err()
                .0,
            StatusCode::BAD_REQUEST
        );
    }
    let urls = fs::uploads::part_urls(app, filesystem, id, actor, numbers)
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
    let key: String = sqlx::query_scalar("SELECT object_key FROM files WHERE node_id=$1")
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
        fs::uploads::part_urls(app, filesystem, id, actor, vec![1])
            .await
            .is_err()
    );
}

#[tokio::test]
#[ignore = "requires Docker; run pnpm --filter @openlet/letfs test:integration"]
async fn direct_storage_commit_quota_and_abort() {
    let fixture = Fixture::new().await;
    let app = &fixture.app;
    let bucket = fs::ensure_bucket(
        &app.pool,
        fs::EnsureBucket {
            provision_key: Uuid::now_v7().to_string(),
            limit_bytes: "3".into(),
        },
    )
    .await
    .unwrap()
    .id;
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
    assert_eq!(state["status"], "aborted");
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
            assert_eq!(state["status"], "finalized");
            assert_eq!(aborted.unwrap_err().1, "UPLOAD_FINALIZED");
            assert_eq!(usage(app, bucket).await, 3);
        }
        Err(error) => {
            aborted.unwrap();
            assert_eq!(state["status"], "aborted");
            assert_eq!(error.1, "UPLOAD_NOT_ACTIVE");
            assert_eq!(usage(app, bucket).await, 2);
        }
    }
    sqlx::query("UPDATE object_deletions d SET state='deleted' FROM uploads u WHERE u.id=$1 AND d.object_key=u.candidate_key")
        .bind(second).execute(&app.pool).await.unwrap();
    let mut limited = app.clone();
    Arc::make_mut(&mut limited.config).max_cleanup_backlog = 1;
    let refused = fs::uploads::create(&limited,filesystem,request(filesystem,actor,json!({
        "parent":{"node_id":root},"name":"backpressure","storage":"object","size_bytes":"1","content_md5":"DMF1ucDxtqgxw5niaXcmYQ==","request_key":Uuid::now_v7()
    }))).await.unwrap_err();
    assert_eq!(
        refused.1, "RESOURCE_LIMIT",
        "an acknowledged delete must not hide unresolved write evidence from admission bounds"
    );
}

mod artifacts;

mod search;

#[tokio::test]
#[ignore = "requires Docker; run pnpm --filter @openlet/letfs test:integration"]
async fn workspace_provisioning_receipts_pin_results_and_enforce_owner_scope() {
    use letfs::fs::provisioning as owner;
    let fixture = Fixture::new().await;
    let pool = &fixture.app.pool;
    let workspace = Uuid::now_v7();
    let input = || owner::BucketInput {
        workspace_id: workspace,
        limit_bytes: "1024".into(),
    };
    let (left, right) = tokio::join!(owner::bucket(pool, input()), owner::bucket(pool, input()));
    let bucket = left.unwrap();
    assert_eq!(bucket.id, right.unwrap().id);
    assert!(
        owner::bucket(
            pool,
            owner::BucketInput {
                workspace_id: workspace,
                limit_bytes: "1025".into()
            }
        )
        .await
        .is_err()
    );
    let filesystem = owner::filesystem(
        pool,
        owner::FilesystemInput {
            workspace_id: workspace,
            bucket_id: bucket.id,
        },
        100,
    )
    .await
    .unwrap();
    let again = owner::filesystem(
        pool,
        owner::FilesystemInput {
            workspace_id: workspace,
            bucket_id: bucket.id,
        },
        100,
    )
    .await
    .unwrap();
    assert_eq!(filesystem.id, again.id);
    assert_eq!(filesystem.root_id, again.root_id);
    // A lost Activity acknowledgment can be retried beyond 24h while its parent is active.
    owner::prune_receipts(pool).await.unwrap();
    let pinned: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM idempotency_keys WHERE completed_at IS NULL AND expires_at IS NULL",
    )
    .fetch_one(pool)
    .await
    .unwrap();
    assert_eq!(pinned, 2);
    assert!(
        owner::freeze(
            pool,
            owner::BucketScope {
                workspace_id: Uuid::now_v7(),
                bucket_id: bucket.id
            }
        )
        .await
        .is_err()
    );
    let release = || owner::Provisioned {
        workspace_id: workspace,
        bucket_id: bucket.id,
        filesystem_id: filesystem.id,
        root_id: filesystem.root_id.unwrap(),
    };
    owner::release(pool, release()).await.unwrap();
    owner::release(pool, release()).await.unwrap();
    let released: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM idempotency_keys WHERE expires_at=completed_at+interval '24 hours'",
    )
    .fetch_one(pool)
    .await
    .unwrap();
    assert_eq!(released, 2);
    sqlx::query("UPDATE idempotency_keys SET completed_at=now()-interval '25 hours',expires_at=now()-interval '1 hour'").execute(pool).await.unwrap();
    owner::prune_receipts(pool).await.unwrap();
    assert_eq!(bucket.id, owner::bucket(pool, input()).await.unwrap().id);
    owner::freeze(
        pool,
        owner::BucketScope {
            workspace_id: workspace,
            bucket_id: bucket.id,
        },
    )
    .await
    .unwrap();
    let ids = owner::filesystems(
        pool,
        owner::FilesystemPage {
            workspace_id: workspace,
            bucket_id: bucket.id,
            after: Uuid::nil(),
        },
    )
    .await
    .unwrap();
    assert_eq!(ids, vec![filesystem.id]);
    assert!(
        owner::complete(
            pool,
            owner::BucketScope {
                workspace_id: workspace,
                bucket_id: bucket.id
            }
        )
        .await
        .is_err()
    );
    assert!(owner::bucket(pool, input()).await.is_err());
    let operation = fs::deletion::prepare(
        &fixture.app,
        fs::deletion::Start {
            filesystem_id: filesystem.id,
            actor_id: Uuid::now_v7(),
            entry_id: None,
            revision: None,
        },
    )
    .await
    .unwrap();
    while !fs::deletion::batch(&fixture.app, &operation).await.unwrap() {}
    // Mapping acknowledgment may arrive after a concurrent deletion removed the root.
    owner::release(pool, release()).await.unwrap();
    owner::complete(
        pool,
        owner::BucketScope {
            workspace_id: workspace,
            bucket_id: bucket.id,
        },
    )
    .await
    .unwrap();
    assert!(owner::bucket(pool, input()).await.is_err());
}

#[tokio::test]
#[ignore = "requires Docker; run pnpm --filter @openlet/letfs test:integration"]
async fn failed_workspace_cleanup_fences_late_provisioning_and_releases_receipts() {
    use letfs::fs::provisioning as owner;
    let fixture = Fixture::new().await;
    let pool = &fixture.app.pool;
    for has_bucket in [false, true] {
        let workspace = Uuid::now_v7();
        let input = || owner::BucketInput {
            workspace_id: workspace,
            limit_bytes: "1024".into(),
        };
        let admitted = if has_bucket {
            Some(owner::bucket(pool, input()).await.unwrap().id)
        } else {
            None
        };
        let bucket = owner::freeze(
            pool,
            owner::BucketScope {
                workspace_id: workspace,
                bucket_id: Uuid::nil(),
            },
        )
        .await
        .unwrap();
        if let Some(admitted) = admitted {
            assert_eq!(admitted, bucket);
        }
        assert_eq!(
            bucket,
            owner::freeze(
                pool,
                owner::BucketScope {
                    workspace_id: workspace,
                    bucket_id: Uuid::nil()
                }
            )
            .await
            .unwrap()
        );
        assert!(owner::bucket(pool, input()).await.is_err());
        owner::complete(
            pool,
            owner::BucketScope {
                workspace_id: workspace,
                bucket_id: bucket,
            },
        )
        .await
        .unwrap();
        assert!(owner::bucket(pool, input()).await.is_err());
    }
    let pinned: i64 =
        sqlx::query_scalar("SELECT count(*) FROM idempotency_keys WHERE completed_at IS NULL")
            .fetch_one(pool)
            .await
            .unwrap();
    assert_eq!(pinned, 0);
}

#[tokio::test]
#[ignore = "requires Docker; run pnpm --filter @openlet/letfs test:integration"]
async fn strict_node_creation_receipts_are_atomic_scoped_and_expire_without_recreation() {
    use base64::{Engine, prelude::BASE64_STANDARD};
    let f = Fixture::new().await;
    let app = &f.app;
    let bucket = fs::ensure_bucket(
        &app.pool,
        fs::EnsureBucket {
            provision_key: Uuid::now_v7().to_string(),
            limit_bytes: "1000000".into(),
        },
    )
    .await
    .unwrap()
    .id;
    let (filesystem, root) = f.filesystem(bucket).await;
    let actor = Uuid::now_v7();
    let key = Uuid::now_v7();
    let bytes = [0, 255, 13, 10, 65, 0];
    let input:nodes::Create=serde_json::from_value(json!({"scope":request(filesystem,actor,json!({})).scope,"input":{"kind":"file","parent":{"node_id":root},"name":"payload.bin","request_key":key,"content_base64":BASE64_STANDARD.encode(bytes),"media_type":"application/octet-stream"}})).unwrap();
    let results =
        futures::future::join_all((0..4).map(|_| nodes::create(app, filesystem, input.clone())))
            .await;
    let node = results[0].as_ref().unwrap();
    assert!(results.iter().all(|r| r.as_ref().unwrap().id == node.id));
    assert_eq!(usage(app, bucket).await, bytes.len() as i64);
    let data: Vec<u8> = sqlx::query_scalar("SELECT inline_bytes FROM files WHERE node_id=$1")
        .bind(node.id)
        .fetch_one(&app.pool)
        .await
        .unwrap();
    assert_eq!(data, bytes);
    let mut changed = input.clone();
    if let nodes::CreateInput::File { name, .. } = &mut changed.input {
        *name = "changed.bin".into()
    }
    assert_eq!(
        nodes::create(app, filesystem, changed.clone())
            .await
            .unwrap_err()
            .1,
        "IDEMPOTENCY_CONFLICT"
    );
    let mut collision = input.clone();
    if let nodes::CreateInput::File { request_key, .. } = &mut collision.input {
        *request_key = Uuid::now_v7()
    }
    assert_eq!(
        nodes::create(app, filesystem, collision)
            .await
            .unwrap_err()
            .1,
        "NAME_CONFLICT"
    );
    nodes::modify(
        app,
        filesystem,
        "rename",
        request(
            filesystem,
            actor,
            json!({"locator":{"node_id":node.id},"revision":node.revision,"name":"renamed.bin"}),
        ),
    )
    .await
    .unwrap();
    let replay = nodes::create(app, filesystem, input.clone()).await.unwrap();
    assert_eq!((replay.id, replay.revision.as_str()), (node.id, "1"));
    let mut denied = input.clone();
    denied.scope.mounts.clear();
    assert_eq!(
        nodes::create(app, filesystem, denied).await.unwrap_err().1,
        "VALIDATION"
    );
    sqlx::query("UPDATE idempotency_keys SET completed_at=now()-interval '25 hours',expires_at=now()-interval '1 hour' WHERE request_key=$1 AND operation='create-node'").bind(key.to_string()).execute(&app.pool).await.unwrap();
    let fresh = nodes::create(app, filesystem, changed).await.unwrap();
    assert_ne!(fresh.id, node.id);
    assert_eq!(usage(app, bucket).await, (2 * bytes.len()) as i64);
    let dir = nodes::create(
        app,
        filesystem,
        create_request(
            "directories",
            request(
                filesystem,
                actor,
                json!({"parent":{"node_id":root},"name":"folder"}),
            ),
        ),
    )
    .await
    .unwrap();
    let dto = json!(dir);
    for field in [
        "media_type",
        "title",
        "description",
        "semantic_type",
        "context",
    ] {
        assert!(dto.get(field).is_none(), "directory exposed {field}")
    }
    let directory_files: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM nodes n JOIN files f ON f.node_id=n.id WHERE n.kind='directory'",
    )
    .fetch_one(&app.pool)
    .await
    .unwrap();
    assert_eq!(directory_files, 0);
    let old_columns:i64=sqlx::query_scalar("SELECT count(*) FROM information_schema.columns WHERE table_name='nodes' AND column_name IN ('media_type','title','description','semantic_type','context')").fetch_one(&app.pool).await.unwrap();
    assert_eq!(old_columns, 0);
}
