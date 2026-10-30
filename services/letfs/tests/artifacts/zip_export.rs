use super::*;
use fs::exports::{self, Start};
use std::collections::BTreeMap;

fn selection(fs: Uuid, actor: Uuid, ids: &[Uuid], artifacts: bool) -> Start {
    let request = request(fs, actor, json!({}));
    serde_json::from_value(json!({"filesystem_id":fs,"scope":request.scope,"selection":{"locators":ids.iter().map(|id|json!({"node_id":id})).collect::<Vec<_>>(),"artifacts":artifacts,"request_key":Uuid::now_v7()}})).unwrap()
}
async fn archive(app: &App, attempt: &exports::Attempt) -> BTreeMap<String, Vec<u8>> {
    let size = letfs::storage::archive::build(app, attempt).await.unwrap();
    exports::publish(app, attempt, size).await.unwrap();
    let bytes = app
        .storage
        .get(&ObjectPath::from(attempt.key.as_str()))
        .await
        .unwrap()
        .bytes()
        .await
        .unwrap();
    assert_eq!(bytes.len() as i64, size);
    use futures::AsyncReadExt;
    let mut reader = async_zip::base::read1::seek::ZipArchiveReader::open(
        futures::io::Cursor::new(bytes.to_vec()),
    )
    .await
    .unwrap();
    assert!(reader.ceocdr().is_zip64());
    let names = reader
        .cdrs()
        .iter()
        .map(|entry| entry.insecure_file_name.as_str().unwrap().to_owned())
        .collect::<Vec<_>>();
    let mut result = BTreeMap::new();
    for (index, name) in names.into_iter().enumerate() {
        let mut data = Vec::new();
        reader
            .file(index)
            .await
            .unwrap()
            .read_to_end(&mut data)
            .await
            .unwrap();
        result.insert(name, data);
    }
    result
}
#[tokio::test]
#[ignore = "requires Docker; run make test-integration SERVICE=letfs TEST=zip-export"]
async fn zip_export_originals_artifacts_range_expiry_and_accounting() {
    let f = Fixture::new().await;
    let app = &f.app;
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
    let (fs, root) = f.filesystem(bucket).await;
    let actor = Uuid::now_v7();
    let folder = artifact_child(app, fs, root, "folder", None).await;
    let empty = artifact_child(app, fs, folder, "empty", None).await;
    let file = artifact_child(app, fs, folder, "report.pdf", Some(b"original")).await;
    let derived = artifact_child(app, fs, file, "001-intro.md", Some(b"derived")).await;
    let (upload, _) = create_and_transfer(
        app,
        fs,
        actor,
        json!({"parent":{"node_id":folder},"name":"photo.png"}),
        b"image",
        "object",
    )
    .await;
    fs::uploads::finalize(app, fs, upload, actor, None)
        .await
        .unwrap();
    let charged = usage(app, bucket).await;
    let start = selection(fs, actor, &[folder, empty, file], false);
    let attempt = exports::prepare(app, &start, 1, Uuid::now_v7())
        .await
        .unwrap()
        .unwrap();
    let items = archive(app, &attempt).await;
    assert_eq!(
        items,
        BTreeMap::from([
            ("folder/".into(), vec![]),
            ("folder/empty/".into(), vec![]),
            ("folder/report.pdf".into(), b"original".to_vec()),
            ("folder/photo.png".into(), b"image".to_vec())
        ])
    );
    assert_eq!(usage(app, bucket).await, charged);
    assert!(
        exports::prepare(app, &start, 2, Uuid::now_v7())
            .await
            .unwrap()
            .is_none()
    );
    let descriptor = exports::status(app, fs, actor, attempt.operation, true)
        .await
        .unwrap();
    let url = descriptor["download"]["url"].as_str().unwrap();
    let response = reqwest::Client::new()
        .get(url)
        .header("Range", "bytes=0-3")
        .send()
        .await
        .unwrap();
    assert_eq!(response.status().as_u16(), 206);
    assert_eq!(response.bytes().await.unwrap().as_ref(), b"PK\x03\x04");
    assert_eq!(
        exports::status(app, fs, Uuid::now_v7(), attempt.operation, true)
            .await
            .unwrap_err()
            .1,
        "NOT_FOUND"
    );
    let mut conflict = start.clone();
    conflict.selection.artifacts = true;
    assert_eq!(
        exports::existing(app, &conflict).await.unwrap_err().1,
        "IDEMPOTENCY_CONFLICT"
    );
    let separate = selection(fs, actor, &[file], true);
    let artifacts = exports::prepare(app, &separate, 1, Uuid::now_v7())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(artifacts.snapshot.name, "report.pdf-artifacts.zip");
    assert_eq!(
        archive(app, &artifacts).await,
        BTreeMap::from([("001-intro.md".into(), b"derived".to_vec())])
    );
    let copied = selection(fs, actor, &[derived], false);
    let direct = exports::prepare(app, &copied, 1, Uuid::now_v7())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        archive(app, &direct).await,
        BTreeMap::from([("001-intro.md".into(), b"derived".to_vec())])
    );
    sqlx::query("UPDATE export_attempts SET expires_at=now()-interval '1 second' WHERE id=$1")
        .bind(attempt.id)
        .execute(&app.pool)
        .await
        .unwrap();
    assert_eq!(
        exports::status(app, fs, actor, attempt.operation, false)
            .await
            .unwrap()["state"],
        "expired"
    );
    assert_eq!(
        exports::status(app, fs, actor, attempt.operation, true)
            .await
            .unwrap_err()
            .1,
        "EXPORT_NOT_READY"
    );
}
#[tokio::test]
#[ignore = "requires Docker; run make test-integration SERVICE=letfs TEST=zip-export"]
async fn zip_export_stale_attempt_changed_input_and_bounded_output() {
    let f = Fixture::new().await;
    let mut app = f.app.clone();
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
    let (fs, root) = f.filesystem(bucket).await;
    let actor = Uuid::now_v7();
    let folder = artifact_child(&app, fs, root, "folder", None).await;
    let file = artifact_child(&app, fs, folder, "text.md", Some(b"before")).await;
    let start = selection(fs, actor, &[folder], false);
    let first = exports::prepare(&app, &start, 1, Uuid::now_v7())
        .await
        .unwrap()
        .unwrap();
    let second = exports::prepare(&app, &start, 2, Uuid::now_v7())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        exports::publish(&app, &first, 1).await.unwrap_err().1,
        "STALE_EXPORT_ATTEMPT"
    );
    let size = letfs::storage::archive::build(&app, &second).await.unwrap();
    nodes::modify(
        &app,
        fs,
        "replace-text",
        request(
            fs,
            actor,
            json!({"locator":{"node_id":file},"revision":"1","text":"after"}),
        ),
    )
    .await
    .unwrap();
    assert_eq!(
        exports::publish(&app, &second, size).await.unwrap_err().1,
        "SOURCE_CHANGED"
    );
    assert_eq!(
        exports::status(&app, fs, actor, second.operation, true)
            .await
            .unwrap_err()
            .1,
        "EXPORT_NOT_READY"
    );
    Arc::make_mut(&mut app.config).exports.max_output_bytes = 1;
    let third = exports::prepare(&app, &start, 3, Uuid::now_v7())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        letfs::storage::archive::build(&app, &third)
            .await
            .unwrap_err()
            .1,
        "RESOURCE_LIMIT"
    );
    assert!(
        sqlx::query_scalar::<_, bool>(
            "SELECT EXISTS(SELECT 1 FROM object_deletions WHERE object_key=$1 AND ambiguous_write)"
        )
        .bind(&third.key)
        .fetch_one(&app.pool)
        .await
        .unwrap()
    );
    Arc::make_mut(&mut app.config).exports.max_entries = 1;
    assert_eq!(
        exports::preflight(&app, &start).await.unwrap_err().1,
        "RESOURCE_LIMIT"
    );
}

#[tokio::test]
#[ignore = "requires Docker; run make test-integration SERVICE=letfs TEST=zip-export"]
async fn zip_export_publication_cannot_resurrect_a_failed_operation() {
    let f = Fixture::new().await;
    let app = &f.app;
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
    let (fs, root) = f.filesystem(bucket).await;
    let file = artifact_child(app, fs, root, "test.txt", Some(b"data")).await;
    let attempt = exports::prepare(
        app,
        &selection(fs, Uuid::now_v7(), &[file], false),
        1,
        Uuid::now_v7(),
    )
    .await
    .unwrap()
    .unwrap();
    let size = letfs::storage::archive::build(app, &attempt).await.unwrap();
    let operation = attempt.operation;
    let mut tx = app.pool.begin().await.unwrap();
    sqlx::query("SELECT id FROM operations WHERE id=$1 FOR UPDATE")
        .bind(operation)
        .execute(&mut *tx)
        .await
        .unwrap();
    let blocker: i32 = sqlx::query_scalar("SELECT pg_backend_pid()")
        .fetch_one(&mut *tx)
        .await
        .unwrap();
    let publisher_app = app.clone();
    let publisher =
        tokio::spawn(async move { exports::publish(&publisher_app, &attempt, size).await });
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let blocked: bool = sqlx::query_scalar(
                "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE $1=ANY(pg_blocking_pids(pid)))",
            )
            .bind(blocker)
            .fetch_one(&app.pool)
            .await
            .unwrap();
            if blocked {
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("publisher must reach the operation row lock");
    sqlx::query("UPDATE operations SET state='failed',error_code='EXPORT_FAILED' WHERE id=$1")
        .bind(operation)
        .execute(&mut *tx)
        .await
        .unwrap();
    tx.commit().await.unwrap();
    assert_eq!(
        publisher.await.unwrap().unwrap_err().1,
        "STALE_EXPORT_ATTEMPT"
    );
    let state: String = sqlx::query_scalar("SELECT state FROM operations WHERE id=$1")
        .bind(operation)
        .fetch_one(&app.pool)
        .await
        .unwrap();
    assert_eq!(state, "failed");
}

#[tokio::test]
#[ignore = "requires Docker; run make test-integration SERVICE=letfs TEST=zip-export"]
async fn zip_export_names_multipart_cleanup_and_capacity() {
    let f = Fixture::new().await;
    let mut app = f.app.clone();
    Arc::make_mut(&mut app.config).exports.max_concurrent = 1;
    let bucket = Uuid::now_v7();
    fs::ensure_bucket(
        &app.pool,
        fs::EnsureBucket {
            id: bucket,
            provision_key: bucket.to_string(),
            limit_bytes: "50000000".into(),
        },
    )
    .await
    .unwrap();
    let (fs, root) = f.filesystem(bucket).await;
    let actor = Uuid::now_v7();
    let one = artifact_child(&app, fs, root, "one", None).await;
    let two = artifact_child(&app, fs, root, "two", None).await;
    let long = "ữ".repeat(85);
    let a = artifact_child(&app, fs, one, &long, None).await;
    let b = artifact_child(&app, fs, two, &long, None).await;
    let start = selection(fs, actor, &[a, b], false);
    let first = exports::prepare(&app, &start, 1, Uuid::now_v7())
        .await
        .unwrap()
        .unwrap();
    let mut reversed = start.clone();
    reversed.selection.locators.reverse();
    let mut session = nodes::session(&app, fs, false).await.unwrap();
    let reversed = exports::enumerate(&app, &mut session, &reversed)
        .await
        .unwrap();
    assert_eq!(first.snapshot.entries, reversed.entries);
    assert_eq!(first.snapshot.entries.len(), 2);
    assert!(first.snapshot.entries.iter().all(|e| e.path.len() <= 255));
    assert!(
        first
            .snapshot
            .entries
            .iter()
            .any(|e| e.path.ends_with(" (2)"))
    );
    drop(session);
    let items = archive(&app, &first).await;
    assert_eq!(items.len(), 2, "preserve both empty selected roots");
    assert!(items.values().all(Vec::is_empty));
    let mut denied = start.clone();
    denied.scope.mounts.clear();
    assert_eq!(
        exports::existing(&app, &denied).await.unwrap_err().1,
        "NOT_FOUND"
    );

    let data = vec![0x7b; 9 * 1048576];
    let (upload, _) = create_and_transfer(
        &app,
        fs,
        actor,
        json!({"parent":{"node_id":root},"name":"large.bin"}),
        &data,
        "object",
    )
    .await;
    let result = fs::uploads::finalize(&app, fs, upload, actor, None)
        .await
        .unwrap();
    let large = serde_json::from_value(result["node_id"].clone()).unwrap();
    let start = selection(fs, actor, &[large], false);
    let active = exports::prepare(&app, &start, 1, Uuid::now_v7())
        .await
        .unwrap()
        .unwrap();
    let refused = exports::prepare(
        &app,
        &selection(fs, actor, &[root], false),
        1,
        Uuid::now_v7(),
    )
    .await;
    assert_eq!(refused.err().unwrap().1, "RESOURCE_LIMIT");
    let items = archive(&app, &active).await;
    assert_eq!(
        items["large.bin"], data,
        "archive spans multiple native S3 parts"
    );
    sqlx::query("UPDATE object_deletions SET eligible_at=now() WHERE object_key=$1")
        .bind(&active.key)
        .execute(&app.pool)
        .await
        .unwrap();
    fs::maintenance::delete_objects(&app).await.unwrap();
    app.storage
        .head(&ObjectPath::from(active.key.as_str()))
        .await
        .expect("live export protected from deletion");
    sqlx::query("UPDATE export_attempts SET expires_at=now()-interval '1 second' WHERE id=$1")
        .bind(active.id)
        .execute(&app.pool)
        .await
        .unwrap();
    sqlx::query("UPDATE object_deletions SET eligible_at=now() WHERE object_key=$1")
        .bind(&active.key)
        .execute(&app.pool)
        .await
        .unwrap();
    assert!(fs::maintenance::delete_objects(&app).await.unwrap() > 0);
    assert!(matches!(
        app.storage
            .head(&ObjectPath::from(active.key.as_str()))
            .await,
        Err(object_store::Error::NotFound { .. })
    ));

    use object_store::multipart::MultipartStore;
    let abandoned = exports::prepare(
        &app,
        &selection(fs, actor, &[one], false),
        1,
        Uuid::now_v7(),
    )
    .await
    .unwrap()
    .unwrap();
    let remote = app
        .storage
        .create_multipart(&ObjectPath::from(abandoned.key.as_str()))
        .await
        .unwrap();
    sqlx::query(
        "UPDATE export_attempts SET multipart_id=$2,deadline=now()-interval '1 second' WHERE id=$1",
    )
    .bind(abandoned.id)
    .bind(&remote)
    .execute(&app.pool)
    .await
    .unwrap();
    exports::maintain(&app).await.unwrap();
    let cleared: bool =
        sqlx::query_scalar("SELECT multipart_id IS NULL FROM export_attempts WHERE id=$1")
            .bind(abandoned.id)
            .fetch_one(&app.pool)
            .await
            .unwrap();
    assert!(
        cleared,
        "maintenance aborted the abandoned multipart upload"
    );
    assert!(
        app.storage
            .put_part(
                &ObjectPath::from(abandoned.key.as_str()),
                &remote,
                0,
                bytes::Bytes::from_static(b"late").into()
            )
            .await
            .is_err()
    );
}
