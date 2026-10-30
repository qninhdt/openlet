use super::{nodes::*, paths};
use crate::http::{ApiError, App};
use serde_json::{Value, json};
use sqlx::{PgConnection, Row};
use uuid::Uuid;

pub async fn queue_object(
    conn: &mut PgConnection,
    node: Uuid,
    bucket: Uuid,
) -> Result<(), ApiError> {
    sqlx::query("INSERT INTO object_deletions(object_key,bucket_id) SELECT object_key,$2 FROM file_data WHERE node_id=$1 AND object_key IS NOT NULL ON CONFLICT DO NOTHING").bind(node).bind(bucket).execute(conn).await?;
    Ok(())
}
pub async fn list(s: &mut Session<'_>, input: &Input) -> Result<Value, ApiError> {
    let scope = format!("trash/{}", s.fs);
    let (after, limit) = page(input, &scope)?;
    let rows=sqlx::query("SELECT t.id AS entry_id,t.original_parent_id,t.original_name,t.state,t.created_at AS trashed_at,n.* FROM trash_entries t JOIN nodes n ON n.id=t.node_id AND n.filesystem_id=t.filesystem_id WHERE t.filesystem_id=$1 AND t.id>$2 ORDER BY t.id LIMIT $3")
        .bind(s.fs).bind(after).bind((limit+1)as i64).fetch_all(&mut *s.tx).await?;
    let entries = rows
        .iter()
        .map(|row| {
            let id: Uuid = row.get("entry_id");
            (
                id,
                json!({
                    "id": id,
                    "node": Node::from_row(row),
                    "original_parent_id": row.get::<Option<Uuid>, _>("original_parent_id"),
                    "original_name": row.get::<String, _>("original_name"),
                    "state": row.get::<String, _>("state"),
                    "trashed_at": row.get::<chrono::DateTime<chrono::Utc>, _>("trashed_at"),
                }),
            )
        })
        .collect();
    Ok(paged(entries, limit, &scope))
}
pub async fn trash(app: &App, fs: Uuid, r: Request) -> Result<Value, ApiError> {
    let mut s = session(app, fs, true).await?;
    let l = needed(r.input.locator)?;
    let n = s.resolve(&r.scope, &l).await?;
    paths::guard(&l, n.id, false)?;
    n.writable()?;
    n.revision(r.input.revision.as_deref())?;
    if n.id == s.root {
        return Err(ApiError::state("ROOT_IMMUTABLE"));
    }
    let id = Uuid::now_v7();
    super::artifacts::fence_trashed(&mut s, n.id).await?;
    sqlx::query("INSERT INTO trash_entries(id,filesystem_id,node_id,original_parent_id,original_name,actor_id) VALUES($1,$2,$3,$4,$5,$6)").bind(id).bind(fs).bind(n.id).bind(n.parent_id).bind(&n.name).bind(r.scope.actor_id).execute(&mut *s.tx).await?;
    sqlx::query("UPDATE nodes SET parent_id=NULL WHERE id=$1")
        .bind(n.id)
        .execute(&mut *s.tx)
        .await?;
    bump(&mut s.tx, &[n.id, n.parent_id.unwrap()]).await?;
    let out = json!({"id":id,"state":"trashed","node":fetch(&mut s.tx,n.id).await?});
    s.tx.commit().await?;
    Ok(out)
}
pub async fn restore(app: &App, fs: Uuid, r: Request) -> Result<Node, ApiError> {
    let mut s = session(app, fs, true).await?;
    let entry = needed(r.input.entry_id)?;
    let row=sqlx::query("SELECT t.node_id,t.original_parent_id,t.original_name,t.state FROM trash_entries t WHERE id=$1 AND filesystem_id=$2 FOR UPDATE").bind(entry).bind(fs).fetch_optional(&mut *s.tx).await?.ok_or_else(ApiError::not_found)?;
    if row.get::<String, _>("state") != "trashed" {
        return Err(ApiError::state("TRASH_PURGING"));
    }
    let id: Uuid = row.get("node_id");
    let n = fetch(&mut s.tx, id).await?;
    n.revision(r.input.revision.as_deref())?;
    let parent = if let Some(l) = r.input.parent {
        let p = s.resolve(&r.scope, &l).await?;
        paths::guard(&l, p.id, true)?;
        p.writable()?;
        p.directory()?;
        p.id
    } else {
        let parent: Uuid = row
            .get::<Option<Uuid>, _>("original_parent_id")
            .ok_or_else(ApiError::not_found)?;
        let l = paths::Locator {
            node_id: Some(parent),
            path: None,
            cwd_id: None,
            expected_node_id: None,
            expected_parent_id: None,
        };
        let p = s.resolve(&r.scope, &l).await?;
        p.writable()?;
        p.directory()?;
        p.id
    };
    cycle(&mut s.tx, fs, id, parent).await?;
    if depth(&mut s.tx, fs, parent).await? + 1 + subtree_height(&mut s.tx, fs, id).await? > 128 {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    let name = r.input.name.unwrap_or(row.get("original_name"));
    s.name(parent, &name)?;
    sqlx::query("UPDATE nodes SET parent_id=$2,name=$3 WHERE id=$1")
        .bind(id)
        .bind(parent)
        .bind(name)
        .execute(&mut *s.tx)
        .await?;
    sqlx::query("DELETE FROM trash_entries WHERE id=$1")
        .bind(entry)
        .execute(&mut *s.tx)
        .await?;
    bump(&mut s.tx, &[id, parent]).await?;
    let out = fetch(&mut s.tx, id).await?;
    s.tx.commit().await?;
    Ok(out)
}
pub async fn purge_file(app: &App, fs: Uuid, r: Request) -> Result<(), ApiError> {
    let mut s = session(app, fs, true).await?;
    let entry = needed(r.input.entry_id)?;
    let row = sqlx::query(
        "SELECT node_id,state FROM trash_entries WHERE id=$1 AND filesystem_id=$2 FOR UPDATE",
    )
    .bind(entry)
    .bind(fs)
    .fetch_optional(&mut *s.tx)
    .await?
    .ok_or_else(ApiError::not_found)?;
    if row.get::<String, _>("state") != "trashed" {
        return Err(ApiError::state("TRASH_PURGING"));
    }
    let n = fetch(&mut s.tx, row.get("node_id")).await?;
    n.revision(r.input.revision.as_deref())?;
    if n.kind != "file" || super::artifacts::has_children(&mut s, n.id).await? {
        return Err(ApiError::state("DURABLE_PURGE_REQUIRED"));
    }
    super::deletion::remove(&mut s, &[n.id]).await?;
    s.tx.commit().await?;
    Ok(())
}
