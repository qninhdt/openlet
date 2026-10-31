use super::nodes::{Node, Request, Session, needed, session};
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

pub async fn dispatch_pending(app: &App, source: Uuid) {
    match sqlx::query_scalar::<_,Uuid>("SELECT id FROM operations WHERE source_id=$1 AND kind='process-file' AND superseded_at IS NULL AND index_state!='succeeded'").bind(source).fetch_optional(&app.pool).await {
        Ok(Some(op))=> {if crate::temporal::process_file_workflow::dispatch(app,op).await.is_err(){tracing::warn!("processing dispatch deferred");}},
        Ok(None)=>{},
        Err(_)=>tracing::warn!("processing dispatch lookup deferred"),
    }
}

pub async fn record_inline(
    s: &mut Session<'_>,
    node: &Node,
    actor: Uuid,
    bytes: &[u8],
) -> Result<Option<Uuid>, ApiError> {
    use sha2::{Digest, Sha256};
    let digest = format!("{:x}", Sha256::digest(bytes));
    let upload = Uuid::now_v7();
    let format = if eligible_format(&node.name) == Some("csv") {
        "csv"
    } else {
        "text"
    };
    let media_type = match eligible_format(&node.name) {
        Some("text" | "csv") => super::enrichment::media_type(&node.name),
        _ => "text/plain",
    };
    let identity = json!({"parse_required":false,"media_type":media_type,"source_upload_id":upload,"object_key":null,"inline_sha256":digest,"format":format});
    insert_intent(s, node, actor, upload, identity)
        .await
        .map(Some)
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

pub async fn invalidate(s: &mut Session<'_>, source: Uuid, actor: Uuid) -> Result<(), ApiError> {
    sqlx::query("UPDATE nodes SET title=NULL,description=NULL,semantic_type=NULL,context=NULL,media_type=NULL WHERE id=$1")
        .bind(source).execute(&mut *s.tx).await?;
    // Succeeded publishers must stay succeeded until their charged children are removed.
    sqlx::query("UPDATE operations SET superseded_at=now(),state=CASE WHEN state='running' THEN 'failed' ELSE state END,error_code=CASE WHEN state='running' THEN 'SOURCE_REPLACED' ELSE error_code END,updated_at=now() WHERE filesystem_id=$1 AND source_id=$2 AND kind='process-file' AND superseded_at IS NULL")
        .bind(s.fs).bind(source).execute(&mut *s.tx).await?;
    let cleanup = Uuid::now_v7();
    let inserted: Option<Uuid> = sqlx::query_scalar("INSERT INTO operations(id,filesystem_id,actor_id,kind,request_key,fingerprint) SELECT $1,$2,$3,'discard-artifacts',$1,$4 WHERE EXISTS(SELECT 1 FROM nodes WHERE filesystem_id=$2 AND parent_id=$5) RETURNING id")
        .bind(cleanup).bind(s.fs).bind(actor).bind(json!({"source_id":source})).bind(source)
        .fetch_optional(&mut *s.tx).await?;
    if inserted.is_some() {
        sqlx::query("WITH roots AS (UPDATE nodes SET parent_id=NULL WHERE filesystem_id=$1 AND parent_id=$2 RETURNING id) INSERT INTO deletion_items(operation_id,node_id,depth) SELECT $3,id,0 FROM roots")
            .bind(s.fs).bind(source).bind(cleanup).execute(&mut *s.tx).await?;
    }
    Ok(())
}

pub async fn record_intent(
    s: &mut Session<'_>,
    node: &Node,
    actor: Uuid,
    upload: Uuid,
    object_key: Option<&str>,
    inline_sha256: Option<&str>,
) -> Result<Option<Uuid>, ApiError> {
    let Some(format) = eligible_format(&node.name) else {
        return Ok(None);
    };
    let parse_required = self::format(&node.name).is_some();
    let identity = json!({"parse_required":parse_required,"media_type":super::enrichment::media_type(&node.name),"source_upload_id":upload,"object_key":object_key,"inline_sha256":inline_sha256,"format":format});
    insert_intent(s, node, actor, upload, identity)
        .await
        .map(Some)
}

async fn insert_intent(
    s: &mut Session<'_>,
    node: &Node,
    actor: Uuid,
    upload: Uuid,
    identity: Value,
) -> Result<Uuid, ApiError> {
    let parse_required = identity["parse_required"].as_bool().unwrap_or(true);
    sqlx::query("UPDATE nodes SET media_type=$2 WHERE id=$1")
        .bind(node.id)
        .bind(identity["media_type"].as_str())
        .execute(&mut *s.tx)
        .await?;
    let op = Uuid::now_v7();
    sqlx::query("INSERT INTO operations(id,filesystem_id,actor_id,kind,request_key,fingerprint,source_id) VALUES($1,$2,$3,'process-file',$4,$5,$6)")
        .bind(op).bind(s.fs).bind(actor).bind(upload).bind(identity).bind(node.id)
        .execute(&mut *s.tx).await?;
    if !parse_required {
        sqlx::query("UPDATE operations SET state='succeeded',result_node_id=$2 WHERE id=$1")
            .bind(op)
            .bind(node.id)
            .execute(&mut *s.tx)
            .await?;
    }
    Ok(op)
}

pub async fn fence_trashed(s: &mut Session<'_>, root: Uuid) -> Result<(), ApiError> {
    sqlx::query(r#"WITH RECURSIVE ancestors(op,id,parent_id,depth) AS (
        SELECT o.id,n.id,n.parent_id,0 FROM operations o JOIN nodes n ON n.id=o.source_id AND n.filesystem_id=o.filesystem_id
        WHERE o.filesystem_id=$1 AND o.kind='process-file' AND o.state='running' AND o.superseded_at IS NULL
        UNION ALL SELECT a.op,n.id,n.parent_id,a.depth+1 FROM ancestors a
        JOIN nodes n ON n.id=a.parent_id AND n.filesystem_id=$1 WHERE a.depth<128
    ) UPDATE operations SET state='failed',error_code='SOURCE_TRASHED',updated_at=now()
      WHERE id IN (SELECT op FROM ancestors WHERE id=$2)"#)
        .bind(s.fs).bind(root).execute(&mut *s.tx).await?;
    Ok(())
}

pub async fn status(app: &App, fs: Uuid, r: Request) -> Result<Value, ApiError> {
    let mut s = session(app, fs, false).await?;
    let source = s.resolve(&r.scope, &needed(r.input.locator)?).await?;
    status_for(&mut s, source.id)
        .await?
        .ok_or_else(ApiError::not_found)
}

pub async fn status_for(s: &mut Session<'_>, source: Uuid) -> Result<Option<Value>, ApiError> {
    let row=sqlx::query("SELECT * FROM operations WHERE filesystem_id=$1 AND source_id=$2 AND kind='process-file' AND superseded_at IS NULL")
        .bind(s.fs).bind(source).fetch_optional(&mut *s.tx).await?;
    Ok(row.map(|row| {
        let parse = match row.get::<&str,_>("state") {
            "running" if row.get::<Option<chrono::DateTime<chrono::Utc>>,_>("workflow_started_at").is_none()=>"pending",
            "running"=>"running", "succeeded"=>"succeeded", _=>"failed",
        };
        let stage=|state:&str,error:Option<String>,retryable:bool|json!({"state":state,"error_code":error,"retryable":retryable});
        let en:&str=row.get("enrichment_state");let index:&str=row.get("index_state");
        json!({"operation_id":row.get::<Uuid,_>("id"),"source_id":source,"stages":{
            "parse":stage(parse,row.get("error_code"),false),
            "enrichment":stage(en,row.get("enrichment_error"),parse=="succeeded" && en=="failed"),
            "index":stage(index,row.get("index_error"),en=="succeeded" && index=="failed")}})
    }))
}

pub async fn retry(
    app: &App,
    fs: Uuid,
    r: Request,
) -> Result<(axum::http::StatusCode, Value), ApiError> {
    let stage = needed(r.input.stage.as_deref())?;
    if !matches!(stage, "enrichment" | "index") {
        return Err(ApiError::bad("invalid retry stage"));
    }
    let mut s = session(app, fs, true).await?;
    let source = s.resolve(&r.scope, &needed(r.input.locator)?).await?;
    source.writable()?;
    let row=sqlx::query("SELECT * FROM operations WHERE filesystem_id=$1 AND source_id=$2 AND kind='process-file' AND superseded_at IS NULL FOR UPDATE")
        .bind(fs).bind(source.id).fetch_optional(&mut *s.tx).await?.ok_or_else(ApiError::not_found)?;
    if row.get::<&str, _>("state") != "succeeded"
        || (stage == "index" && row.get::<&str, _>("enrichment_state") != "succeeded")
    {
        return Err(ApiError::state("PREVIOUS_STAGE_NOT_COMPLETE"));
    }
    let state: &str = row.get(if stage == "index" {
        "index_state"
    } else {
        "enrichment_state"
    });
    let op: Uuid = row.get("id");
    let code = if state == "succeeded" {
        axum::http::StatusCode::OK
    } else {
        axum::http::StatusCode::ACCEPTED
    };
    if state == "failed" {
        sqlx::query(if stage=="index" {"UPDATE operations SET index_state='pending',index_error=NULL,updated_at=now() WHERE id=$1"} else {"UPDATE operations SET enrichment_state='pending',enrichment_error=NULL,updated_at=now() WHERE id=$1"}).bind(op).execute(&mut *s.tx).await?;
    }
    let result = status_for(&mut s, source.id)
        .await?
        .ok_or_else(ApiError::not_found)?;
    s.tx.commit().await?;
    if state != "succeeded" {
        crate::temporal::process_file_workflow::dispatch(app, op).await?;
    }
    Ok((code, result))
}

pub async fn discard_forests(app: &App) -> Result<u32, ApiError> {
    let operations: Vec<Uuid> = sqlx::query_scalar("SELECT id FROM operations WHERE kind='discard-artifacts' AND state='running' ORDER BY updated_at,id LIMIT 64")
        .fetch_all(&app.pool).await?;
    for op in &operations {
        super::deletion::batch(app, *op).await?;
    }
    Ok(operations.len() as u32)
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
