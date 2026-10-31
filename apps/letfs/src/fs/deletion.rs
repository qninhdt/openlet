use super::nodes::{self, Session};
use crate::http::{ApiError, App};
use serde::{Deserialize, Serialize};
use sqlx::Row;
use uuid::Uuid;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Start {
    pub filesystem_id: Uuid,
    pub actor_id: Uuid,
    pub entry_id: Option<Uuid>,
    pub revision: Option<String>,
}
impl Start {
    pub fn workflow_id(&self) -> String {
        match self.entry_id {
            Some(entry) => format!("purge-trash/{}/{entry}", self.filesystem_id),
            None => format!("delete-filesystem/{}", self.filesystem_id),
        }
    }
    pub fn identity(&self) -> Uuid {
        self.entry_id.unwrap_or(self.filesystem_id)
    }
    fn validate(&self) -> Result<(), ApiError> {
        if self.filesystem_id.is_nil()
            || self.actor_id.is_nil()
            || self.entry_id.is_some_and(|v| v.is_nil())
        {
            return Err(ApiError::bad("invalid deletion identity"));
        }
        Ok(())
    }
}
pub async fn prepare(app: &App, input: Start) -> Result<Start, ApiError> {
    input.validate()?;
    let mut s = nodes::lifecycle_session(app, input.filesystem_id).await?;
    if let Some(entry) = input.entry_id {
        let row = sqlx::query(
            "SELECT node_id,state FROM trash_entries WHERE id=$1 AND filesystem_id=$2 FOR UPDATE",
        )
        .bind(entry)
        .bind(s.fs)
        .fetch_optional(&mut *s.tx)
        .await?;
        if let Some(row) = row
            && row.get::<&str, _>("state") == "trashed"
        {
            let state: String = sqlx::query_scalar("SELECT state FROM quota_buckets WHERE id=$1")
                .bind(s.bucket)
                .fetch_one(&mut *s.tx)
                .await?;
            if state != "active" {
                return Err(ApiError::state("BUCKET_FROZEN"));
            }
            if let Some(revision) = input.revision.as_deref() {
                nodes::fetch(&mut s.tx, row.get("node_id"))
                    .await?
                    .revision(Some(revision))?;
            }
            sqlx::query("UPDATE trash_entries SET state='purging' WHERE id=$1")
                .bind(entry)
                .execute(&mut *s.tx)
                .await?;
        }
    } else {
        let state: String = sqlx::query_scalar("SELECT state FROM filesystems WHERE id=$1")
            .bind(s.fs)
            .fetch_one(&mut *s.tx)
            .await?;
        if state == "active" {
            sqlx::query("UPDATE filesystems SET state='deleting' WHERE id=$1")
                .bind(s.fs)
                .execute(&mut *s.tx)
                .await?;
            // The filesystem lock fences publication before any cleanup is enumerated.
            sqlx::query("INSERT INTO index_deletions(file_id,generation,embedding_model,vector_collection,vector_dimension) SELECT f.node_id,f.desired_generation,f.embedding_model,f.vector_collection,f.vector_dimension FROM files f JOIN nodes n ON n.id=f.node_id WHERE n.filesystem_id=$1 AND f.embedding_model IS NOT NULL AND f.vector_collection IS NOT NULL AND f.vector_dimension IS NOT NULL ON CONFLICT DO NOTHING")
                .bind(s.fs).execute(&mut *s.tx).await?;
            sqlx::query("UPDATE idempotency_keys SET completed_at=now(),expires_at=now()+interval '24 hours' WHERE operation='copy-node' AND result->>'filesystem_id'=$1 AND completed_at IS NULL").bind(s.fs.to_string()).execute(&mut *s.tx).await?;
            sqlx::query("INSERT INTO object_deletions(object_key,bucket_id,ambiguous_write,eligible_at) SELECT candidate_key,bucket_id,true,greatest(now()+interval '15 minutes',transfer_deadline) FROM uploads WHERE filesystem_id=$1 AND result_node_id IS NULL AND candidate_key IS NOT NULL ON CONFLICT(object_key) DO UPDATE SET ambiguous_write=true,state='pending',eligible_at=greatest(object_deletions.eligible_at,excluded.eligible_at)")
                .bind(s.fs).execute(&mut *s.tx).await?;
            sqlx::query("UPDATE uploads SET state=CASE WHEN state IN ('open','completing') THEN 'aborted' ELSE state END,inline_bytes=NULL,updated_at=now() WHERE filesystem_id=$1 AND result_node_id IS NULL")
                .bind(s.fs).execute(&mut *s.tx).await?;
            sqlx::query("UPDATE idempotency_keys r SET completed_at=now(),expires_at=now()+interval '24 hours' FROM uploads u WHERE u.filesystem_id=$1 AND u.state='aborted' AND r.operation='create-upload' AND r.result->>'id'=u.id::text AND r.completed_at IS NULL")
                .bind(s.fs).execute(&mut *s.tx).await?;
        }
    }
    s.tx.commit().await?;
    Ok(input)
}

// Node removal and actual quota debit commit together.
pub async fn remove(s: &mut Session<'_>, ids: &[Uuid]) -> Result<(i64, i64), ApiError> {
    super::indexing::enqueue(s, ids).await?;
    let sources=sqlx::query("SELECT node_id,desired_generation FROM files WHERE node_id=ANY($1) AND desired_generation>0")
        .bind(ids).fetch_all(&mut *s.tx).await?;
    for row in sources {
        let source = super::processing::Generation {
            file_id: row.get("node_id"),
            generation: row.get("desired_generation"),
        };
        super::processing::discard_uploads(s, source, None).await?;
        super::processing::complete_receipt(s, source).await?;
    }
    sqlx::query("INSERT INTO object_deletions(object_key,bucket_id) SELECT d.object_key,$2 FROM files d JOIN nodes n ON n.id=d.node_id WHERE n.id=ANY($1) AND n.filesystem_id=$3 AND d.object_key IS NOT NULL ON CONFLICT(object_key) DO UPDATE SET state='pending',eligible_at=least(object_deletions.eligible_at,excluded.eligible_at)")
        .bind(ids).bind(s.bucket).bind(s.fs).execute(&mut *s.tx).await?;
    sqlx::query("DELETE FROM trash_entries WHERE filesystem_id=$1 AND node_id=ANY($2)")
        .bind(s.fs)
        .bind(ids)
        .execute(&mut *s.tx)
        .await?;
    sqlx::query("UPDATE trash_entries SET original_parent_id=NULL WHERE filesystem_id=$1 AND original_parent_id=ANY($2)").bind(s.fs).bind(ids).execute(&mut *s.tx).await?;
    let removed =
        sqlx::query("DELETE FROM nodes WHERE filesystem_id=$1 AND id=ANY($2) RETURNING size_bytes")
            .bind(s.fs)
            .bind(ids)
            .fetch_all(&mut *s.tx)
            .await?;
    let bytes: i64 = removed.iter().map(|r| r.get::<i64, _>("size_bytes")).sum();
    s.usage(-bytes).await?;
    s.add_nodes(-(removed.len() as i64)).await?;
    Ok((removed.len() as i64, bytes))
}
pub async fn leaves(s: &mut Session<'_>, root: Uuid) -> Result<Vec<Uuid>, ApiError> {
    let leaf = sqlx::query("WITH RECURSIVE branch AS (SELECT id,parent_id,0 AS depth FROM nodes WHERE id=$1 AND filesystem_id=$2 UNION ALL SELECT n.id,n.parent_id,b.depth+1 FROM branch b JOIN LATERAL (SELECT id,parent_id FROM nodes WHERE filesystem_id=$2 AND parent_id=b.id ORDER BY name LIMIT 1) n ON true WHERE b.depth<128) SELECT id,parent_id FROM branch ORDER BY depth DESC LIMIT 1")
        .bind(root).bind(s.fs).fetch_optional(&mut *s.tx).await?;
    let Some(leaf) = leaf else {
        return Ok(vec![]);
    };
    let ids = sqlx::query_scalar("SELECT n.id FROM nodes n WHERE n.filesystem_id=$1 AND (n.id=$2 OR n.parent_id=$3) AND NOT EXISTS(SELECT 1 FROM nodes c WHERE c.filesystem_id=$1 AND c.parent_id=n.id) ORDER BY n.name LIMIT 64")
        .bind(s.fs).bind(leaf.get::<Uuid,_>("id")).bind(leaf.get::<Option<Uuid>,_>("parent_id")).fetch_all(&mut *s.tx).await?;
    if ids.is_empty() {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    Ok(ids)
}
pub async fn batch(app: &App, input: &Start) -> Result<bool, ApiError> {
    let mut s = nodes::lifecycle_session(app, input.filesystem_id).await?;
    let ids: Vec<Uuid> = if let Some(entry) = input.entry_id {
        let row =
            sqlx::query("SELECT node_id,state FROM trash_entries WHERE filesystem_id=$1 AND id=$2")
                .bind(s.fs)
                .bind(entry)
                .fetch_optional(&mut *s.tx)
                .await?;
        let Some(row) = row else {
            return Ok(true);
        };
        if row.get::<&str, _>("state") != "purging" {
            return Err(ApiError::state("TRASH_NOT_PURGING"));
        }
        leaves(&mut s, row.get("node_id")).await?
    } else {
        let state: String = sqlx::query_scalar("SELECT state FROM filesystems WHERE id=$1")
            .bind(s.fs)
            .fetch_one(&mut *s.tx)
            .await?;
        if state == "deleted" {
            return Ok(true);
        }
        if state != "deleting" {
            return Err(ApiError::state("FILESYSTEM_NOT_DELETING"));
        }
        sqlx::query_scalar("SELECT n.id FROM nodes n WHERE n.filesystem_id=$1 AND NOT EXISTS(SELECT 1 FROM nodes c WHERE c.filesystem_id=$1 AND c.parent_id=n.id) ORDER BY n.id LIMIT 64")
            .bind(s.fs).fetch_all(&mut *s.tx).await?
    };
    if input.entry_id.is_none() && ids.contains(&s.root) {
        sqlx::query("UPDATE filesystems SET root_id=NULL WHERE id=$1")
            .bind(s.fs)
            .execute(&mut *s.tx)
            .await?;
    }
    remove(&mut s, &ids).await?;
    let done: bool = if let Some(entry) = input.entry_id {
        !sqlx::query_scalar::<_, bool>(
            "SELECT EXISTS(SELECT 1 FROM trash_entries WHERE filesystem_id=$1 AND id=$2)",
        )
        .bind(s.fs)
        .bind(entry)
        .fetch_one(&mut *s.tx)
        .await?
    } else {
        let remaining: bool =
            sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM nodes WHERE filesystem_id=$1)")
                .bind(s.fs)
                .fetch_one(&mut *s.tx)
                .await?;
        if !remaining {
            sqlx::query(
                "UPDATE filesystems SET state='deleted',root_id=NULL WHERE id=$1 AND node_count=0",
            )
            .bind(s.fs)
            .execute(&mut *s.tx)
            .await?;
        }
        !remaining
    };
    s.tx.commit().await?;
    Ok(done)
}
