use super::nodes::{self, Session};
use crate::http::{ApiError, App};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sqlx::Row;
use uuid::Uuid;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Start {
    pub filesystem_id: Uuid,
    pub actor_id: Uuid,
    pub request_key: Uuid,
    pub entry_id: Option<Uuid>,
    pub revision: Option<String>,
}
impl Start {
    pub fn kind(&self) -> &'static str {
        if self.entry_id.is_some() {
            "purge"
        } else {
            "delete-filesystem"
        }
    }
    pub fn workflow_id(&self) -> String {
        format!(
            "{}/{}/{}/{}",
            self.kind(),
            self.filesystem_id,
            self.actor_id,
            self.request_key
        )
    }
    pub fn validate(&self) -> Result<(), ApiError> {
        if self.filesystem_id.is_nil()
            || self.actor_id.is_nil()
            || self.request_key.is_nil()
            || self.entry_id.is_some_and(|v| v.is_nil())
        {
            return Err(ApiError::bad("invalid deletion identity"));
        }
        Ok(())
    }
}
pub async fn existing(app: &App, input: &Start) -> Result<Option<Value>, ApiError> {
    input.validate()?;
    let row = sqlx::query("SELECT id,fingerprint FROM operations WHERE filesystem_id=$1 AND actor_id=$2 AND kind=$3 AND request_key=$4")
        .bind(input.filesystem_id).bind(input.actor_id).bind(input.kind()).bind(input.request_key).fetch_optional(&app.pool).await?;
    if let Some(row) = row {
        if row.get::<Value, _>("fingerprint") != json!(input) {
            return Err(ApiError::state("IDEMPOTENCY_CONFLICT"));
        }
        return super::copy::operation(app, input.filesystem_id, row.get("id"))
            .await
            .map(Some);
    }
    Ok(None)
}
pub async fn prepare(app: &App, input: Start) -> Result<Uuid, ApiError> {
    input.validate()?;
    let mut s = nodes::lifecycle_session(app, input.filesystem_id).await?;
    let old = sqlx::query("SELECT id,fingerprint FROM operations WHERE filesystem_id=$1 AND actor_id=$2 AND kind=$3 AND request_key=$4")
        .bind(s.fs).bind(input.actor_id).bind(input.kind()).bind(input.request_key).fetch_optional(&mut *s.tx).await?;
    if let Some(row) = old {
        if row.get::<Value, _>("fingerprint") != json!(input) {
            return Err(ApiError::state("IDEMPOTENCY_CONFLICT"));
        }
        return Ok(row.get("id"));
    }
    let state: String = sqlx::query_scalar("SELECT state FROM filesystems WHERE id=$1")
        .bind(s.fs)
        .fetch_one(&mut *s.tx)
        .await?;
    if state != "active" {
        return Err(ApiError::state("FILESYSTEM_DELETING"));
    }
    let op = Uuid::now_v7();
    let root = if let Some(entry) = input.entry_id {
        let row = sqlx::query(
            "SELECT node_id,state FROM trash_entries WHERE id=$1 AND filesystem_id=$2 FOR UPDATE",
        )
        .bind(entry)
        .bind(s.fs)
        .fetch_optional(&mut *s.tx)
        .await?
        .ok_or_else(ApiError::not_found)?;
        if row.get::<String, _>("state") != "trashed" {
            return Err(ApiError::state("TRASH_PURGING"));
        }
        let node = nodes::fetch(&mut s.tx, row.get("node_id")).await?;
        node.revision(input.revision.as_deref())?;
        let bucket_state: String =
            sqlx::query_scalar("SELECT state FROM quota_buckets WHERE id=$1")
                .bind(s.bucket)
                .fetch_one(&mut *s.tx)
                .await?;
        if bucket_state != "active" {
            return Err(ApiError::state("BUCKET_FROZEN"));
        }
        sqlx::query("UPDATE trash_entries SET state='purging' WHERE id=$1")
            .bind(entry)
            .execute(&mut *s.tx)
            .await?;
        Some(node.id)
    } else {
        sqlx::query("UPDATE filesystems SET state='deleting' WHERE id=$1")
            .bind(s.fs)
            .execute(&mut *s.tx)
            .await?;
        // Publication is fenced by the filesystem lock before any cleanup is enumerated.
        sqlx::query("UPDATE operations SET state='failed',error_code='FILESYSTEM_DELETED',updated_at=now() WHERE filesystem_id=$1 AND state IN ('running','discarding')").bind(s.fs).execute(&mut *s.tx).await?;
        sqlx::query("INSERT INTO object_deletions(object_key,bucket_id,ambiguous_write,eligible_at) SELECT candidate_key,bucket_id,true,greatest(now()+interval '15 minutes',transfer_deadline) FROM uploads WHERE filesystem_id=$1 AND state!='finalized' AND candidate_key IS NOT NULL ON CONFLICT(object_key) DO UPDATE SET ambiguous_write=true,state='pending',eligible_at=greatest(object_deletions.eligible_at,excluded.eligible_at)").bind(s.fs).execute(&mut *s.tx).await?;
        sqlx::query("UPDATE uploads SET state='aborted',updated_at=now() WHERE filesystem_id=$1 AND state IN ('created','transferring','uploaded')").bind(s.fs).execute(&mut *s.tx).await?;
        sqlx::query("INSERT INTO object_deletions(object_key,bucket_id,ambiguous_write) SELECT c.target_key,$2,true FROM copy_items c JOIN operations o ON o.id=c.operation_id WHERE o.filesystem_id=$1 AND o.state!='succeeded' AND c.target_key IS NOT NULL ON CONFLICT(object_key) DO UPDATE SET ambiguous_write=true,state='pending',eligible_at=greatest(object_deletions.eligible_at,now()+interval '15 minutes')").bind(s.fs).bind(s.bucket).execute(&mut *s.tx).await?;
        None
    };
    sqlx::query("INSERT INTO operations(id,filesystem_id,actor_id,kind,request_key,fingerprint,durable,staging_root_id) VALUES($1,$2,$3,$4,$5,$6,true,$7)")
        .bind(op).bind(s.fs).bind(input.actor_id).bind(input.kind()).bind(input.request_key).bind(json!(&input)).bind(root).execute(&mut *s.tx).await?;
    if let Some(root) = root {
        sqlx::query("INSERT INTO deletion_items(operation_id,node_id,depth) VALUES($1,$2,0)")
            .bind(op)
            .bind(root)
            .execute(&mut *s.tx)
            .await?;
    }
    s.tx.commit().await?;
    Ok(op)
}

// Both charged published nodes and uncharged staging are removed in this transaction.
pub async fn remove(s: &mut Session<'_>, ids: &[Uuid]) -> Result<(i64, i64), ApiError> {
    sqlx::query("INSERT INTO object_deletions(object_key,bucket_id,ambiguous_write) SELECT d.object_key,$2,(n.staging_operation_id IS NOT NULL AND o.state!='succeeded') FROM file_data d JOIN nodes n ON n.id=d.node_id LEFT JOIN operations o ON o.id=n.staging_operation_id WHERE n.id=ANY($1) AND n.filesystem_id=$3 AND d.object_key IS NOT NULL ON CONFLICT(object_key) DO UPDATE SET ambiguous_write=object_deletions.ambiguous_write OR excluded.ambiguous_write")
        .bind(ids).bind(s.bucket).bind(s.fs).execute(&mut *s.tx).await?;
    sqlx::query("DELETE FROM trash_entries WHERE filesystem_id=$1 AND node_id=ANY($2)")
        .bind(s.fs)
        .bind(ids)
        .execute(&mut *s.tx)
        .await?;
    sqlx::query("UPDATE trash_entries SET original_parent_id=NULL WHERE filesystem_id=$1 AND original_parent_id=ANY($2)").bind(s.fs).bind(ids).execute(&mut *s.tx).await?;
    let removed=sqlx::query("WITH removed AS (DELETE FROM nodes WHERE filesystem_id=$1 AND id=ANY($2) RETURNING size_bytes,staging_operation_id) SELECT r.size_bytes,(r.staging_operation_id IS NULL OR o.state='succeeded') AS charged FROM removed r LEFT JOIN operations o ON o.id=r.staging_operation_id").bind(s.fs).bind(ids).fetch_all(&mut *s.tx).await?;
    let bytes: i64 = removed
        .iter()
        .filter(|r| r.get::<bool, _>("charged"))
        .map(|r| r.get::<i64, _>("size_bytes"))
        .sum();
    s.usage(-bytes).await?;
    s.add_nodes(-(removed.len() as i64)).await?;
    Ok((removed.len() as i64, bytes))
}
pub async fn batch(app: &App, op: Uuid) -> Result<bool, ApiError> {
    let fs: Uuid = sqlx::query_scalar("SELECT filesystem_id FROM operations WHERE id=$1")
        .bind(op)
        .fetch_one(&app.pool)
        .await?;
    let mut s = nodes::lifecycle_session(app, fs).await?;
    let row =
        sqlx::query("SELECT state,kind,deletion_cursor FROM operations WHERE id=$1 FOR UPDATE")
            .bind(op)
            .fetch_one(&mut *s.tx)
            .await?;
    if row.get::<String, _>("state") != "running" {
        return Ok(true);
    }
    let filesystem = row.get::<String, _>("kind") == "delete-filesystem";
    let ids:Vec<Uuid>=sqlx::query_scalar("SELECT i.node_id FROM deletion_items i JOIN nodes n ON n.id=i.node_id AND n.filesystem_id=$2 WHERE i.operation_id=$1 AND NOT EXISTS(SELECT 1 FROM nodes c WHERE c.filesystem_id=$2 AND c.parent_id=n.id) ORDER BY i.depth DESC,i.node_id LIMIT 64")
        .bind(op).bind(fs).fetch_all(&mut *s.tx).await?;
    if !ids.is_empty() {
        if filesystem && ids.contains(&s.root) {
            // The deferred root FK and this update commit together only at logical completion.
            sqlx::query("UPDATE filesystems SET root_id=NULL WHERE id=$1").bind(fs).execute(&mut *s.tx).await?;
        }
        remove(&mut s,&ids).await?;
        sqlx::query("DELETE FROM deletion_items WHERE operation_id=$1 AND node_id=ANY($2)").bind(op).bind(&ids).execute(&mut *s.tx).await?;
    } else if let Some(dir)=sqlx::query("SELECT node_id,depth,child_cursor FROM deletion_items WHERE operation_id=$1 ORDER BY depth DESC,node_id LIMIT 1").bind(op).fetch_optional(&mut *s.tx).await? {
        let children:Vec<Uuid>=sqlx::query_scalar("SELECT id FROM nodes WHERE filesystem_id=$1 AND parent_id=$2 AND id>$3 ORDER BY id LIMIT 64").bind(fs).bind(dir.get::<Uuid,_>("node_id")).bind(dir.get::<Uuid,_>("child_cursor")).fetch_all(&mut *s.tx).await?;
        if children.is_empty() {return Err(ApiError::state("DELETION_INVARIANT"));}
        sqlx::query("INSERT INTO deletion_items(operation_id,node_id,depth) SELECT $1,unnest($2::uuid[]),$3 ON CONFLICT DO NOTHING").bind(op).bind(&children).bind(dir.get::<i32,_>("depth")+1).execute(&mut *s.tx).await?;
        sqlx::query("UPDATE deletion_items SET child_cursor=$3 WHERE operation_id=$1 AND node_id=$2").bind(op).bind(dir.get::<Uuid,_>("node_id")).bind(children.last()).execute(&mut *s.tx).await?;
    } else if filesystem {
        let roots:Vec<Uuid>=sqlx::query_scalar("SELECT id FROM nodes WHERE filesystem_id=$1 AND parent_id IS NULL AND id>$2 ORDER BY id LIMIT 64").bind(fs).bind(row.get::<Uuid,_>("deletion_cursor")).fetch_all(&mut *s.tx).await?;
        if !roots.is_empty() {
            sqlx::query("INSERT INTO deletion_items(operation_id,node_id,depth) SELECT $1,unnest($2::uuid[]),0 ON CONFLICT DO NOTHING").bind(op).bind(&roots).execute(&mut *s.tx).await?;
            sqlx::query("UPDATE operations SET deletion_cursor=$2 WHERE id=$1").bind(op).bind(roots.last()).execute(&mut *s.tx).await?;
        }
    }
    let remaining: bool =
        sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM deletion_items WHERE operation_id=$1)")
            .bind(op)
            .fetch_one(&mut *s.tx)
            .await?;
    let nodes_left: bool = if filesystem {
        sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM nodes WHERE filesystem_id=$1)")
            .bind(fs)
            .fetch_one(&mut *s.tx)
            .await?
    } else {
        false
    };
    let done = !remaining && !nodes_left;
    if filesystem && done {
        // A deleted live root can precede detached roots; keep the tombstone root ID separately in operation state.
        sqlx::query(
            "UPDATE filesystems SET state='deleted',root_id=NULL WHERE id=$1 AND node_count=0",
        )
        .bind(fs)
        .execute(&mut *s.tx)
        .await?;
    }
    if done {
        sqlx::query("UPDATE operations SET state='succeeded',updated_at=now() WHERE id=$1")
            .bind(op)
            .execute(&mut *s.tx)
            .await?;
    }
    s.tx.commit().await?;
    Ok(done)
}
