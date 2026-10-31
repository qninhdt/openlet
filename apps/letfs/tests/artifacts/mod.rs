mod archive;
use super::*;
mod processing;

#[tokio::test]
#[ignore = "requires Docker; run pnpm --filter @openlet/letfs test:integration"]
async fn artifacts_copy_and_large_forest_lifecycle() {
    let fixture = Fixture::new().await;
    let mut app = fixture.app.clone();
    Arc::make_mut(&mut app.config).max_copy_nodes = 200;
    let app = &app;
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
    let folder = nodes::create(
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
    let (upload, _) = create_and_transfer(
        app,
        filesystem,
        actor,
        json!({"parent":{"node_id":folder.id},"name":"report.pdf"}),
        b"original",
        "inline",
    )
    .await;
    let source: Uuid = serde_json::from_value(
        fs::uploads::finalize(app, filesystem, upload, actor, None)
            .await
            .unwrap()["node_id"]
            .clone(),
    )
    .unwrap();
    let parts = artifact_child(app, filesystem, source, "artifacts", None).await;
    let mut s = nodes::session(app, filesystem, true).await.unwrap();
    s.add_nodes(70).await.unwrap();
    s.usage(70).await.unwrap();
    sqlx::query(concat!(
        "WITH added AS (",
        "INSERT INTO nodes(id,filesystem_id,parent_id,name,kind,size_bytes) ",
        "SELECT gen_random_uuid(),$1,$2,'part-'||i::text||'.md','file',1 ",
        "FROM generate_series(1,70) i RETURNING id",
        ") INSERT INTO files(node_id,storage_kind,inline_bytes) ",
        "SELECT id,'inline',decode('78','hex') FROM added"
    ))
    .bind(filesystem)
    .bind(parts)
    .execute(&mut *s.tx)
    .await
    .unwrap();
    s.tx.commit().await.unwrap();
    let trash = fs::trash::trash(
        app,
        filesystem,
        request(
            filesystem,
            actor,
            json!({"locator":{"node_id":folder.id},"revision":"2"}),
        ),
    )
    .await
    .unwrap();
    assert_eq!(fs::artifacts::discard_forests(app).await.unwrap(), 0);
    assert_eq!(usage(app, bucket).await, 78);
    assert!(
        nodes::read(
            app,
            filesystem,
            "stat",
            request(filesystem, actor, json!({"locator":{"node_id":parts}}))
        )
        .await
        .is_err()
    );
    fs::trash::restore(
        app,
        filesystem,
        request(
            filesystem,
            actor,
            json!({"entry_id":trash["id"],"revision":"3"}),
        ),
    )
    .await
    .unwrap();
    assert_eq!(
        fs::artifacts::status(
            app,
            filesystem,
            request(filesystem, actor, json!({"locator":{"node_id":source}}))
        )
        .await
        .unwrap()["error_code"],
        "SOURCE_TRASHED"
    );
    nodes::modify(
        app,
        filesystem,
        "move",
        request(
            filesystem,
            actor,
            json!({
                "locator":{"node_id":folder.id},
                "parent":{"node_id":root},
                "name":"moved",
                "revision":"4"
            }),
        ),
    )
    .await
    .unwrap();
    assert_eq!(
        nodes::read(
            app,
            filesystem,
            "stat",
            request(
                filesystem,
                actor,
                json!({"locator":{"path":"/drive/moved/report.pdf/artifacts/part-70.md"}})
            )
        )
        .await
        .unwrap()["size_bytes"],
        "1"
    );
    let copy_request = request(
        filesystem,
        actor,
        json!({
            "locator":{"node_id":source},
            "revision":"1",
            "parent":{"node_id":root},
            "name":"copy.pdf",
            "request_key":Uuid::now_v7()
        }),
    );
    let op = admit_copy(app, filesystem, copy_request).await.unwrap();
    finish_copy(app, &op).await;
    let copied = op.root.destination;
    assert_eq!(usage(app, bucket).await, 156);
    assert_eq!(
        fs::artifacts::status(
            app,
            filesystem,
            request(filesystem, actor, json!({"locator":{"node_id":copied}}))
        )
        .await
        .unwrap()["publication_status"],
        "parsed"
    );
    let copy_parts = nodes::read(
        app,
        filesystem,
        "stat",
        request(
            filesystem,
            actor,
            json!({"locator":{"path":"/drive/copy.pdf/artifacts"}}),
        ),
    )
    .await
    .unwrap();
    let children = nodes::read(
        app,
        filesystem,
        "list",
        request(
            filesystem,
            actor,
            json!({"locator":{"node_id":copy_parts["id"]},"limit":100}),
        ),
    )
    .await
    .unwrap();
    assert_eq!(children["items"].as_array().unwrap().len(), 70);
    assert_eq!(
        nodes::modify(
            app,
            filesystem,
            "rename",
            request(
                filesystem,
                actor,
                json!({"locator":{"node_id":copy_parts["id"]},"revision":"1","name":"denied"})
            )
        )
        .await
        .unwrap_err()
        .1,
        "ARTIFACT_READ_ONLY"
    );
    let trashed = fs::trash::trash(
        app,
        filesystem,
        request(
            filesystem,
            actor,
            json!({"locator":{"node_id":source},"revision":"1"}),
        ),
    )
    .await
    .unwrap();
    let deletion = fs::deletion::prepare(
        app,
        fs::deletion::Start {
            filesystem_id: filesystem,
            actor_id: actor,
            entry_id: Some(serde_json::from_value(trashed["id"].clone()).unwrap()),
            revision: Some("2".into()),
        },
    )
    .await
    .unwrap();
    finish_deletion(app, deletion).await;
    assert_eq!(usage(app, bucket).await, 78);

    nodes::modify(
        app,
        filesystem,
        "replace-content",
        request(
            filesystem,
            actor,
            json!({"locator":{"node_id":copied},"revision":nodes::fetch(&mut app.pool.acquire().await.unwrap(),copied).await.unwrap().revision,"text":"updated"}),
        ),
    )
    .await
    .unwrap();
    assert_eq!(usage(app, bucket).await, 77);
    assert_eq!(fs::artifacts::discard_forests(app).await.unwrap(), 1);
    assert_eq!(
        usage(app, bucket).await,
        13,
        "one batch removes at most 64 charged leaf bytes"
    );
    assert!(
        sqlx::query_scalar::<_, bool>("SELECT EXISTS(SELECT 1 FROM nodes WHERE id=$1)")
            .bind(serde_json::from_value::<Uuid>(copy_parts["id"].clone()).unwrap())
            .fetch_one(&app.pool)
            .await
            .unwrap()
    );
    for attempt in 0..200 {
        if fs::artifacts::discard_forests(app).await.unwrap() == 0 {
            break;
        }
        assert!(attempt < 199, "invalidated forest did not converge");
    }
    assert_eq!(usage(app, bucket).await, 7);
    let (upload, _) = create_and_transfer(
        app,
        filesystem,
        actor,
        json!({"parent":{"node_id":root},"name":"late.pdf"}),
        b"object",
        "object",
    )
    .await;
    let late: Uuid = serde_json::from_value(
        fs::uploads::finalize(app, filesystem, upload, actor, None)
            .await
            .unwrap()["node_id"]
            .clone(),
    )
    .unwrap();
    let op = admit_copy(
        app,
        filesystem,
        request(
            filesystem,
            actor,
            json!({
                "locator":{"node_id":late},
                "revision":"1",
                "parent":{"node_id":root},
                "name":"empty-snapshot.pdf",
                "request_key":Uuid::now_v7()
            }),
        ),
    )
    .await
    .unwrap();
    let empty = op.root.destination;
    artifact_child(app, filesystem, late, "late.md", Some(b"late")).await;
    finish_copy(app, &op).await;
    assert!(
        nodes::read(
            app,
            filesystem,
            "list",
            request(filesystem, actor, json!({"locator":{"node_id":empty}}))
        )
        .await
        .unwrap()["items"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    let op = admit_copy(
        app,
        filesystem,
        request(
            filesystem,
            actor,
            json!({
                "locator":{"node_id":late},
                "revision":"1",
                "parent":{"node_id":root},
                "name":"stale.pdf",
                "request_key":Uuid::now_v7()
            }),
        ),
    )
    .await
    .unwrap();
    nodes::modify(
        app,
        filesystem,
        "replace-content",
        request(
            filesystem,
            actor,
            json!({"locator":{"node_id":late},"revision":"1","text":"replaced"}),
        ),
    )
    .await
    .unwrap();
    assert_eq!(
        fs::copy::commit_item(
            app,
            fs::copy::Step {
                admission: op.clone(),
                item: op.root.clone()
            }
        )
        .await
        .unwrap_err()
        .1,
        "SOURCE_REPLACED"
    );
    fs::copy::complete(app, &op).await.unwrap();
    let deletion = fs::deletion::prepare(
        app,
        fs::deletion::Start {
            filesystem_id: filesystem,
            actor_id: actor,
            entry_id: None,
            revision: None,
        },
    )
    .await
    .unwrap();
    finish_deletion(app, deletion).await;
    assert_eq!(usage(app, bucket).await, 0);
    let count: i64 = sqlx::query_scalar("SELECT node_count FROM filesystems WHERE id=$1")
        .bind(filesystem)
        .fetch_one(&app.pool)
        .await
        .unwrap();
    assert_eq!(count, 0);
}

async fn admit_copy(
    app: &App,
    filesystem: Uuid,
    r: nodes::Request,
) -> Result<fs::copy::Admission, letfs::http::ApiError> {
    fs::copy::admit(
        app,
        filesystem,
        fs::copy::Request {
            scope: r.scope,
            input: fs::copy::Input {
                source_id: r.input.locator.unwrap().node_id.unwrap(),
                parent_id: r.input.parent.unwrap().node_id.unwrap(),
                name: r.input.name.unwrap(),
                revision: r.input.revision.unwrap(),
                request_key: r.input.request_key.unwrap(),
            },
        },
    )
    .await
}
async fn finish_copy(app: &App, admission: &fs::copy::Admission) -> Vec<fs::copy::Next> {
    fs::copy::commit_item(
        app,
        fs::copy::Step {
            admission: admission.clone(),
            item: admission.root.clone(),
        },
    )
    .await
    .unwrap();
    let mut stack = vec![fs::copy::Frame {
        item: admission.root.clone(),
        after: Uuid::nil(),
        revision: "1".into(),
    }];
    let mut completed = vec![];
    for _ in 0..1000 {
        let Some(frame) = stack.last().cloned() else {
            fs::copy::complete(app, admission).await.unwrap();
            return completed;
        };
        let input = fs::copy::Next {
            admission: admission.clone(),
            frame,
        };
        match fs::copy::next(app, input.clone()).await.unwrap() {
            Some(item) => {
                fs::copy::commit_item(
                    app,
                    fs::copy::Step {
                        admission: admission.clone(),
                        item: item.clone(),
                    },
                )
                .await
                .unwrap();
                let parent = stack.last_mut().unwrap();
                parent.after = item.source;
                parent.revision = (parent.revision.parse::<i64>().unwrap() + 1).to_string();
                stack.push(fs::copy::Frame {
                    item,
                    after: Uuid::nil(),
                    revision: "1".into(),
                });
            }
            None => {
                fs::copy::finish_file(app, input.clone()).await.unwrap();
                completed.push(input);
                stack.pop();
            }
        }
    }
    panic!("copy did not converge")
}

async fn finish_deletion(app: &App, op: fs::deletion::Start) {
    for _ in 0..200 {
        if fs::deletion::batch(app, &op).await.unwrap() {
            return;
        }
    }
    panic!("deletion did not converge");
}

#[tokio::test]
#[ignore = "requires Docker; run pnpm --filter @openlet/letfs test:integration"]
async fn artifacts_directory_copy_dispatches_every_logical_file_and_keeps_media_types() {
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
    let folder = nodes::create(
        app,
        filesystem,
        create_request(
            "directory",
            request(
                filesystem,
                actor,
                json!({"parent":{"node_id":root},"name":"originals"}),
            ),
        ),
    )
    .await
    .unwrap();
    for (name, media_type) in [
        ("notes.md", "text/markdown"),
        ("data.json", "application/json"),
        ("data.csv", "text/csv"),
    ] {
        let node = nodes::create(
            app,
            filesystem,
            create_request(
                "text",
                request(
                    filesystem,
                    actor,
                    json!({"parent":{"node_id":folder.id},"name":name,"text":"original content"}),
                ),
            ),
        )
        .await
        .unwrap();
        let stat = nodes::read(
            app,
            filesystem,
            "stat",
            request(filesystem, actor, json!({"locator":{"node_id":node.id}})),
        )
        .await
        .unwrap();
        assert_eq!(stat["media_type"], media_type);
    }
    let stat = nodes::read(
        app,
        filesystem,
        "stat",
        request(filesystem, actor, json!({"locator":{"node_id":folder.id}})),
    )
    .await
    .unwrap();
    let copy = admit_copy(
        app,
        filesystem,
        request(
            filesystem,
            actor,
            json!({
            "locator":{"node_id":folder.id}, "revision":stat["revision"], "parent":{"node_id":root},
                "name":"copies", "request_key":Uuid::now_v7()
            }),
        ),
    )
    .await
    .unwrap();
    let completed = finish_copy(app, &copy).await;
    let files =
        sqlx::query("SELECT f.* FROM files f JOIN nodes n ON n.id=f.node_id WHERE n.parent_id=$1")
            .bind(copy.root.destination)
            .fetch_all(&app.pool)
            .await
            .unwrap();
    assert_eq!(files.len(), 3);
    for file in &files {
        let source = fs::processing::Generation {
            file_id: file.get("node_id"),
            generation: file.get("desired_generation"),
        };
        assert!(fs::processing::workflow_running(app, source).await.unwrap());
        assert_eq!(file.get::<&str, _>("publication_status"), "parsed");
        assert_ne!(file.get::<&str, _>("media_type"), "text/plain");
    }
    let before = usage(app, bucket).await;
    for frame in completed {
        fs::copy::finish_file(app, frame).await.unwrap();
    }
    assert_eq!(usage(app, bucket).await, before);
    for file in files {
        let generation: i64 =
            sqlx::query_scalar("SELECT desired_generation FROM files WHERE node_id=$1")
                .bind(file.get::<Uuid, _>("node_id"))
                .fetch_one(&app.pool)
                .await
                .unwrap();
        assert_eq!(
            generation,
            file.get::<i64, _>("desired_generation"),
            "publication retry admitted another generation"
        );
    }
}

#[tokio::test]
#[ignore = "requires Docker; run pnpm --filter @openlet/letfs test:integration"]
async fn artifacts_invalidation_preserves_accounting_and_trash_is_terminal() {
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
    let (upload, _) = create_and_transfer(
        app,
        filesystem,
        actor,
        json!({"parent":{"node_id":root},"name":"report.pdf"}),
        b"old",
        "object",
    )
    .await;
    let source: Uuid = serde_json::from_value(
        fs::uploads::finalize(app, filesystem, upload, actor, None)
            .await
            .unwrap()["node_id"]
            .clone(),
    )
    .unwrap();
    let status = fs::artifacts::status(
        app,
        filesystem,
        request(filesystem, actor, json!({"locator":{"node_id":source}})),
    )
    .await
    .unwrap();
    let publisher = status["desired_generation"].clone();
    let child = artifact_child(app, filesystem, source, "content.md", Some(b"artifact")).await;
    let renamed = nodes::modify(
        app,
        filesystem,
        "rename",
        request(
            filesystem,
            actor,
            json!({"locator":{"node_id":source},"revision":"1","name":"renamed.PDF"}),
        ),
    )
    .await
    .unwrap();
    assert_eq!(
        fs::artifacts::status(
            app,
            filesystem,
            request(filesystem, actor, json!({"locator":{"node_id":source}}))
        )
        .await
        .unwrap()["desired_generation"],
        publisher
    );
    let (replacement, _) = create_and_transfer(
        app,
        filesystem,
        actor,
        json!({"locator":{"node_id":source},"revision":renamed.revision}),
        b"new",
        "inline",
    )
    .await;
    fs::uploads::finalize(app, filesystem, replacement, actor, None)
        .await
        .unwrap();
    assert_eq!(
        usage(app, bucket).await,
        11,
        "invalidated bytes must remain charged until deletion"
    );
    assert!(
        nodes::read(
            app,
            filesystem,
            "stat",
            request(
                filesystem,
                actor,
                json!({"locator":{"path":format!("/drive/@{child}")}})
            )
        )
        .await
        .is_err()
    );
    assert!(
        nodes::read(
            app,
            filesystem,
            "list",
            request(filesystem, actor, json!({"locator":{"node_id":source}}))
        )
        .await
        .unwrap()["items"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    let next = fs::artifacts::status(
        app,
        filesystem,
        request(filesystem, actor, json!({"locator":{"node_id":source}})),
    )
    .await
    .unwrap();
    assert_ne!(next["desired_generation"], publisher);
    assert_eq!(next["publication_status"], "pending");
    assert_eq!(fs::artifacts::discard_forests(app).await.unwrap(), 1);
    assert_eq!(fs::artifacts::discard_forests(app).await.unwrap(), 0);
    assert_eq!(usage(app, bucket).await, 3);
    let count: i64 = sqlx::query_scalar("SELECT node_count FROM filesystems WHERE id=$1")
        .bind(filesystem)
        .fetch_one(&app.pool)
        .await
        .unwrap();
    assert_eq!(count, 2);

    let trashed = fs::trash::trash(
        app,
        filesystem,
        request(
            filesystem,
            actor,
            json!({"locator":{"node_id":source},"revision":"3"}),
        ),
    )
    .await
    .unwrap();
    assert!(
        fs::artifacts::status(
            app,
            filesystem,
            request(filesystem, actor, json!({"locator":{"node_id":source}}))
        )
        .await
        .is_err()
    );
    fs::trash::restore(
        app,
        filesystem,
        request(
            filesystem,
            actor,
            json!({"entry_id":trashed["id"],"revision":"4"}),
        ),
    )
    .await
    .unwrap();
    let failed = fs::artifacts::status(
        app,
        filesystem,
        request(filesystem, actor, json!({"locator":{"node_id":source}})),
    )
    .await
    .unwrap();
    assert_eq!(failed["publication_status"], "failed");
    assert_eq!(failed["error_code"], "SOURCE_TRASHED");
    assert_eq!(failed["desired_generation"], next["desired_generation"]);
    nodes::modify(
        app,
        filesystem,
        "replace-content",
        request(
            filesystem,
            actor,
            json!({"locator":{"node_id":source},"revision":"5","text":"x"}),
        ),
    )
    .await
    .unwrap();
    assert_eq!(
        fs::artifacts::status(
            app,
            filesystem,
            request(filesystem, actor, json!({"locator":{"node_id":source}}))
        )
        .await
        .unwrap()["publication_status"],
        "pending"
    );
    let latest = fs::artifacts::status(
        app,
        filesystem,
        request(filesystem, actor, json!({"locator":{"node_id":source}})),
    )
    .await
    .unwrap();
    assert_ne!(latest["desired_generation"], failed["desired_generation"]);
    assert_eq!(usage(app, bucket).await, 1);
}

// Seed publication provenance for filesystem mutation tests without invoking a parser.
async fn artifact_child(
    app: &App,
    filesystem: Uuid,
    parent: Uuid,
    name: &str,
    data: Option<&[u8]>,
) -> Uuid {
    let mut s = nodes::session(app, filesystem, true).await.unwrap();
    let id = Uuid::now_v7();
    s.add_nodes(1).await.unwrap();
    s.usage(data.map_or(0, |bytes| bytes.len() as i64))
        .await
        .unwrap();
    sqlx::query(
        "INSERT INTO nodes(id,filesystem_id,parent_id,name,kind,size_bytes) \
         VALUES($1,$2,$3,$4,$5,$6)",
    )
    .bind(id)
    .bind(filesystem)
    .bind(parent)
    .bind(name)
    .bind(if data.is_some() { "file" } else { "directory" })
    .bind(data.map_or(0, |bytes| bytes.len() as i64))
    .execute(&mut *s.tx)
    .await
    .unwrap();
    if let Some(data) = data {
        sqlx::query("INSERT INTO files(node_id,storage_kind,inline_bytes) VALUES($1,'inline',$2)")
            .bind(id)
            .bind(data)
            .execute(&mut *s.tx)
            .await
            .unwrap();
    }
    s.tx.commit().await.unwrap();
    id
}

#[tokio::test]
#[ignore = "requires Docker; run pnpm --filter @openlet/letfs test:integration"]
async fn artifacts_paths_and_readonly() {
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
    let (upload, _) = create_and_transfer(
        app,
        filesystem,
        actor,
        json!({"parent":{"node_id":root},"name":"report.PDF"}),
        b"original",
        "inline",
    )
    .await;
    let source: Uuid = serde_json::from_value(
        fs::uploads::finalize(app, filesystem, upload, actor, None)
            .await
            .unwrap()["node_id"]
            .clone(),
    )
    .unwrap();
    let before = nodes::read(
        app,
        filesystem,
        "stat",
        request(filesystem, actor, json!({"locator":{"node_id":source}})),
    )
    .await
    .unwrap();
    let child = artifact_child(app, filesystem, source, "001-intro.md", Some(b"derived")).await;
    let images = artifact_child(app, filesystem, source, "images", None).await;
    let image = artifact_child(app, filesystem, images, "001.png", Some(&[0, 255])).await;
    for locator in [
        json!({"node_id":child}),
        json!({"path":"/drive/report.PDF/001-intro.md"}),
        json!({"path":format!("/drive/@{source}/001-intro.md")}),
        json!({"path":format!("/drive/@{}",child.to_string().to_uppercase())}),
        json!({"path":"001-intro.md","cwd_id":source}),
        json!({"path":format!("@{child}"),"cwd_id":root}),
    ] {
        let stat = nodes::read(
            app,
            filesystem,
            "stat",
            request(filesystem, actor, json!({"locator":locator})),
        )
        .await
        .unwrap();
        assert_eq!(stat["id"], json!(child));
        assert!(
            stat.get("readonly").is_none(),
            "internal provenance leaked into Node contract"
        );
        let mut guarded = locator.clone();
        guarded["expected_node_id"] = json!(child);
        for action in ["replace-content", "rename", "move"] {
            assert_eq!(
                nodes::modify(
                    app,
                    filesystem,
                    action,
                    request(
                        filesystem,
                        actor,
                        json!({
                            "locator":guarded,
                            "revision":"1",
                            "text":"changed",
                            "name":"changed",
                            "parent":{"node_id":root}
                        }),
                    ),
                )
                .await
                .unwrap_err()
                .1,
                "ARTIFACT_READ_ONLY"
            );
        }
        assert_eq!(
            fs::trash::trash(
                app,
                filesystem,
                request(filesystem, actor, json!({"locator":guarded,"revision":"1"}))
            )
            .await
            .unwrap_err()
            .1,
            "ARTIFACT_READ_ONLY"
        );
        assert_eq!(
            fs::uploads::create(
                app,
                filesystem,
                request(
                    filesystem,
                    actor,
                    json!({
                        "locator":guarded,
                        "revision":"1",
                        "storage":"inline",
                        "size_bytes":"1",
                        "request_key":Uuid::now_v7()
                    }),
                ),
            )
            .await
            .unwrap_err()
            .1,
            "ARTIFACT_READ_ONLY"
        );
    }
    for path in [
        "/drive/report.PDF",
        "/drive/report.PDF/",
        "/drive/report.PDF/.",
    ] {
        let children = nodes::read(
            app,
            filesystem,
            "list",
            request(filesystem, actor, json!({"locator":{"path":path}})),
        )
        .await
        .unwrap();
        assert_eq!(children["items"].as_array().unwrap().len(), 2);
    }
    let up = nodes::read(
        app,
        filesystem,
        "stat",
        request(
            filesystem,
            actor,
            json!({"locator":{"path":format!("/drive/@{image}/../..")}}),
        ),
    )
    .await
    .unwrap();
    assert_eq!(up["id"], json!(source));
    let after = nodes::read(
        app,
        filesystem,
        "stat",
        request(filesystem, actor, json!({"locator":{"node_id":source}})),
    )
    .await
    .unwrap();
    assert_eq!(
        before, after,
        "child publication changed source payload metadata"
    );
    let status = fs::artifacts::status(
        app,
        filesystem,
        request(filesystem, actor, json!({"locator":{"node_id":source}})),
    )
    .await
    .unwrap();
    assert_eq!(status["publication_status"], "pending");
    for parent in [source, images] {
        assert!(
            nodes::create(
                app,
                filesystem,
                create_request(
                    "text",
                    request(
                        filesystem,
                        actor,
                        json!({"parent":{"node_id":parent},"name":"injected","text":"bad"})
                    )
                )
            )
            .await
            .is_err()
        );
    }
    let copied = admit_copy(
        app,
        filesystem,
        request(
            filesystem,
            actor,
            json!({
                "locator":{"node_id":child},
                "parent":{"node_id":root},
                "name":"writable.md",
                "revision":"1",
                "request_key":Uuid::now_v7()
            }),
        ),
    )
    .await
    .unwrap();
    finish_copy(app, &copied).await;
    let writable = copied.root.destination;
    nodes::modify(
        app,
        filesystem,
        "replace-content",
        request(
            filesystem,
            actor,
            json!({"locator":{"node_id":writable},"revision":"1","text":"edited"}),
        ),
    )
    .await
    .unwrap();
    assert_eq!(
        admit_copy(
            app,
            filesystem,
            request(
                filesystem,
                actor,
                json!({
                    "locator":{"node_id":child},
                    "parent":{"node_id":images},
                    "name":"denied",
                    "revision":"1",
                    "request_key":Uuid::now_v7()
                }),
            ),
        )
        .await
        .unwrap_err()
        .1,
        "ARTIFACT_READ_ONLY"
    );
    let alias_name = format!("@{}", Uuid::now_v7());
    assert_eq!(
        fs::uploads::create(
            app,
            filesystem,
            request(
                filesystem,
                actor,
                json!({
                    "parent":{"node_id":root},
                    "name":alias_name,
                    "storage":"inline",
                    "size_bytes":"0",
                    "request_key":Uuid::now_v7()
                }),
            ),
        )
        .await
        .unwrap_err()
        .1,
        "VALIDATION"
    );
    assert_eq!(
        admit_copy(
            app,
            filesystem,
            request(
                filesystem,
                actor,
                json!({
                    "locator":{"node_id":child},
                    "parent":{"node_id":root},
                    "name":alias_name,
                    "revision":"1",
                    "request_key":Uuid::now_v7()
                }),
            ),
        )
        .await
        .unwrap_err()
        .1,
        "VALIDATION"
    );
    let trashed = fs::trash::trash(
        app,
        filesystem,
        request(
            filesystem,
            actor,
            json!({"locator":{"node_id":writable},"revision":"2"}),
        ),
    )
    .await
    .unwrap();
    assert_eq!(
        fs::trash::restore(
            app,
            filesystem,
            request(
                filesystem,
                actor,
                json!({"entry_id":trashed["id"],"revision":"3","parent":{"node_id":images}})
            )
        )
        .await
        .unwrap_err()
        .1,
        "ARTIFACT_READ_ONLY"
    );
    assert_eq!(
        fs::trash::restore(
            app,
            filesystem,
            request(
                filesystem,
                actor,
                json!({"entry_id":trashed["id"],"revision":"3","name":alias_name})
            )
        )
        .await
        .unwrap_err()
        .1,
        "VALIDATION"
    );
    fs::trash::restore(
        app,
        filesystem,
        request(
            filesystem,
            actor,
            json!({"entry_id":trashed["id"],"revision":"3"}),
        ),
    )
    .await
    .unwrap();
    assert!(
        nodes::create(
            app,
            filesystem,
            create_request(
                "directories",
                request(
                    filesystem,
                    actor,
                    json!({"parent":{"node_id":root},"name":alias_name})
                )
            )
        )
        .await
        .is_err()
    );
    let normal = nodes::create(
        app,
        filesystem,
        create_request(
            "directories",
            request(
                filesystem,
                actor,
                json!({"parent":{"node_id":root},"name":"normal"}),
            ),
        ),
    )
    .await
    .unwrap();
    let nested = nodes::create(
        app,
        filesystem,
        create_request(
            "directories",
            request(
                filesystem,
                actor,
                json!({"parent":{"node_id":normal.id},"name":alias_name}),
            ),
        ),
    )
    .await
    .unwrap();
    assert_eq!(
        nodes::read(
            app,
            filesystem,
            "stat",
            request(
                filesystem,
                actor,
                json!({"locator":{"path":format!("/drive/normal/{alias_name}")}})
            )
        )
        .await
        .unwrap()["id"],
        json!(nested.id)
    );
    for (action, parent, name) in [
        ("rename", None, alias_name.clone()),
        ("move", Some(root), alias_name.clone()),
    ] {
        assert_eq!(
            nodes::modify(
                app,
                filesystem,
                action,
                request(
                    filesystem,
                    actor,
                    json!({
                        "locator":{"node_id":normal.id},
                        "parent":parent.map(|id|json!({"node_id":id})),
                        "name":name,
                        "revision":"2"
                    }),
                ),
            )
            .await
            .unwrap_err()
            .1,
            "VALIDATION"
        );
    }
    let (foreign, _) = fixture.filesystem(bucket).await;
    assert_eq!(
        nodes::read(
            app,
            foreign,
            "stat",
            request(
                foreign,
                actor,
                json!({"locator":{"path":format!("/drive/@{child}")}})
            )
        )
        .await
        .unwrap_err()
        .0,
        StatusCode::NOT_FOUND
    );
}
