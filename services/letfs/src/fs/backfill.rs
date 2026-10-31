use super::{artifacts, nodes::*, paths};
use crate::http::{ApiError, App};
use serde_json::json;
use sha2::{Digest, Sha256};
use sqlx::Row;
use uuid::Uuid;

pub async fn run(app: &App, args: &[String]) -> Result<(), String> {
    let mut mode = "missing";
    let mut apply = false;
    let mut after = Uuid::nil();
    let mut limit = 100_i64;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--apply" => apply = true,
            "--mode" => {
                i += 1;
                mode = args.get(i).ok_or("missing mode")?;
            }
            "--after" => {
                i += 1;
                after = args
                    .get(i)
                    .ok_or("missing cursor")?
                    .parse()
                    .map_err(|_| "invalid cursor")?;
            }
            "--limit" => {
                i += 1;
                limit = args
                    .get(i)
                    .ok_or("missing limit")?
                    .parse()
                    .map_err(|_| "invalid limit")?;
            }
            _ => return Err("unknown backfill option".into()),
        }
        i += 1;
    }
    if !matches!(mode, "missing" | "rebuild-index") || !(1..=1000).contains(&limit) {
        return Err("invalid backfill mode or limit".into());
    }
    let rows = sqlx::query(
        r#"WITH RECURSIVE live AS (
            SELECT n.id, n.filesystem_id, n.kind, 0 AS depth
            FROM nodes n
            JOIN filesystems f ON f.root_id = n.id
            JOIN quota_buckets b ON b.id = f.bucket_id
            WHERE f.state = 'active' AND b.state = 'active'
            UNION ALL
            SELECT n.id, n.filesystem_id, n.kind, l.depth + 1
            FROM nodes n
            JOIN live l ON n.parent_id = l.id AND n.filesystem_id = l.filesystem_id
            WHERE l.kind = 'directory' AND l.depth < 128
        )
        SELECT n.id, n.filesystem_id, n.name, o.id AS operation_id
        FROM live l
        JOIN nodes n ON n.id = l.id
        JOIN file_data d ON d.node_id = n.id
        LEFT JOIN operations o
            ON o.source_id = n.id
            AND o.kind = 'process-file'
            AND o.superseded_at IS NULL
        WHERE n.id > $1 AND (
            ($2 = 'missing' AND (o.id IS NULL OR o.index_state != 'succeeded'))
            OR ($2 = 'rebuild-index' AND o.enrichment_state = 'succeeded' AND o.index_state IN ('succeeded','failed'))
        )
        ORDER BY n.id
        LIMIT $3"#,
    )
    .bind(after)
    .bind(mode)
    .bind(limit + 1)
    .fetch_all(&app.pool)
    .await
    .map_err(|_| "backfill query failed")?;
    let more = rows.len() as i64 > limit;
    let mut eligible = 0;
    let mut applied = 0;
    let mut cursor = None;
    let actor = Uuid::now_v7();
    for row in rows.iter().take(limit as usize) {
        let id: Uuid = row.get("id");
        cursor = Some(id);
        if artifacts::eligible_format(row.get("name")).is_none()
            && row.get::<Option<Uuid>, _>("operation_id").is_none()
        {
            continue;
        }
        eligible += 1;
        if !apply {
            continue;
        }
        let fs: Uuid = row.get("filesystem_id");
        let page_operation: Option<Uuid> = row.get("operation_id");
        if let Some(op) = page_operation
            && super::processing::workflow_running(app, op)
                .await
                .map_err(|_| "workflow state unavailable")?
        {
            continue;
        }
        let mut s = session(app, fs, true)
            .await
            .map_err(|_| "backfill scope unavailable")?;
        let scope = paths::Scope {
            actor_id: actor,
            mounts: vec![paths::Mount {
                path: "/".into(),
                filesystem_id: fs,
            }],
        };
        let node = s
            .resolve(
                &scope,
                &paths::Locator {
                    node_id: Some(id),
                    path: None,
                    cwd_id: None,
                    expected_node_id: None,
                    expected_parent_id: None,
                },
            )
            .await
            .map_err(|_| "backfill source changed")?;
        node.writable()
            .map_err(|_| "backfill source is an artifact")?;
        let prior = sqlx::query(
            "SELECT id,state,index_state FROM operations WHERE source_id=$1 AND kind='process-file' AND superseded_at IS NULL FOR UPDATE",
        )
        .bind(id)
        .fetch_optional(&mut *s.tx)
        .await
        .map_err(|_| "backfill operation unavailable")?;
        let operation = if let Some(prior) = prior {
            let op: Uuid = prior.get("id");
            if Some(op) != page_operation {
                continue;
            }
            if mode == "rebuild-index" {
                if !matches!(prior.get::<&str, _>("index_state"), "succeeded" | "failed")
                    || super::processing::workflow_running(app, op)
                        .await
                        .map_err(|_| "workflow state unavailable")?
                {
                    continue;
                }
                sqlx::query("UPDATE operations SET index_state='pending',index_error=NULL,indexed_at=NULL,index_cleanup_state='pending',updated_at=now() WHERE id=$1")
                    .bind(op)
                    .execute(&mut *s.tx)
                    .await
                    .map_err(|_| "rebuild reset failed")?;
                op
            } else if prior.get::<&str, _>("state") == "succeeded" {
                sqlx::query("UPDATE operations SET enrichment_state=CASE WHEN enrichment_state='failed' THEN 'pending' ELSE enrichment_state END,index_state=CASE WHEN index_state='failed' THEN 'pending' ELSE index_state END,updated_at=now() WHERE id=$1")
                    .bind(op)
                    .execute(&mut *s.tx)
                    .await
                    .map_err(|_| "backfill reset failed")?;
                op
            } else {
                artifacts::invalidate(&mut s, id, actor)
                    .await
                    .map_err(|_| "backfill invalidate failed")?;
                record(&mut s, &node, actor)
                    .await
                    .map_err(|_| "backfill intent failed")?
            }
        } else {
            let op = record(&mut s, &node, actor)
                .await
                .map_err(|_| "backfill intent failed")?;
            if artifacts::has_children(&mut s, id)
                .await
                .map_err(|_| "backfill inventory failed")?
            {
                sqlx::query(
                    "UPDATE operations SET state='succeeded',result_node_id=$2 WHERE id=$1",
                )
                .bind(op)
                .bind(id)
                .execute(&mut *s.tx)
                .await
                .map_err(|_| "backfill artifact adoption failed")?;
            }
            op
        };
        s.tx.commit().await.map_err(|_| "backfill commit failed")?;
        crate::temporal::process_file_workflow::dispatch(app, operation)
            .await
            .map_err(|_| "backfill dispatch failed")?;
        applied += 1;
    }
    println!(
        "{}",
        json!({
            "mode": mode,
            "apply": apply,
            "scanned": rows.len().min(limit as usize),
            "eligible": eligible,
            "applied": applied,
            "next_cursor": if more { cursor } else { None },
        })
    );
    Ok(())
}
async fn record(s: &mut Session<'_>, node: &Node, actor: Uuid) -> Result<Uuid, ApiError> {
    let data = sqlx::query("SELECT object_key,inline_bytes FROM file_data WHERE node_id=$1")
        .bind(node.id)
        .fetch_one(&mut *s.tx)
        .await?;
    let key: Option<String> = data.get("object_key");
    let digest = data
        .get::<Option<Vec<u8>>, _>("inline_bytes")
        .map(|b| format!("{:x}", Sha256::digest(b)));
    artifacts::record_intent(
        s,
        node,
        actor,
        Uuid::now_v7(),
        key.as_deref(),
        digest.as_deref(),
    )
    .await?
    .ok_or_else(|| ApiError::bad("source format unsupported"))
}
