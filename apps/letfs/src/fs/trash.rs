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
    sqlx::query("INSERT INTO object_deletions(object_key,bucket_id) SELECT object_key,$2 FROM files WHERE node_id=$1 AND object_key IS NOT NULL ON CONFLICT DO NOTHING").bind(node).bind(bucket).execute(conn).await?;
    Ok(())
}
pub async fn list(s: &mut Session<'_>, input: &Input) -> Result<Value, ApiError> {
    let scope = format!("trash/{}", s.fs);
    let (after, limit) = page(input, &scope)?;
    let rows=sqlx::query("SELECT t.*,t.id AS entry_id,t.created_at AS trashed_at FROM trash_entries t WHERE t.filesystem_id=$1 AND t.id>$2 ORDER BY t.id LIMIT $3")
        .bind(s.fs).bind(after).bind((limit+1)as i64).fetch_all(&mut *s.tx).await?;
    let entries = rows
        .iter()
        .map(|row| (row.get("entry_id"), value(row)))
        .collect();
    Ok(paged(entries, limit, &scope))
}
fn value(row: &sqlx::postgres::PgRow) -> Value {
    json!({"id":row.get::<Uuid,_>("entry_id"),"node_id":row.get::<Uuid,_>("node_id"),
        "parent_id":row.get::<Option<Uuid>,_>("original_parent_id"),"name":row.get::<String,_>("original_name"),
        "actor_id":row.get::<Uuid,_>("actor_id"),"status":row.get::<String,_>("state"),
        "created_at":row.get::<chrono::DateTime<chrono::Utc>,_>("trashed_at")})
}
pub async fn entry(s: &mut Session<'_>, id: Uuid) -> Result<Option<Value>, ApiError> {
    let row=sqlx::query("SELECT t.*,t.id AS entry_id,t.created_at AS trashed_at FROM trash_entries t WHERE t.filesystem_id=$1 AND t.id=$2")
        .bind(s.fs).bind(id).fetch_optional(&mut *s.tx).await?;
    Ok(row.as_ref().map(value))
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
    let out = entry(&mut s, id).await?.ok_or_else(ApiError::not_found)?;
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
    if let Some(revision) = r.input.revision.as_deref() {
        n.revision(Some(revision))?;
    }
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
