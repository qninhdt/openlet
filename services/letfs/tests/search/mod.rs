use super::*;
use std::sync::{
    Mutex,
    atomic::{AtomicBool, Ordering},
};

#[derive(Default)]
struct AI {
    embed_fail: AtomicBool,
    rerank_fail: AtomicBool,
    documents: Mutex<Vec<String>>,
}
async fn embedding(
    axum::extract::State(ai): axum::extract::State<Arc<AI>>,
) -> (StatusCode, axum::Json<Value>) {
    if ai.embed_fail.load(Ordering::SeqCst) {
        return (StatusCode::SERVICE_UNAVAILABLE, axum::Json(json!({})));
    }
    (
        StatusCode::OK,
        axum::Json(json!({"data":[{"index":0,"embedding":[1.0,0.0]}]})),
    )
}
async fn rerank(
    axum::extract::State(ai): axum::extract::State<Arc<AI>>,
    axum::Json(input): axum::Json<Value>,
) -> (StatusCode, axum::Json<Value>) {
    if ai.rerank_fail.load(Ordering::SeqCst) {
        return (StatusCode::SERVICE_UNAVAILABLE, axum::Json(json!({})));
    }
    let docs = input["documents"].as_array().unwrap();
    ai.documents
        .lock()
        .unwrap()
        .extend(docs.iter().map(|d| d.as_str().unwrap().to_owned()));
    (
        StatusCode::OK,
        axum::Json(
            json!({"results":(0..docs.len()).map(|i|json!({"index":i,"relevance_score":1.0})).collect::<Vec<_>>()}),
        ),
    )
}
fn search_request(fs: Uuid, actor: Uuid, input: Value) -> fs::search::Request {
    serde_json::from_value(json!({"scope":{"actor_id":actor,"mounts":[{"path":"/drive","filesystem_id":fs}]},"input":input})).unwrap()
}

async fn close_processing(app: &App, op: Uuid) {
    use temporalio_common::protos::temporal::api::{
        common::v1::WorkflowExecution, workflowservice::v1::TerminateWorkflowExecutionRequest,
    };
    app.temporal
        .connection()
        .workflow_service()
        .terminate_workflow_execution(temporalio_client::tonic::Request::new(
            TerminateWorkflowExecutionRequest {
                namespace: app.config.temporal_namespace.clone(),
                workflow_execution: Some(WorkflowExecution {
                    workflow_id: format!("process-file/{op}"),
                    run_id: String::new(),
                }),
                reason: "Integration test completed stages directly".into(),
                ..Default::default()
            },
        ))
        .await
        .unwrap();
}

async fn point_count(client: &reqwest::Client, qurl: &str, collection: &str, op: Uuid) -> u64 {
    let result: Value = client
        .post(format!("{qurl}/collections/{collection}/points/count"))
        .json(
            &json!({"exact":true,"filter":{"must":[{"key":"operation_id","match":{"value":op}}]}}),
        )
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    result["result"]["count"].as_u64().unwrap()
}
async fn direct(
    app: &App,
    filesystem: Uuid,
    root: Uuid,
    actor: Uuid,
    name: &str,
    text: &str,
) -> (Uuid, Uuid) {
    let node = nodes::create(
        app,
        filesystem,
        "text",
        request(
            filesystem,
            actor,
            json!({"parent":{"node_id":root},"name":name,"text":text}),
        ),
    )
    .await
    .unwrap();
    let op = fs::artifacts::status(
        app,
        filesystem,
        request(filesystem, actor, json!({"locator":{"node_id":node.id}})),
    )
    .await
    .unwrap()["operation_id"]
        .as_str()
        .unwrap()
        .parse()
        .unwrap();
    fs::enrichment::prepare(app, op).await.unwrap();
    fs::enrichment::complete(app,op,serde_json::from_value(json!({"nodes":[{"id":node.id,"path":"","metadata":{"title":"Volcano research","description":"Volcano measurements.","type":"report","context":"Volcano studies and scientific observations."}}]})).unwrap()).await.unwrap();
    (node.id, op)
}

#[tokio::test]
#[ignore = "requires Docker; run make test-integration SERVICE=letfs TEST=search"]
async fn search_live_current_ready_filters_and_lifecycle() {
    let fixture = Fixture::new().await;
    let ai = Arc::new(AI::default());
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api_url = format!("http://{}", listener.local_addr().unwrap());
    let mut tasks = tokio::task::JoinSet::new();
    let router = axum::Router::new()
        .route("/embeddings", axum::routing::post(embedding))
        .route("/rerank", axum::routing::post(rerank))
        .with_state(ai.clone());
    tasks.spawn(async move { axum::serve(listener, router).await.unwrap() });
    let qdrant = GenericImage::new(
        "qdrant/qdrant",
        "v1.20.0@sha256:9bfc89f9914fc14876a88c05270685921a55b8877b254a98bcc1cc2f0a424cd2",
    )
    .with_exposed_port(6333.tcp())
    .with_env_var("QDRANT__SERVICE__API_KEY", "isolated-test-key")
    .start()
    .await
    .unwrap();
    let qurl = format!(
        "http://{}:{}",
        qdrant.get_host().await.unwrap(),
        qdrant.get_host_port_ipv4(6333).await.unwrap()
    );
    let mut app = fixture.app.clone();
    let settings = &mut Arc::make_mut(&mut app.config).search;
    settings.openrouter_url = api_url;
    settings.openrouter_key = "test-key".into();
    settings.qdrant_url = qurl.clone();
    settings.qdrant_key = "isolated-test-key".into();
    settings.vector_dimension = 2;
    let client = reqwest::Client::builder()
        .default_headers(
            [(
                reqwest::header::HeaderName::from_static("api-key"),
                reqwest::header::HeaderValue::from_static("isolated-test-key"),
            )]
            .into_iter()
            .collect(),
        )
        .timeout(Duration::from_secs(5))
        .build()
        .unwrap();
    tokio::time::timeout(Duration::from_secs(30), async {
        loop {
            if client
                .get(format!("{qurl}/collections"))
                .send()
                .await
                .is_ok_and(|r| r.status() == 200)
            {
                break;
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    })
    .await
    .unwrap();
    client
        .put(format!("{qurl}/collections/files"))
        .json(&json!({"vectors":{"dense":{"size":2,"distance":"Cosine"}}}))
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap();
    client.put(format!("{qurl}/collections/files/index?wait=true")).json(&json!({"field_name":"text","field_schema":{"type":"text","tokenizer":"word","scoring":true}})).send().await.unwrap().error_for_status().unwrap();
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
    let (a, aop) = direct(&app, filesystem, root, actor, "A.txt", "volcano A").await;
    let (b, bop) = direct(&app, filesystem, root, actor, "B.txt", "volcano B").await;
    let first = fs::search::basic(
        &app,
        filesystem,
        search_request(filesystem, actor, json!({"query":".txt","limit":1})),
    )
    .await
    .unwrap();
    assert_eq!(first["items"].as_array().unwrap().len(), 1);
    let cursor = first["next_cursor"].as_str().unwrap();
    let second = fs::search::basic(
        &app,
        filesystem,
        search_request(
            filesystem,
            actor,
            json!({"query":".txt","limit":1,"cursor":cursor}),
        ),
    )
    .await
    .unwrap();
    assert_ne!(first["items"][0]["node_id"], second["items"][0]["node_id"]);
    assert_eq!(
        fs::search::basic(
            &app,
            filesystem,
            search_request(
                filesystem,
                Uuid::now_v7(),
                json!({"query":".txt","limit":1,"cursor":cursor})
            )
        )
        .await
        .unwrap_err()
        .1,
        "VALIDATION"
    );
    let points = vec![
        json!({"id":Uuid::now_v7(),"vector":{"dense":[1.,0.]},"payload":{"filesystem_id":filesystem,"source_id":a,"file_id":a,"operation_id":aop,"text":"volcano A"}}),
        json!({"id":Uuid::now_v7(),"vector":{"dense":[1.,0.]},"payload":{"filesystem_id":filesystem,"source_id":a,"file_id":a,"operation_id":aop,"text":"volcano A duplicate evidence"}}),
        json!({"id":Uuid::now_v7(),"vector":{"dense":[1.,0.]},"payload":{"filesystem_id":filesystem,"source_id":b,"file_id":b,"operation_id":bop,"text":"SECRET_NOT_READY volcano B"}}),
        json!({"id":Uuid::now_v7(),"vector":{"dense":[1.,0.]},"payload":{"filesystem_id":filesystem,"source_id":Uuid::now_v7(),"file_id":b,"operation_id":aop,"text":"SECRET_FOREIGN volcano"}}),
    ];
    client
        .put(format!("{qurl}/collections/files/points?wait=true"))
        .json(&json!({"points":points}))
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap();
    fs::indexing::prepare(&app, aop).await.unwrap();
    fs::indexing::complete(&app, aop).await.unwrap();
    let query = || search_request(filesystem, actor, json!({"query":"volcano"}));
    let result = fs::search::semantic(&app, filesystem, query())
        .await
        .unwrap();
    assert_eq!(result["items"].as_array().unwrap().len(), 1);
    assert_eq!(result["items"][0]["node_id"], json!(a));
    assert!(
        !ai.documents
            .lock()
            .unwrap()
            .iter()
            .any(|d| d.contains("SECRET"))
    );
    assert!(
        fs::search::semantic(
            &app,
            filesystem,
            search_request(
                filesystem,
                actor,
                json!({"query":"volcano","filters":{"type":"invoice"}})
            )
        )
        .await
        .unwrap()["items"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    ai.rerank_fail.store(true, Ordering::SeqCst);
    assert_eq!(
        fs::search::semantic(&app, filesystem, query())
            .await
            .unwrap()["degraded"],
        true
    );
    ai.rerank_fail.store(false, Ordering::SeqCst);
    ai.embed_fail.store(true, Ordering::SeqCst);
    assert_eq!(
        fs::search::semantic(&app, filesystem, query())
            .await
            .unwrap_err()
            .0,
        StatusCode::SERVICE_UNAVAILABLE
    );
    ai.embed_fail.store(false, Ordering::SeqCst);
    let mut unavailable = app.clone();
    Arc::make_mut(&mut unavailable.config).search.qdrant_url = "http://127.0.0.1:1".into();
    assert_eq!(
        fs::search::semantic(&unavailable, filesystem, query())
            .await
            .unwrap_err()
            .0,
        StatusCode::SERVICE_UNAVAILABLE
    );
    assert_eq!(
        fs::search::basic(
            &app,
            filesystem,
            search_request(Uuid::now_v7(), actor, json!({"query":"volcano"}))
        )
        .await
        .unwrap_err()
        .1,
        "NOT_FOUND"
    );
    let stat = nodes::read(
        &app,
        filesystem,
        "stat",
        request(filesystem, actor, json!({"locator":{"node_id":a}})),
    )
    .await
    .unwrap();
    let trash = fs::trash::trash(
        &app,
        filesystem,
        request(
            filesystem,
            actor,
            json!({"locator":{"node_id":a},"revision":stat["revision"]}),
        ),
    )
    .await
    .unwrap();
    assert!(
        fs::search::semantic(&app, filesystem, query())
            .await
            .unwrap()["items"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    fs::trash::restore(&app,filesystem,request(filesystem,actor,json!({"entry_id":trash["id"],"revision":trash["node"]["revision"],"parent":{"node_id":root},"name":"restored.txt"}))).await.unwrap();
    assert_eq!(
        fs::search::semantic(&app, filesystem, query())
            .await
            .unwrap()["items"][0]["filename"],
        "restored.txt"
    );
    fs::indexing::prepare(&app, bop).await.unwrap();
    let stat = nodes::read(
        &app,
        filesystem,
        "stat",
        request(filesystem, actor, json!({"locator":{"node_id":b}})),
    )
    .await
    .unwrap();
    nodes::modify(
        &app,
        filesystem,
        "replace-text",
        request(
            filesystem,
            actor,
            json!({"locator":{"node_id":b},"revision":stat["revision"],"text":"new bytes"}),
        ),
    )
    .await
    .unwrap();
    assert_eq!(
        fs::indexing::complete(&app, bop).await.unwrap_err().1,
        "SOURCE_REPLACED"
    );
    assert!(
        !ai.documents
            .lock()
            .unwrap()
            .iter()
            .any(|d| d.contains("SECRET"))
    );
    assert_eq!(
        fs::search::semantic(&app, filesystem, query())
            .await
            .unwrap()["items"]
            .as_array()
            .unwrap()
            .len(),
        1
    );

    close_processing(&app, aop).await;
    close_processing(&app, bop).await;
    let enriched_at: chrono::DateTime<chrono::Utc> =
        sqlx::query_scalar("SELECT enriched_at FROM operations WHERE id=$1")
            .bind(aop)
            .fetch_one(&app.pool)
            .await
            .unwrap();
    Arc::make_mut(&mut app.config).search.vector_collection = "files-v2".into();
    let rebuild = vec!["--mode".into(), "rebuild-index".into()];
    fs::backfill::run(&app, &rebuild).await.unwrap();
    assert_eq!(
        point_count(&client, &qurl, "files", aop).await,
        3,
        "dry run deleted vectors"
    );
    let mut apply = rebuild;
    apply.push("--apply".into());
    fs::backfill::run(&app, &apply).await.unwrap();
    assert_eq!(point_count(&client, &qurl, "files", aop).await, 3);
    let mut unavailable = app.clone();
    Arc::make_mut(&mut unavailable.config).search.qdrant_url = "http://127.0.0.1:1".into();
    assert_eq!(
        fs::indexing::prepare(&unavailable, aop)
            .await
            .unwrap_err()
            .0,
        StatusCode::SERVICE_UNAVAILABLE
    );
    let retry = sqlx::query(
        "SELECT index_state,vector_collection,index_cleanup_state FROM operations WHERE id=$1",
    )
    .bind(aop)
    .fetch_one(&app.pool)
    .await
    .unwrap();
    assert_eq!(retry.get::<&str, _>("index_state"), "pending");
    assert_eq!(retry.get::<&str, _>("vector_collection"), "files");
    assert_eq!(retry.get::<&str, _>("index_cleanup_state"), "pending");
    sqlx::query("UPDATE operations SET updated_at=now()-interval '16 minutes' WHERE id=$1")
        .bind(aop)
        .execute(&app.pool)
        .await
        .unwrap();
    fs::indexing::cleanup(&app).await.unwrap();
    assert_eq!(point_count(&client, &qurl, "files", aop).await, 3);
    assert_eq!(
        point_count(&client, &qurl, "files", bop).await,
        1,
        "rebuild deleted another operation"
    );
    assert!(fs::processing::workflow_running(&app, aop).await.unwrap());
    let snapshot = fs::indexing::prepare(&app, aop).await.unwrap();
    assert_eq!(point_count(&client, &qurl, "files", aop).await, 0);
    assert_eq!(snapshot["vector_space"]["collection"], "files-v2");
    let unchanged: chrono::DateTime<chrono::Utc> =
        sqlx::query_scalar("SELECT enriched_at FROM operations WHERE id=$1")
            .bind(aop)
            .fetch_one(&app.pool)
            .await
            .unwrap();
    assert_eq!(unchanged, enriched_at);
    close_processing(&app, aop).await;
    client
        .put(format!("{qurl}/collections/files-v2"))
        .json(&json!({"vectors":{"dense":{"size":2,"distance":"Cosine"}}}))
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap();
    client.put(format!("{qurl}/collections/files-v2/points?wait=true"))
        .json(&json!({"points":[{"id":Uuid::now_v7(),"vector":{"dense":[1.,0.]},"payload":{"operation_id":aop}}]}))
        .send().await.unwrap().error_for_status().unwrap();
    fs::indexing::complete(&app, aop).await.unwrap();
    let stat = nodes::read(
        &app,
        filesystem,
        "stat",
        request(filesystem, actor, json!({"locator":{"node_id":a}})),
    )
    .await
    .unwrap();
    let trashed = fs::trash::trash(
        &app,
        filesystem,
        request(
            filesystem,
            actor,
            json!({"locator":{"node_id":a},"revision":stat["revision"]}),
        ),
    )
    .await
    .unwrap();
    let purge = fs::deletion::prepare(
        &app,
        fs::deletion::Start {
            filesystem_id: filesystem,
            actor_id: actor,
            request_key: Uuid::now_v7(),
            entry_id: Some(serde_json::from_value(trashed["id"].clone()).unwrap()),
            revision: Some(trashed["node"]["revision"].as_str().unwrap().into()),
        },
    )
    .await
    .unwrap();
    while !fs::deletion::batch(&app, purge).await.unwrap() {}
    fs::indexing::cleanup(&app).await.unwrap();
    sqlx::query("UPDATE operations SET updated_at=now()-interval '16 minutes' WHERE index_cleanup_state='pending'")
        .execute(&app.pool).await.unwrap();
    fs::indexing::cleanup(&app).await.unwrap();
    assert_eq!(point_count(&client, &qurl, "files-v2", aop).await, 0);
    assert_eq!(point_count(&client, &qurl, "files", bop).await, 0);

    let (_, cop) = direct(&app, filesystem, root, actor, "C.txt", "volcano C").await;
    fs::indexing::prepare(&app, cop).await.unwrap();
    client.put(format!("{qurl}/collections/files-v2/points?wait=true"))
        .json(&json!({"points":[{"id":Uuid::now_v7(),"vector":{"dense":[1.,0.]},"payload":{"operation_id":cop}}]}))
        .send().await.unwrap().error_for_status().unwrap();
    fs::indexing::complete(&app, cop).await.unwrap();
    close_processing(&app, cop).await;
    let delete = fs::deletion::prepare(
        &app,
        fs::deletion::Start {
            filesystem_id: filesystem,
            actor_id: actor,
            request_key: Uuid::now_v7(),
            entry_id: None,
            revision: None,
        },
    )
    .await
    .unwrap();
    while !fs::deletion::batch(&app, delete).await.unwrap() {}
    fs::indexing::cleanup(&app).await.unwrap();
    sqlx::query("UPDATE operations SET updated_at=now()-interval '16 minutes' WHERE index_cleanup_state='pending'")
        .execute(&app.pool).await.unwrap();
    fs::indexing::cleanup(&app).await.unwrap();
    assert_eq!(point_count(&client, &qurl, "files-v2", cop).await, 0);
}

#[tokio::test]
#[ignore = "requires Docker; run make test-integration SERVICE=letfs TEST=search"]
async fn search_backfill_missing_preserves_direct_source_bytes() {
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
    let node = nodes::create(
        app,
        filesystem,
        "text",
        request(
            filesystem,
            actor,
            json!({"parent":{"node_id":root},"name":"older.md","text":"preserved bytes"}),
        ),
    )
    .await
    .unwrap();
    let prior: Uuid = sqlx::query_scalar(
        "DELETE FROM operations WHERE source_id=$1 AND kind='process-file' RETURNING id",
    )
    .bind(node.id)
    .fetch_one(&app.pool)
    .await
    .unwrap();
    close_processing(app, prior).await;
    let before = usage(app, bucket).await;
    fs::backfill::run(app, &[]).await.unwrap();
    let count: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM operations WHERE source_id=$1 AND kind='process-file'",
    )
    .bind(node.id)
    .fetch_one(&app.pool)
    .await
    .unwrap();
    assert_eq!(count, 0, "dry run created an intent");
    let apply = vec!["--apply".into(), "--limit".into(), "1".into()];
    fs::backfill::run(app, &apply).await.unwrap();
    let row = sqlx::query("SELECT id,state,workflow_started_at FROM operations WHERE source_id=$1 AND kind='process-file'")
        .bind(node.id).fetch_one(&app.pool).await.unwrap();
    let op: Uuid = row.get("id");
    assert_eq!(row.get::<&str, _>("state"), "succeeded");
    assert!(
        row.get::<Option<chrono::DateTime<chrono::Utc>>, _>("workflow_started_at")
            .is_some()
    );
    fs::backfill::run(app, &apply).await.unwrap();
    let current: Uuid =
        sqlx::query_scalar("SELECT id FROM operations WHERE source_id=$1 AND kind='process-file'")
            .bind(node.id)
            .fetch_one(&app.pool)
            .await
            .unwrap();
    assert_eq!(current, op);
    let bytes: Vec<u8> = sqlx::query_scalar("SELECT inline_bytes FROM file_data WHERE node_id=$1")
        .bind(node.id)
        .fetch_one(&app.pool)
        .await
        .unwrap();
    assert_eq!(bytes, b"preserved bytes");
    assert_eq!(usage(app, bucket).await, before);
    assert!(
        fs::backfill::run(app, &["--limit".into(), "0".into()])
            .await
            .is_err()
    );
}
