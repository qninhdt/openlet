use super::nodes::{Node, Request, Session, lifecycle_session, needed, session};
use super::processing::{self, Generation};
use crate::http::{ApiError, App};
use serde_json::{Value, json};
use sqlx::Row;
use uuid::Uuid;

pub fn format(name: &str) -> Option<&'static str> {
    match name.rsplit_once('.')?.1.to_ascii_lowercase().as_str() {
        "pdf" => Some("pdf"),
        "docx" => Some("docx"),
        "xlsx" => Some("xlsx"),
        "pptx" => Some("pptx"),
        _ => None,
    }
}

pub fn eligible_format(name: &str) -> Option<&'static str> {
    if let Some(format) = format(name) {
        return Some(format);
    }
    match name.rsplit_once('.')?.1.to_ascii_lowercase().as_str() {
        "csv" => Some("csv"),
        "png" | "jpg" | "jpeg" | "webp" | "gif" => Some("image"),
        "txt" | "md" | "markdown" | "rst" | "json" | "jsonl" | "yaml" | "yml" | "xml" | "html"
        | "htm" | "css" | "js" | "ts" | "tsx" | "jsx" | "py" | "rs" | "go" | "java" | "c" | "h"
        | "cpp" | "sh" | "sql" | "log" | "toml" | "ini" | "cfg" => Some("text"),
        _ => None,
    }
}

pub async fn dispatch_pending(app: &App, file: Uuid) {
    let row=sqlx::query("SELECT desired_generation FROM files WHERE node_id=$1 AND (publication_status IN ('pending','parsed') OR (publication_status='ready' AND index_status='pending'))")
        .bind(file).fetch_optional(&app.pool).await;
    match row {
        Ok(Some(row)) => {
            let source = Generation {
                file_id: file,
                generation: row.get("desired_generation"),
            };
            if crate::temporal::process_file_workflow::dispatch(app, source)
                .await
                .is_err()
            {
                tracing::warn!("processing dispatch deferred");
            }
        }
        Ok(None) => {}
        Err(_) => tracing::warn!("processing dispatch lookup deferred"),
    }
}
pub async fn has_children(s: &mut Session<'_>, node: Uuid) -> Result<bool, ApiError> {
    Ok(sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM nodes WHERE filesystem_id=$1 AND parent_id=$2)",
    )
    .bind(s.fs)
    .bind(node)
    .fetch_one(&mut *s.tx)
    .await?)
}
pub async fn invalidate(s: &mut Session<'_>, file: Uuid) -> Result<(), ApiError> {
    if let Some(generation) = sqlx::query_scalar::<_, i64>(
        "SELECT desired_generation FROM files WHERE node_id=$1 FOR UPDATE",
    )
    .bind(file)
    .fetch_optional(&mut *s.tx)
    .await?
    {
        let source = Generation {
            file_id: file,
            generation,
        };
        super::indexing::enqueue(s, &[file]).await?;
        processing::discard_uploads(s, source, None).await?;
        processing::complete_receipt(s, source).await?;
    }
    sqlx::query("UPDATE files SET title=NULL,description=NULL,semantic_type=NULL,context=NULL,publication_status='not_required',published_generation=NULL,indexed_generation=NULL,index_status='not_required',artifact_root_id=NULL,processing_error=NULL,processing_updated_at=now() WHERE node_id=$1")
        .bind(file).execute(&mut *s.tx).await?;
    sqlx::query("UPDATE nodes SET parent_id=NULL WHERE filesystem_id=$1 AND parent_id=$2")
        .bind(s.fs)
        .bind(file)
        .execute(&mut *s.tx)
        .await?;
    Ok(())
}
pub async fn record_intent(
    s: &mut Session<'_>,
    node: &Node,
    actor: Uuid,
    object_key: Option<&str>,
    inline_sha256: Option<&str>,
) -> Result<Option<Generation>, ApiError> {
    let format = eligible_format(&node.name);
    let identity = processing::content_identity(object_key, inline_sha256)?;
    let publication = if format.is_none() {
        "not_required"
    } else if self::format(&node.name).is_some() {
        "pending"
    } else {
        "parsed"
    };
    let generation=sqlx::query_scalar("UPDATE files SET desired_generation=desired_generation+1,processing_actor_id=$2,processing_format=$3,processing_source_identity=$4,publication_status=$5,index_status=CASE WHEN $5='not_required' THEN 'not_required' ELSE 'pending' END,published_generation=NULL,indexed_generation=NULL,artifact_root_id=NULL,parse_manifest_hash=NULL,publication_manifest_hash=NULL,accepted_attempt=0,accepted_attempt_id=NULL,processing_error=NULL,embedding_model=NULL,vector_collection=NULL,vector_dimension=NULL,processing_updated_at=now() WHERE node_id=$1 RETURNING desired_generation")
        .bind(node.id).bind(actor).bind(format).bind(identity).bind(publication).fetch_one(&mut *s.tx).await?;
    Ok(format.map(|_| Generation {
        file_id: node.id,
        generation,
    }))
}
pub async fn fence_trashed(s: &mut Session<'_>, root: Uuid) -> Result<(), ApiError> {
    let rows=sqlx::query("WITH RECURSIVE tree AS (SELECT id,0 AS depth FROM nodes WHERE id=$1 AND filesystem_id=$2 UNION ALL SELECT n.id,t.depth+1 FROM nodes n JOIN tree t ON n.parent_id=t.id WHERE n.filesystem_id=$2 AND t.depth<128) SELECT f.node_id,f.desired_generation FROM tree t JOIN files f ON f.node_id=t.id WHERE f.desired_generation>0 AND f.publication_status!='not_required'")
        .bind(root).bind(s.fs).fetch_all(&mut *s.tx).await?;
    let ids = rows
        .iter()
        .map(|r| r.get::<Uuid, _>("node_id"))
        .collect::<Vec<_>>();
    super::indexing::enqueue(s, &ids).await?;
    for row in rows {
        processing::fail(
            s,
            Generation {
                file_id: row.get("node_id"),
                generation: row.get("desired_generation"),
            },
            "SOURCE_TRASHED",
        )
        .await?;
    }
    Ok(())
}
pub async fn status(app: &App, fs: Uuid, r: Request) -> Result<Value, ApiError> {
    let mut s = session(app, fs, false).await?;
    let node = s.resolve(&r.scope, &needed(r.input.locator)?).await?;
    status_for(&mut s, node.id)
        .await?
        .ok_or_else(ApiError::not_found)
}
pub async fn status_for(s: &mut Session<'_>, file: Uuid) -> Result<Option<Value>, ApiError> {
    let row=sqlx::query("SELECT f.* FROM files f JOIN nodes n ON n.id=f.node_id WHERE f.node_id=$1 AND n.filesystem_id=$2")
        .bind(file).bind(s.fs).fetch_optional(&mut *s.tx).await?;
    Ok(row.map(|row|json!({"file_id":file,"desired_generation":row.get::<i64,_>("desired_generation").to_string(),
        "published_generation":row.get::<Option<i64>,_>("published_generation").map(|n|n.to_string()),
        "indexed_generation":row.get::<Option<i64>,_>("indexed_generation").map(|n|n.to_string()),
        "artifact_root_id":row.get::<Option<Uuid>,_>("artifact_root_id"),"publication_status":row.get::<&str,_>("publication_status"),
        "index_status":row.get::<&str,_>("index_status"),"error_code":row.get::<Option<String>,_>("processing_error")})))
}
pub async fn reprocess(app: &App, fs: Uuid, r: Request) -> Result<Value, ApiError> {
    let key = needed(r.input.request_key)?;
    if key.is_nil() {
        return Err(ApiError::bad("invalid processing request key"));
    }
    let mut s = session(app, fs, true).await?;
    let node = s.resolve(&r.scope, &needed(r.input.locator)?).await?;
    node.writable()?;
    if node.kind != "file" || eligible_format(&node.name).is_none() {
        return Err(ApiError::state("PROCESSING_UNSUPPORTED"));
    }
    let data = sqlx::query("SELECT object_key,inline_bytes FROM files WHERE node_id=$1 FOR UPDATE")
        .bind(node.id)
        .fetch_one(&mut *s.tx)
        .await?;
    use sha2::{Digest, Sha256};
    let object: Option<String> = data.get("object_key");
    let digest = data
        .get::<Option<Vec<u8>>, _>("inline_bytes")
        .map(|b| format!("{:x}", Sha256::digest(b)));
    let hash = processing::hash(
        &json!({"file_id":node.id,"source":processing::content_identity(object.as_deref(),digest.as_deref())?}),
    )?;
    let scope = format!("filesystem/{fs}/actor/{}", r.scope.actor_id);
    if let Some(prior)=sqlx::query("SELECT request_hash,result FROM idempotency_keys WHERE scope=$1 AND operation='process-file' AND request_key=$2 AND (expires_at IS NULL OR expires_at>now())")
        .bind(&scope).bind(key.to_string()).fetch_optional(&mut *s.tx).await? {
        if prior.get::<String,_>("request_hash")!=hash{return Err(ApiError::state("IDEMPOTENCY_CONFLICT"));}
        return Ok(prior.get("result"));
    }
    invalidate(&mut s, node.id).await?;
    let source = record_intent(
        &mut s,
        &node,
        r.scope.actor_id,
        object.as_deref(),
        digest.as_deref(),
    )
    .await?
    .ok_or_else(|| ApiError::state("PROCESSING_UNSUPPORTED"))?;
    let result = json!({"file_id":source.file_id,"generation":source.generation.to_string(),"workflow_id":source.workflow_id()});
    sqlx::query("INSERT INTO idempotency_keys(scope,operation,request_key,request_hash,result) VALUES($1,'process-file',$2,$3,$4) ON CONFLICT(scope,operation,request_key) DO UPDATE SET request_hash=excluded.request_hash,result=excluded.result,completed_at=NULL,expires_at=NULL WHERE idempotency_keys.expires_at<=now()")
        .bind(scope).bind(key.to_string()).bind(hash).bind(&result).execute(&mut *s.tx).await?;
    s.tx.commit().await?;
    dispatch_pending(app, node.id).await;
    Ok(result)
}

pub async fn discard_forests(app: &App) -> Result<u32, ApiError> {
    // Detached roots are durable cleanup intent; trash has its own lifecycle.
    let roots = sqlx::query("SELECT n.id,n.filesystem_id FROM nodes n JOIN filesystems f ON f.id=n.filesystem_id WHERE n.parent_id IS NULL AND n.id IS DISTINCT FROM f.root_id AND NOT EXISTS(SELECT 1 FROM trash_entries t WHERE t.node_id=n.id) ORDER BY n.filesystem_id,n.id LIMIT 64")
        .fetch_all(&app.pool).await?;
    let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(30);
    let mut count = 0;
    for root in roots {
        if tokio::time::Instant::now() >= deadline {
            break;
        }
        let id: Uuid = root.get("id");
        let mut s = lifecycle_session(app, root.get("filesystem_id")).await?;
        let detached: bool = sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM nodes n WHERE n.id=$1 AND n.filesystem_id=$2 AND n.parent_id IS NULL AND n.id!=$3 AND NOT EXISTS(SELECT 1 FROM trash_entries t WHERE t.node_id=n.id))")
            .bind(id).bind(s.fs).bind(s.root).fetch_one(&mut *s.tx).await?;
        if !detached {
            continue;
        }
        let leaves = super::deletion::leaves(&mut s, id).await?;
        super::deletion::remove(&mut s, &leaves).await?;
        s.tx.commit().await?;
        count += 1;
    }
    Ok(count)
}

#[cfg(test)]
mod tests {
    #[test]
    fn eligible_extensions_are_explicit() {
        for name in ["report.PDF", "word.DoCx", "sheet.xlsx", "slides.pptx"] {
            assert!(super::format(name).is_some());
        }
        for name in [
            "pdf",
            "report.pdf.txt",
            "image.png",
            "legacy.doc",
            "sheet.xls",
            "slides.ppt",
            "note.md",
        ] {
            assert!(super::format(name).is_none());
        }
    }
}
