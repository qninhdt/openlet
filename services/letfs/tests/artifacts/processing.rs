use super::*;
use fs::processing::{self, Attempt, Complete};

async fn source(f: &Fixture, bucket: Uuid, name: &str) -> (Uuid, Uuid, Uuid, Attempt) {
    let (filesystem, root) = f.filesystem(bucket).await;
    let actor = Uuid::now_v7();
    let (upload, _) = create_and_transfer(
        &f.app,
        filesystem,
        actor,
        json!({"parent":{"node_id":root},"name":name}),
        b"original",
        "inline",
    )
    .await;
    let result = fs::uploads::finalize(&f.app, filesystem, upload, actor, None)
        .await
        .unwrap();
    let source_id = serde_json::from_value(result["node_id"].clone()).unwrap();
    let operation_id =
        sqlx::query_scalar("SELECT id FROM operations WHERE source_id=$1 AND kind='process-file'")
            .bind(source_id)
            .fetch_one(&f.app.pool)
            .await
            .unwrap();
    (
        filesystem,
        source_id,
        actor,
        Attempt {
            operation_id,
            generation: 1,
            attempt_id: Uuid::now_v7(),
        },
    )
}

async fn output(
    app: &App,
    filesystem: Uuid,
    attempt: &Attempt,
    path: &str,
    bytes: &[u8],
    mode: &str,
) -> Uuid {
    use base64::{Engine, prelude::BASE64_STANDARD};
    use md5::{Digest, Md5};

    let content_md5 = (mode == "object").then(|| BASE64_STANDARD.encode(Md5::digest(bytes)));
    let metadata = json!({
        "path": path,
        "storage": mode,
        "size_bytes": bytes.len().to_string(),
        "content_md5": content_md5,
    });
    let prepared = processing::prepare_output(
        app,
        attempt,
        serde_json::from_value(metadata.clone()).unwrap(),
    )
    .await
    .unwrap();
    assert_eq!(
        prepared["id"],
        processing::prepare_output(app, attempt, serde_json::from_value(metadata).unwrap())
            .await
            .unwrap()["id"]
    );
    let id = serde_json::from_value(prepared["id"].clone()).unwrap();
    let access = fs::uploads::Access::Processor(attempt.clone());
    if mode == "inline" {
        fs::uploads::transfer(
            app,
            filesystem,
            id,
            access.clone(),
            Body::from(bytes.to_vec()),
        )
        .await
        .unwrap();
    } else {
        let mut put = reqwest::Client::new()
            .put(prepared["transfer"]["url"].as_str().unwrap())
            .body(bytes.to_vec());
        for (key, value) in prepared["transfer"]["headers"].as_object().unwrap() {
            put = put.header(key, value.as_str().unwrap());
        }
        assert!(put.send().await.unwrap().status().is_success());
    }
    assert_eq!(
        fs::uploads::finalize(app, filesystem, id, access, None)
            .await
            .unwrap()["state"],
        "uploaded"
    );
    id
}

#[tokio::test]
#[ignore = "requires Docker; run make test-integration SERVICE=letfs TEST=artifacts"]
async fn processing_publishes_all_outputs_once_without_per_file_admission() {
    let f = Fixture::new().await;
    let bucket = Uuid::now_v7();
    fs::ensure_bucket(
        &f.app.pool,
        fs::EnsureBucket {
            id: bucket,
            provision_key: bucket.to_string(),
            limit_bytes: "1000000".into(),
        },
    )
    .await
    .unwrap();
    let (filesystem, id, actor, attempt) = source(&f, bucket, "report.PDF").await;
    let mut app = f.app.clone();
    Arc::make_mut(&mut app.config).max_outstanding = 1;
    let prepared = processing::prepare(&app, &attempt).await.unwrap();
    assert_eq!(prepared["source"]["bytes_base64"], "b3JpZ2luYWw=");
    assert_eq!(prepared["format"], "pdf");
    assert_eq!(
        processing::prepare(
            &app,
            &Attempt {
                attempt_id: Uuid::now_v7(),
                ..attempt.clone()
            }
        )
        .await
        .unwrap_err()
        .1,
        "STALE_PROCESSING_ATTEMPT"
    );
    let before = nodes::read(
        &app,
        filesystem,
        "stat",
        request(filesystem, actor, json!({"locator":{"node_id":id}})),
    )
    .await
    .unwrap();
    let mut uploads = Vec::new();
    for i in 1..=20 {
        uploads.push(
            output(
                &app,
                filesystem,
                &attempt,
                &format!("{i:03}.md"),
                b"text",
                "inline",
            )
            .await,
        );
    }
    uploads.push(
        output(
            &app,
            filesystem,
            &attempt,
            "images/001.png",
            b"image",
            "object",
        )
        .await,
    );
    assert_eq!(usage(&app, bucket).await, 8);
    assert!(
        nodes::read(
            &app,
            filesystem,
            "list",
            request(filesystem, actor, json!({"locator":{"node_id":id}}))
        )
        .await
        .unwrap()["items"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    assert_eq!(
        fs::uploads::status(&app, filesystem, uploads[0], actor)
            .await
            .unwrap_err()
            .1,
        "NOT_FOUND"
    );
    let complete = || Complete {
        uploads: uploads.clone(),
        directories: vec!["empty".into()],
    };
    let result = processing::complete(&app, &attempt, complete())
        .await
        .unwrap();
    assert_eq!(result["state"], "succeeded");
    assert_eq!(
        processing::complete(&app, &attempt, complete())
            .await
            .unwrap(),
        result
    );
    assert_eq!(usage(&app, bucket).await, 93);
    let after = nodes::read(
        &app,
        filesystem,
        "stat",
        request(filesystem, actor, json!({"locator":{"node_id":id}})),
    )
    .await
    .unwrap();
    assert_eq!(before, after);
    let child = nodes::read(
        &app,
        filesystem,
        "stat",
        request(
            filesystem,
            actor,
            json!({"locator":{"path":"/drive/report.PDF/images/001.png"}}),
        ),
    )
    .await
    .unwrap();
    assert_eq!(child["size_bytes"], "5");
    assert_eq!(
        nodes::modify(
            &app,
            filesystem,
            "replace-text",
            request(
                filesystem,
                actor,
                json!({"locator":{"node_id":child["id"]},"revision":"1","text":"x"})
            )
        )
        .await
        .unwrap_err()
        .1,
        "ARTIFACT_READ_ONLY"
    );
    assert_eq!(
        processing::prepare(
            &app,
            &Attempt {
                generation: 2,
                attempt_id: Uuid::now_v7(),
                ..attempt.clone()
            }
        )
        .await
        .unwrap()["state"],
        "succeeded"
    );
    assert_eq!(
        processing::complete(
            &app,
            &Attempt {
                generation: 2,
                attempt_id: Uuid::now_v7(),
                ..attempt
            },
            complete()
        )
        .await
        .unwrap_err()
        .1,
        "STALE_PROCESSING_ATTEMPT"
    );
}

#[tokio::test]
#[ignore = "requires Docker; run make test-integration SERVICE=letfs TEST=artifacts"]
async fn processing_fences_stale_attempts_and_quota_failure_is_atomic() {
    let f = Fixture::new().await;
    let app = &f.app;
    let bucket = Uuid::now_v7();
    fs::ensure_bucket(
        &app.pool,
        fs::EnsureBucket {
            id: bucket,
            provision_key: bucket.to_string(),
            limit_bytes: "10".into(),
        },
    )
    .await
    .unwrap();
    let (filesystem, id, actor, first) = source(&f, bucket, "report.pdf").await;
    processing::prepare(app, &first).await.unwrap();
    let old = output(app, filesystem, &first, "old.md", b"old", "inline").await;
    let second = Attempt {
        generation: 2,
        attempt_id: Uuid::now_v7(),
        ..first.clone()
    };
    processing::prepare(app, &second).await.unwrap();
    assert_eq!(
        fs::uploads::status(
            app,
            filesystem,
            old,
            fs::uploads::Access::Processor(first.clone())
        )
        .await
        .unwrap_err()
        .1,
        "STALE_PROCESSING_ATTEMPT"
    );
    assert_eq!(
        processing::prepare(app, &first).await.unwrap_err().1,
        "STALE_PROCESSING_ATTEMPT"
    );
    assert_eq!(
        processing::abort(app, &first, "DOCUMENT_INVALID")
            .await
            .unwrap_err()
            .1,
        "STALE_PROCESSING_ATTEMPT"
    );
    let current = output(app, filesystem, &second, "part.md", b"long", "object").await;
    nodes::modify(
        app,
        filesystem,
        "rename",
        request(
            filesystem,
            actor,
            json!({"locator":{"node_id":id},"name":"renamed.pdf","revision":"1"}),
        ),
    )
    .await
    .unwrap();
    assert_eq!(
        processing::complete(
            app,
            &second,
            Complete {
                uploads: vec![current],
                directories: vec![]
            }
        )
        .await
        .unwrap_err()
        .1,
        "QUOTA_EXCEEDED"
    );
    assert_eq!(usage(app, bucket).await, 8);
    assert!(
        nodes::read(
            app,
            filesystem,
            "list",
            request(filesystem, actor, json!({"locator":{"node_id":id}}))
        )
        .await
        .unwrap()["items"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    processing::abort(app, &second, "QUOTA_EXCEEDED")
        .await
        .unwrap();
    assert_eq!(
        fs::artifacts::status(
            app,
            filesystem,
            request(filesystem, actor, json!({"locator":{"node_id":id}}))
        )
        .await
        .unwrap()["error_code"],
        "QUOTA_EXCEEDED"
    );
    let candidate =
        sqlx::query_scalar::<_, String>("SELECT candidate_key FROM uploads WHERE id=$1")
            .bind(current)
            .fetch_one(&app.pool)
            .await
            .unwrap();
    assert!(
        sqlx::query_scalar::<_, bool>(
            "SELECT EXISTS(SELECT 1 FROM object_deletions WHERE object_key=$1 AND ambiguous_write)"
        )
        .bind(candidate)
        .fetch_one(&app.pool)
        .await
        .unwrap()
    );
}
