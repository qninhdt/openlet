use super::*;

#[tokio::test]
#[ignore = "requires Docker; run pnpm --filter @openlet/letfs test:integration"]
async fn copy_receipt_and_item_retries_cannot_recharge_or_resurrect_deleted_results() {
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
                json!({"parent":{"node_id":root},"name":"source"}),
            ),
        ),
    )
    .await
    .unwrap();
    for name in ["first.bin", "second.bin"] {
        nodes::create(
            app,
            filesystem,
            create_request(
                "text",
                request(
                    filesystem,
                    actor,
                    json!({"parent":{"node_id":folder.id},"name":name,"text":"xx"}),
                ),
            ),
        )
        .await
        .unwrap();
    }
    let selected = nodes::fetch(&mut app.pool.acquire().await.unwrap(), folder.id)
        .await
        .unwrap();
    let request = fs::copy::Request {
        scope: request(filesystem, actor, json!({})).scope,
        input: fs::copy::Input {
            source_id: folder.id,
            parent_id: root,
            name: "copied".into(),
            revision: selected.revision,
            request_key: Uuid::now_v7(),
        },
    };
    let admission = fs::copy::admit(app, filesystem, request.clone())
        .await
        .unwrap();
    let replay = fs::copy::admit(app, filesystem, request.clone())
        .await
        .unwrap();
    assert_eq!(admission.id, replay.id);
    let mut changed = request.clone();
    changed.input.name = "other".into();
    assert_eq!(
        fs::copy::admit(app, filesystem, changed)
            .await
            .unwrap_err()
            .1,
        "IDEMPOTENCY_CONFLICT"
    );
    let step = fs::copy::Step {
        admission: admission.clone(),
        item: admission.root.clone(),
    };
    fs::copy::commit_item(app, step.clone()).await.unwrap();
    fs::copy::commit_item(app, step).await.unwrap();
    let mut fresh = request;
    fresh.input.request_key = Uuid::now_v7();
    assert_eq!(
        fs::copy::admit(app, filesystem, fresh).await.unwrap_err().1,
        "NAME_CONFLICT"
    );
    let frame = fs::copy::Frame {
        item: admission.root.clone(),
        after: Uuid::nil(),
        revision: "1".into(),
    };
    let child = fs::copy::next(
        app,
        fs::copy::Next {
            admission: admission.clone(),
            frame,
        },
    )
    .await
    .unwrap()
    .unwrap();
    let step = fs::copy::Step {
        admission: admission.clone(),
        item: child.clone(),
    };
    fs::copy::commit_item(app, step.clone()).await.unwrap();
    fs::copy::commit_item(app, step.clone()).await.unwrap();
    assert_eq!(usage(app, bucket).await, 6);
    let entry = fs::trash::trash(
        app,
        filesystem,
        super::request(
            filesystem,
            actor,
            json!({"locator":{"node_id":child.destination},"revision":"1"}),
        ),
    )
    .await
    .unwrap();
    let deletion = fs::deletion::prepare(
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
    assert!(fs::deletion::batch(app, &deletion).await.unwrap());
    assert_eq!(
        fs::copy::commit_item(app, step).await.unwrap_err().1,
        "DESTINATION_CHANGED"
    );
    assert_eq!(usage(app, bucket).await, 4);
    assert!(
        !sqlx::query_scalar::<_, bool>("SELECT EXISTS(SELECT 1 FROM nodes WHERE id=$1)")
            .bind(child.destination)
            .fetch_one(&app.pool)
            .await
            .unwrap()
    );
    assert!(
        nodes::fetch(
            &mut app.pool.acquire().await.unwrap(),
            admission.root.destination
        )
        .await
        .is_ok()
    );
    fs::copy::complete(app, &admission).await.unwrap();
    let expiry:bool=sqlx::query_scalar("SELECT completed_at IS NOT NULL AND expires_at=completed_at+interval '24 hours' FROM idempotency_keys WHERE operation='copy-node' AND result->>'id'=$1").bind(admission.id.to_string()).fetch_one(&app.pool).await.unwrap();
    assert!(expiry);
}

#[tokio::test]
#[ignore = "requires Docker; run pnpm --filter @openlet/letfs test:integration"]
async fn rejected_object_copy_closes_known_write_and_cleanup_prevents_candidate_reuse() {
    let fixture = Fixture::new().await;
    let app = &fixture.app;
    let bucket = fs::ensure_bucket(
        &app.pool,
        fs::EnsureBucket {
            provision_key: Uuid::now_v7().to_string(),
            limit_bytes: "10".into(),
        },
    )
    .await
    .unwrap()
    .id;
    let (filesystem, root) = fixture.filesystem(bucket).await;
    let actor = Uuid::now_v7();
    let (upload, _) = create_and_transfer(
        app,
        filesystem,
        actor,
        json!({"parent":{"node_id":root},"name":"source.bin"}),
        b"object",
        "object",
    )
    .await;
    let finalized = fs::uploads::finalize(app, filesystem, upload, actor, None)
        .await
        .unwrap();
    let source = serde_json::from_value(finalized["node_id"].clone()).unwrap();
    let admission = fs::copy::admit(
        app,
        filesystem,
        fs::copy::Request {
            scope: request(filesystem, actor, json!({})).scope,
            input: fs::copy::Input {
                source_id: source,
                parent_id: root,
                name: "copy.bin".into(),
                revision: "1".into(),
                request_key: Uuid::now_v7(),
            },
        },
    )
    .await
    .unwrap();
    let step = fs::copy::Step {
        admission: admission.clone(),
        item: admission.root.clone(),
    };
    assert_eq!(
        fs::copy::commit_item(app, step.clone())
            .await
            .unwrap_err()
            .1,
        "QUOTA_EXCEEDED"
    );
    assert_eq!(usage(app, bucket).await, 6);
    let key = format!("objects/{bucket}/{}", admission.root.destination);
    let open: i64 =
        sqlx::query_scalar("SELECT open_writes FROM object_deletions WHERE object_key=$1")
            .bind(&key)
            .fetch_one(&app.pool)
            .await
            .unwrap();
    assert_eq!(
        open, 0,
        "an acknowledged write must not stay ambiguous after quota rejection"
    );
    assert!(
        app.storage
            .head(&ObjectPath::from(key.clone()))
            .await
            .is_ok()
    );
    sqlx::query(
        "UPDATE object_deletions SET eligible_at=now()-interval '1 second' WHERE object_key=$1",
    )
    .bind(&key)
    .execute(&app.pool)
    .await
    .unwrap();
    assert_eq!(fs::maintenance::delete_objects(app).await.unwrap(), 1);
    assert!(matches!(
        app.storage.head(&ObjectPath::from(key)).await,
        Err(object_store::Error::NotFound { .. })
    ));
    assert_eq!(
        fs::copy::commit_item(app, step).await.unwrap_err().1,
        "COPY_CANDIDATE_CLOSED"
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT node_count FROM filesystems WHERE id=$1")
            .bind(filesystem)
            .fetch_one(&app.pool)
            .await
            .unwrap(),
        2
    );
    sqlx::query("UPDATE quota_buckets SET limit_bytes=20 WHERE id=$1")
        .bind(bucket)
        .execute(&app.pool)
        .await
        .unwrap();
    let current = nodes::fetch(&mut app.pool.acquire().await.unwrap(), root)
        .await
        .unwrap();
    let successful = fs::copy::admit(
        app,
        filesystem,
        fs::copy::Request {
            scope: request(filesystem, actor, json!({})).scope,
            input: fs::copy::Input {
                source_id: source,
                parent_id: root,
                name: "committed.bin".into(),
                revision: "1".into(),
                request_key: Uuid::now_v7(),
            },
        },
    )
    .await
    .unwrap();
    assert_eq!(successful.root.parent_revision, current.revision);
    let step = fs::copy::Step {
        admission: successful.clone(),
        item: successful.root.clone(),
    };
    fs::copy::commit_item(app, step.clone()).await.unwrap();
    fs::copy::commit_item(app, step).await.unwrap();
    assert_eq!(usage(app, bucket).await, 12);
    let key = format!("objects/{bucket}/{}", successful.root.destination);
    assert!(
        !sqlx::query_scalar::<_, bool>(
            "SELECT EXISTS(SELECT 1 FROM object_deletions WHERE object_key=$1)"
        )
        .bind(&key)
        .fetch_one(&app.pool)
        .await
        .unwrap(),
        "a closed published candidate must not fill cleanup backlog"
    );
    assert_eq!(
        app.storage
            .get(&ObjectPath::from(key))
            .await
            .unwrap()
            .bytes()
            .await
            .unwrap()
            .as_ref(),
        b"object"
    );
    let uncertain = fs::copy::admit(
        app,
        filesystem,
        fs::copy::Request {
            scope: request(filesystem, actor, json!({})).scope,
            input: fs::copy::Input {
                source_id: source,
                parent_id: root,
                name: "uncertain.bin".into(),
                revision: "1".into(),
                request_key: Uuid::now_v7(),
            },
        },
    )
    .await
    .unwrap();
    let key = format!("objects/{bucket}/{}", uncertain.root.destination);
    // This is the durable state left by an earlier request whose acknowledgment/worker was lost.
    sqlx::query("INSERT INTO object_deletions(object_key,bucket_id,open_writes) VALUES($1,$2,1)")
        .bind(&key)
        .bind(bucket)
        .execute(&app.pool)
        .await
        .unwrap();
    fs::copy::commit_item(
        app,
        fs::copy::Step {
            admission: uncertain.clone(),
            item: uncertain.root.clone(),
        },
    )
    .await
    .unwrap();
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT open_writes FROM object_deletions WHERE object_key=$1"
        )
        .bind(&key)
        .fetch_one(&app.pool)
        .await
        .unwrap(),
        1,
        "closing this request must preserve an older unresolved writer"
    );
    sqlx::query("UPDATE object_deletions SET state='deleted' WHERE object_key=$1")
        .bind(&key)
        .execute(&app.pool)
        .await
        .unwrap();
    let mut bounded = app.clone();
    Arc::make_mut(&mut bounded.config).max_cleanup_backlog = 1;
    let rejected = fs::copy::admit(
        &bounded,
        filesystem,
        fs::copy::Request {
            scope: request(filesystem, actor, json!({})).scope,
            input: fs::copy::Input {
                source_id: source,
                parent_id: root,
                name: "blocked.bin".into(),
                revision: "1".into(),
                request_key: Uuid::now_v7(),
            },
        },
    )
    .await
    .unwrap_err();
    assert_eq!(
        rejected.1, "RESOURCE_LIMIT",
        "a deleted tombstone with an unresolved writer still counts against admission"
    );
}
