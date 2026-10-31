use super::*;

#[tokio::test]
#[ignore = "requires Docker; run pnpm --filter @openlet/letfs test:integration"]
async fn purge_retains_bounded_progress_and_repeated_completion_cannot_debit_twice() {
    let fixture = Fixture::new().await;
    let app = &fixture.app;
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
    let (filesystem, root) = fixture.filesystem(bucket).await;
    let actor = Uuid::now_v7();
    let folder = nodes::create(
        app,
        filesystem,
        create_request(
            "directories",
            request(
                filesystem,
                actor,
                json!({"parent":{"node_id":root},"name":"purge"}),
            ),
        ),
    )
    .await
    .unwrap();
    for index in 0..70 {
        nodes::create(app,filesystem,create_request("text",request(filesystem,actor,
            json!({"parent":{"node_id":folder.id},"name":format!("{index:03}.bin"),"text":"x"})))).await.unwrap();
    }
    let outside = nodes::create(
        app,
        filesystem,
        create_request(
            "text",
            request(
                filesystem,
                actor,
                json!({"parent":{"node_id":root},"name":"outside.bin","text":"keep"}),
            ),
        ),
    )
    .await
    .unwrap();
    let selected = nodes::fetch(&mut app.pool.acquire().await.unwrap(), folder.id)
        .await
        .unwrap();
    let entry = fs::trash::trash(
        app,
        filesystem,
        request(
            filesystem,
            actor,
            json!({"locator":{"node_id":folder.id},"revision":selected.revision}),
        ),
    )
    .await
    .unwrap();
    let input = fs::deletion::prepare(
        app,
        fs::deletion::Start {
            filesystem_id: filesystem,
            actor_id: actor,
            entry_id: Some(serde_json::from_value(entry["id"].clone()).unwrap()),
            revision: None,
        },
    )
    .await
    .unwrap();
    assert_eq!(
        fs::trash::restore(
            app,
            filesystem,
            request(filesystem, actor, json!({"entry_id":entry["id"]}))
        )
        .await
        .unwrap_err()
        .1,
        "TRASH_PURGING"
    );
    assert!(!fs::deletion::batch(app, &input).await.unwrap());
    assert_eq!(usage(app, bucket).await, 10);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM nodes WHERE parent_id=$1")
            .bind(folder.id)
            .fetch_one(&app.pool)
            .await
            .unwrap(),
        6
    );
    let restarted = app.clone();
    let resumed = fs::deletion::prepare(&restarted, input.clone())
        .await
        .unwrap();
    for _ in 0..3 {
        if fs::deletion::batch(&restarted, &resumed).await.unwrap() {
            break;
        }
    }
    assert!(fs::deletion::batch(app, &input).await.unwrap());
    assert_eq!(usage(app, bucket).await, 4);
    assert_eq!(
        nodes::fetch(&mut app.pool.acquire().await.unwrap(), outside.id)
            .await
            .unwrap()
            .size_bytes,
        "4"
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT node_count FROM filesystems WHERE id=$1")
            .bind(filesystem)
            .fetch_one(&app.pool)
            .await
            .unwrap(),
        2
    );
}
