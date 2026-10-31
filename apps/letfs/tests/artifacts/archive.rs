use super::*;
use fs::archive;
use object_store::ObjectStore;
use std::collections::BTreeMap;

async fn preflight(app: &App, fs: Uuid, folder: Uuid) -> archive::Archive {
    archive::preflight(
        app,
        fs,
        folder,
        &request(fs, Uuid::now_v7(), json!({})).scope,
    )
    .await
    .unwrap()
}
async fn bytes(app: &App, archive: archive::Archive) -> Result<Vec<u8>, std::io::Error> {
    use futures::TryStreamExt;
    let permit = app.archive_slots.clone().try_acquire_owned().unwrap();
    let chunks = letfs::storage::archive::stream(
        app.clone(),
        archive,
        permit,
        letfs::storage::archive::deadline(app),
    )
    .try_collect::<Vec<_>>()
    .await?;
    Ok(chunks.into_iter().flat_map(|c| c.to_vec()).collect())
}
async fn entries(bytes: Vec<u8>) -> BTreeMap<String, Vec<u8>> {
    use futures::AsyncReadExt;
    let mut reader =
        async_zip::base::read1::seek::ZipArchiveReader::open(futures::io::Cursor::new(bytes))
            .await
            .unwrap();
    assert!(reader.ceocdr().is_zip64());
    let names = reader
        .cdrs()
        .iter()
        .map(|e| e.insecure_file_name.as_str().unwrap().to_owned())
        .collect::<Vec<_>>();
    let mut result = BTreeMap::new();
    for (index, name) in names.into_iter().enumerate() {
        let mut bytes = Vec::new();
        reader
            .file(index)
            .await
            .unwrap()
            .read_to_end(&mut bytes)
            .await
            .unwrap();
        result.insert(name, bytes);
    }
    result
}
#[tokio::test]
#[ignore = "requires Docker; run pnpm --filter @openlet/letfs test:integration"]
async fn archive_streams_inline_object_and_empty_directories_without_storage_writes() {
    let f = Fixture::new().await;
    let app = &f.app;
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
    let (fs, root) = f.filesystem(bucket).await;
    let folder = artifact_child(app, fs, root, "download", None).await;
    artifact_child(app, fs, folder, "empty", None).await;
    let file = artifact_child(app, fs, folder, "tài-liệu.bin", Some(b"inline\0\xff\r\n")).await;
    artifact_child(
        app,
        fs,
        file,
        "generated.md",
        Some(b"must not traverse into files"),
    )
    .await;
    let actor = Uuid::now_v7();
    let (upload, _) = create_and_transfer(
        app,
        fs,
        actor,
        json!({"parent":{"node_id":folder},"name":"image.bin"}),
        b"object",
        "object",
    )
    .await;
    fs::uploads::finalize(app, fs, upload, actor, None)
        .await
        .unwrap();
    let usage_before = usage(app, bucket).await;
    use futures::TryStreamExt;
    let objects_before = app
        .storage
        .list(None)
        .try_collect::<Vec<_>>()
        .await
        .unwrap()
        .len();
    let result = entries(bytes(app, preflight(app, fs, folder).await).await.unwrap()).await;
    assert_eq!(
        result,
        BTreeMap::from([
            ("empty/".into(), vec![]),
            ("tài-liệu.bin".into(), b"inline\0\xff\r\n".to_vec()),
            ("image.bin".into(), b"object".to_vec())
        ])
    );
    assert_eq!(usage(app, bucket).await, usage_before);
    assert_eq!(
        app.storage
            .list(None)
            .try_collect::<Vec<_>>()
            .await
            .unwrap()
            .len(),
        objects_before
    );
}
#[tokio::test]
#[ignore = "requires Docker; run pnpm --filter @openlet/letfs test:integration"]
async fn archive_rejects_changed_sources_unsafe_paths_and_exceeded_bounds() {
    let f = Fixture::new().await;
    let mut app = f.app.clone();
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
    let (fs, root) = f.filesystem(bucket).await;
    let folder = artifact_child(&app, fs, root, "download", None).await;
    let file = artifact_child(&app, fs, folder, "data.bin", Some(b"before")).await;
    let selected = preflight(&app, fs, folder).await;
    sqlx::query("UPDATE nodes SET revision=revision+1 WHERE id=$1")
        .bind(file)
        .execute(&app.pool)
        .await
        .unwrap();
    assert!(
        bytes(&app, selected)
            .await
            .unwrap_err()
            .to_string()
            .contains("SOURCE_CHANGED")
    );
    Arc::make_mut(&mut app.config).archive.max_output_bytes = 1;
    assert!(
        bytes(&app, preflight(&app, fs, folder).await)
            .await
            .unwrap_err()
            .to_string()
            .contains("RESOURCE_LIMIT")
    );
    Arc::make_mut(&mut app.config).archive.max_source_bytes = 1;
    assert_eq!(
        archive::preflight(
            &app,
            fs,
            folder,
            &request(fs, Uuid::now_v7(), json!({})).scope
        )
        .await
        .err()
        .unwrap()
        .1,
        "RESOURCE_LIMIT"
    );
    Arc::make_mut(&mut app.config).archive.max_source_bytes = 100;
    Arc::make_mut(&mut app.config).archive.max_entries = 1;
    artifact_child(&app, fs, folder, "second", None).await;
    assert_eq!(
        archive::preflight(
            &app,
            fs,
            folder,
            &request(fs, Uuid::now_v7(), json!({})).scope
        )
        .await
        .err()
        .unwrap()
        .1,
        "RESOURCE_LIMIT"
    );
    Arc::make_mut(&mut app.config).archive.max_entries = 100;
    sqlx::query("UPDATE nodes SET name=$2 WHERE id=$1")
        .bind(file)
        .bind("é.txt")
        .execute(&app.pool)
        .await
        .unwrap();
    artifact_child(&app, fs, folder, "e\u{301}.txt", Some(b"different")).await;
    assert_eq!(
        archive::preflight(
            &app,
            fs,
            folder,
            &request(fs, Uuid::now_v7(), json!({})).scope
        )
        .await
        .err()
        .unwrap()
        .1,
        "VALIDATION"
    );
    sqlx::query("UPDATE nodes SET name='CON.txt' WHERE id=$1")
        .bind(file)
        .execute(&app.pool)
        .await
        .unwrap();
    assert_eq!(
        archive::preflight(
            &app,
            fs,
            folder,
            &request(fs, Uuid::now_v7(), json!({})).scope
        )
        .await
        .err()
        .unwrap()
        .1,
        "VALIDATION"
    );
}
#[tokio::test]
#[ignore = "requires Docker; run pnpm --filter @openlet/letfs test:integration"]
async fn archive_body_owns_concurrency_and_checks_the_download_deadline() {
    use futures::TryStreamExt;
    let f = Fixture::new().await;
    let app = &f.app;
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
    let (fs, root) = f.filesystem(bucket).await;
    let folder = artifact_child(app, fs, root, "download", None).await;
    let permits = app.archive_slots.available_permits();
    let body = letfs::storage::archive::stream(
        app.clone(),
        preflight(app, fs, folder).await,
        app.archive_slots.clone().try_acquire_owned().unwrap(),
        letfs::storage::archive::deadline(app),
    );
    assert_eq!(app.archive_slots.available_permits(), permits - 1);
    drop(body);
    assert_eq!(app.archive_slots.available_permits(), permits);
    let body = letfs::storage::archive::stream(
        app.clone(),
        preflight(app, fs, folder).await,
        app.archive_slots.clone().try_acquire_owned().unwrap(),
        tokio::time::Instant::now() - Duration::from_secs(1),
    );
    assert_eq!(
        body.try_collect::<Vec<_>>().await.unwrap_err().kind(),
        std::io::ErrorKind::TimedOut
    );
    assert_eq!(app.archive_slots.available_permits(), permits);
}
