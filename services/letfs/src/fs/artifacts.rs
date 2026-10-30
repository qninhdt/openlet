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
    let Some(format) = format(&node.name) else {
        return Ok(None);
    };
    let identity = json!({"source_upload_id":upload,"object_key":object_key,"inline_sha256":inline_sha256,"format":format});
    let op = Uuid::now_v7();
    sqlx::query("INSERT INTO operations(id,filesystem_id,actor_id,kind,request_key,fingerprint,source_id) VALUES($1,$2,$3,'process-file',$4,$5,$6)")
        .bind(op).bind(s.fs).bind(actor).bind(upload).bind(identity).bind(node.id)
        .execute(&mut *s.tx).await?;
    Ok(Some(op))
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
    let row = sqlx::query("SELECT id,state,workflow_started_at,error_code FROM operations WHERE filesystem_id=$1 AND source_id=$2 AND kind='process-file' AND superseded_at IS NULL")
        .bind(fs).bind(source.id).fetch_optional(&mut *s.tx).await?.ok_or_else(ApiError::not_found)?;
    let state = match row.get::<&str, _>("state") {
        "running"
            if row
                .get::<Option<chrono::DateTime<chrono::Utc>>, _>("workflow_started_at")
                .is_none() =>
        {
            "pending"
        }
        "running" => "running",
        "succeeded" => "succeeded",
        _ => "failed",
    };
    Ok(
        json!({"operation_id":row.get::<Uuid,_>("id"),"source_id":source.id,"state":state,"error_code":row.get::<Option<String>,_>("error_code")}),
    )
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
