use super::{nodes::*, processing, uploads};
use crate::http::{ApiError, App};
use base64::{Engine, prelude::BASE64_STANDARD};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sqlx::{Row, postgres::PgRow};
use std::collections::{BTreeMap, BTreeSet};
use uuid::Uuid;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Metadata {
    pub title: String,
    pub description: String,
    #[serde(rename = "type")]
    pub semantic_type: String,
    pub context: String,
}
impl Metadata {
    fn validate(&self) -> Result<(), ApiError> {
        for (text, limit) in [
            (&self.title, 200),
            (&self.description, 600),
            (&self.context, 3000),
        ] {
            if text.trim().is_empty() || text.chars().count() > limit || text.contains('\0') {
                return Err(ApiError::bad("invalid semantic metadata"));
            }
        }
        let allowed = "narrative expository instructions reference qa correspondence source_code configuration structured_records logs tabular_text markup opaque_text mixed empty unknown photograph screenshot chart diagram map scanned_document illustration logo icon ui_design handwriting composite other records time_series summary matrix cross_tab key_value lookup financial_ledger schedule inventory questionnaire textbook course_material tutorial reference_manual research_paper thesis research_notes report proposal business_plan specification policy procedure meeting_record contract legal_document regulatory_document invoice receipt financial_statement budget form survey resume letter personal_notes book article presentation dataset part chapter section sheet collection";
        if !allowed.split_whitespace().any(|t| t == self.semantic_type) {
            return Err(ApiError::bad("invalid semantic type"));
        }
        Ok(())
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Update {
    pub id: Uuid,
    pub path: String,
    pub metadata: Metadata,
    pub upload_id: Option<Uuid>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Complete {
    pub nodes: Vec<Update>,
}

pub fn media_type(name: &str) -> &'static str {
    match name
        .rsplit_once('.')
        .map(|(_, e)| e.to_ascii_lowercase())
        .as_deref()
    {
        Some("md" | "markdown") => "text/markdown",
        Some("csv") => "text/csv",
        Some("json") => "application/json",
        Some("png") => "image/png",
        Some("jpg" | "jpeg") => "image/jpeg",
        Some("webp") => "image/webp",
        Some("gif") => "image/gif",
        Some("pdf") => "application/pdf",
        Some("docx") => "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        Some("xlsx") => "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        Some("pptx") => "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        _ => "text/plain",
    }
}

pub async fn validate(s: &mut Session<'_>, op: Uuid) -> Result<PgRow, ApiError> {
    let row = processing::operation(s, op).await?;
    processing::source(s, &row).await?;
    if row.get::<&str, _>("state") != "succeeded" {
        return Err(ApiError::state("PARSE_NOT_COMPLETE"));
    }
    Ok(row)
}

pub async fn inventory(
    s: &mut Session<'_>,
    source: Uuid,
    limit: i64,
) -> Result<Vec<PgRow>, ApiError> {
    let rows = sqlx::query(r#"WITH RECURSIVE tree AS (
        SELECT n.*,''::text COLLATE "C" AS path,0 AS depth FROM nodes n WHERE id=$1 AND filesystem_id=$2
        UNION ALL SELECT n.*,CASE WHEN t.path='' THEN n.name ELSE t.path||'/'||n.name END,t.depth+1
        FROM nodes n JOIN tree t ON n.parent_id=t.id WHERE n.filesystem_id=$2 AND t.depth<128
    ) SELECT t.*,d.storage_kind,d.inline_bytes,d.object_key FROM tree t LEFT JOIN file_data d ON d.node_id=t.id ORDER BY depth,path LIMIT $3"#)
        .bind(source).bind(s.fs).bind(limit+2).fetch_all(&mut *s.tx).await?;
    if rows.len() as i64 > limit + 1 {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    Ok(rows)
}

pub async fn prepare(app: &App, op: Uuid) -> Result<Value, ApiError> {
    let mut s = processing::open(app, op, false).await?;
    let row = validate(&mut s, op).await?;
    let source: Uuid = row.get("source_id");
    if row.get::<&str, _>("enrichment_state") == "succeeded" {
        return Ok(json!({"state":"succeeded","source_id":source}));
    }
    let rows = inventory(&mut s, source, app.config.processing_max_outputs).await?;
    let nodes = inventory_value(app, rows, source).await?;
    sqlx::query("UPDATE operations SET enrichment_state='running',enrichment_error=NULL,updated_at=now() WHERE id=$1")
        .bind(op).execute(&mut *s.tx).await?;
    s.tx.commit().await?;
    Ok(json!({"state":"running","source_id":source,"nodes":nodes,
        "inline_limit_bytes":app.config.inline_limit,"multipart_threshold_bytes":app.config.storage.multipart_threshold_bytes,
        "max_outputs":app.config.processing_max_outputs,"max_output_bytes":app.config.processing_max_output_bytes}))
}

pub async fn inventory_value(
    app: &App,
    rows: Vec<PgRow>,
    source: Uuid,
) -> Result<Vec<Value>, ApiError> {
    let parsed = rows.len() > 1;
    let mut nodes = Vec::new();
    for row in rows {
        let mut node = json!({"id":row.get::<Uuid,_>("id"),"parent_id":row.get::<Option<Uuid>,_>("parent_id"),
            "path":row.get::<String,_>("path"),"name":row.get::<String,_>("name"),"kind":row.get::<String,_>("kind"),
            "size_bytes":row.get::<i64,_>("size_bytes").to_string(),"title":row.get::<Option<String>,_>("title"),"description":row.get::<Option<String>,_>("description"),"context":row.get::<Option<String>,_>("context"),"media_type":if row.get::<&str,_>("kind")=="directory" {None} else {Some(row.get::<Option<String>,_>("media_type").unwrap_or_else(||media_type(row.get("name")).into()))}});
        if row.get::<&str, _>("kind") == "file" && (!parsed || row.get::<Uuid, _>("id") != source) {
            node["content"] = if let Some(key) = row.get::<Option<String>, _>("object_key") {
                json!({"transport":"object","url":crate::storage::download_url(app,&key,"evidence").await?.as_str()})
            } else {
                json!({"transport":"inline","bytes_base64":BASE64_STANDARD.encode(row.get::<Vec<u8>,_>("inline_bytes"))})
            };
        }
        nodes.push(node);
    }
    Ok(nodes)
}

pub async fn prepare_output(
    app: &App,
    op: Uuid,
    output: processing::Output,
) -> Result<Value, ApiError> {
    processing::relative_path(&output.path)?;
    let mut s = processing::open(app, op, false).await?;
    let row = validate(&mut s, op).await?;
    if row.get::<&str, _>("enrichment_state") == "succeeded" {
        return Err(ApiError::state("ENRICHMENT_COMPLETE"));
    }
    let size = uploads::byte_count(&output.size_bytes)?;
    let totals=sqlx::query("SELECT count(*) AS count,coalesce(sum(expected_size),0)::bigint AS bytes FROM uploads WHERE processing_operation_id=$1 AND processing_stage='enrichment' AND state IN ('created','transferring','uploaded')")
        .bind(op).fetch_one(&mut *s.tx).await?;
    // Whole-stage retries may coexist; cap outstanding evidence independently of committed artifacts.
    if totals.get::<i64, _>("count") >= 3 * app.config.processing_max_outputs
        || size > 3 * app.config.processing_max_output_bytes - totals.get::<i64, _>("bytes")
    {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    let input: Input=serde_json::from_value(json!({"storage":output.storage,"size_bytes":output.size_bytes,"content_md5":output.content_md5}))
        .map_err(|_|ApiError::bad("invalid enrichment output"))?;
    let id = uploads::insert(
        &mut s,
        app,
        row.get("actor_id"),
        Uuid::now_v7(),
        json!({"path":output.path}),
        &input,
    )
    .await?;
    sqlx::query("UPDATE uploads SET processing_operation_id=$2,processing_stage='enrichment',relative_path=$3 WHERE id=$1")
        .bind(id).bind(op).bind(output.path).execute(&mut *s.tx).await?;
    let fs = s.fs;
    s.tx.commit().await?;
    uploads::prepare_transfer(app, fs, id, &uploads::Access::Enrichment(op)).await
}

pub async fn complete(app: &App, op: Uuid, input: Complete) -> Result<Value, ApiError> {
    if input.nodes.len() as i64 > app.config.processing_max_outputs + 1 {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    let mut s = processing::open(app, op, false).await?;
    let operation = validate(&mut s, op).await?;
    let source: Uuid = operation.get("source_id");
    if operation.get::<&str, _>("enrichment_state") == "succeeded" {
        return Ok(json!({"state":"succeeded","source_id":source}));
    }
    let rows = inventory(&mut s, source, app.config.processing_max_outputs).await?;
    validate_manifest(&rows, &input.nodes, source)?;
    let updates: BTreeMap<_, _> = input.nodes.iter().map(|n| (n.id, n)).collect();
    let mut selected = BTreeSet::new();
    let mut replacements = BTreeMap::new();
    let mut delta = 0_i64;
    let mut bytes = 0_i64;
    for row in &rows {
        let id: Uuid = row.get("id");
        if let Some(upload) = updates[&id].upload_id {
            if id == source || row.get::<&str, _>("kind") != "file" || !selected.insert(upload) {
                return Err(ApiError::bad("invalid enrichment upload selection"));
            }
            let u=sqlx::query("SELECT * FROM uploads WHERE id=$1 AND processing_operation_id=$2 AND processing_stage='enrichment' AND state='uploaded' FOR UPDATE")
                .bind(upload).bind(op).fetch_optional(&mut *s.tx).await?.ok_or_else(||ApiError::state("OUTPUTS_INCOMPLETE"))?;
            if u.get::<String, _>("relative_path") != updates[&id].path {
                return Err(ApiError::bad("enrichment upload path mismatch"));
            }
            let size: i64 = u.get("expected_size");
            bytes = bytes
                .checked_add(size)
                .ok_or_else(|| ApiError::state("RESOURCE_LIMIT"))?;
            delta = delta
                .checked_add(size - row.get::<i64, _>("size_bytes"))
                .ok_or_else(|| ApiError::state("RESOURCE_LIMIT"))?;
            replacements.insert(id, u);
        }
    }
    if bytes > app.config.processing_max_output_bytes {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    s.usage(delta).await?;
    // Free sibling names together so swaps and overlapping slugs remain atomic.
    sqlx::query("UPDATE nodes SET name='.enrichment-'||id::text WHERE id=ANY($1) AND id!=$2")
        .bind(updates.keys().copied().collect::<Vec<_>>())
        .bind(source)
        .execute(&mut *s.tx)
        .await?;
    for row in &rows {
        let id: Uuid = row.get("id");
        let update = updates[&id];
        let name = if id == source {
            row.get::<String, _>("name")
        } else {
            update.path.rsplit('/').next().unwrap().to_owned()
        };
        let mime = if row.get::<&str, _>("kind") == "directory" {
            None
        } else {
            Some(
                row.get::<Option<String>, _>("media_type")
                    .unwrap_or_else(|| media_type(&name).into()),
            )
        };
        sqlx::query("UPDATE nodes SET name=$2,title=$3,description=$4,semantic_type=$5,context=$6,media_type=$7,revision=revision+1,updated_at=now() WHERE id=$1")
            .bind(id).bind(&name).bind(&update.metadata.title).bind(&update.metadata.description).bind(&update.metadata.semantic_type).bind(&update.metadata.context).bind(mime).execute(&mut *s.tx).await?;
        if let Some(upload) = replacements.get(&id) {
            super::trash::queue_object(&mut s.tx, id, s.bucket).await?;
            sqlx::query("UPDATE file_data SET storage_kind=$2,inline_bytes=$3,object_key=$4 WHERE node_id=$1")
                .bind(id).bind(if upload.get::<&str,_>("transport")=="inline" {"inline"} else {"object"})
                .bind(upload.get::<Option<Vec<u8>>,_>("inline_bytes")).bind(upload.get::<Option<String>,_>("candidate_key")).execute(&mut *s.tx).await?;
            sqlx::query("UPDATE nodes SET size_bytes=$2 WHERE id=$1")
                .bind(id)
                .bind(upload.get::<i64, _>("expected_size"))
                .execute(&mut *s.tx)
                .await?;
            sqlx::query("UPDATE uploads SET state='finalized',result_node_id=$2,result=jsonb_build_object('node_id',$2::uuid,'state','finalized'),inline_bytes=NULL,updated_at=now() WHERE id=$1")
                .bind(upload.get::<Uuid,_>("id")).bind(id).execute(&mut *s.tx).await?;
        }
    }
    processing::discard_uploads(&mut s, op).await?;
    sqlx::query("UPDATE operations SET enrichment_state='succeeded',enrichment_error=NULL,enriched_at=now(),total_bytes=total_bytes+$2,updated_at=now() WHERE id=$1")
        .bind(op).bind(delta).execute(&mut *s.tx).await?;
    s.tx.commit().await?;
    Ok(json!({"state":"succeeded","source_id":source}))
}

fn validate_manifest(rows: &[PgRow], nodes: &[Update], source: Uuid) -> Result<(), ApiError> {
    let updates: BTreeMap<_, _> = nodes.iter().map(|n| (n.id, n)).collect();
    if updates.len() != nodes.len() || rows.len() != nodes.len() {
        return Err(ApiError::bad("incomplete enrichment manifest"));
    }
    let mut paths = BTreeSet::new();
    for row in rows {
        let id: Uuid = row.get("id");
        let update = updates
            .get(&id)
            .ok_or_else(|| ApiError::bad("unknown enrichment node"))?;
        update.metadata.validate()?;
        if !paths.insert(&update.path) {
            return Err(ApiError::bad("duplicate enrichment path"));
        }
        if id == source {
            if !update.path.is_empty() || update.upload_id.is_some() {
                return Err(ApiError::bad("original file is immutable"));
            }
        } else {
            processing::relative_path(&update.path)?;
            let parent: Uuid = row.get("parent_id");
            let parent_path = &updates
                .get(&parent)
                .ok_or_else(|| ApiError::bad("missing enrichment parent"))?
                .path;
            let submitted_parent = update.path.rsplit_once('/').map_or("", |(p, _)| p);
            if submitted_parent != parent_path {
                return Err(ApiError::bad("enrichment cannot reparent nodes"));
            }
            let old_name: &str = row.get("name");
            let new_name = update.path.rsplit('/').next().unwrap();
            let markdown = row.get::<&str, _>("kind") == "file" && old_name.ends_with(".md");
            if markdown != update.upload_id.is_some() {
                return Err(ApiError::bad(
                    "enrichment rewrites exactly the Markdown files",
                ));
            }
            if old_name == "README.md" && update.metadata != updates[&parent].metadata {
                return Err(ApiError::bad("README metadata must represent its parent"));
            }
            if old_name == "README.md" && (new_name != "README.md" || update.upload_id.is_none()) {
                return Err(ApiError::bad("README must be rewritten"));
            }
            if row.get::<&str, _>("kind") == "file"
                && std::path::Path::new(old_name).extension()
                    != std::path::Path::new(new_name).extension()
            {
                return Err(ApiError::bad("enrichment cannot change file type"));
            }
        }
    }
    Ok(())
}

pub async fn fail(app: &App, op: Uuid, code: &str) -> Result<(), ApiError> {
    if !matches!(
        code,
        "PROCESSING_FAILED"
            | "RESOURCE_LIMIT"
            | "QUOTA_EXCEEDED"
            | "DOCUMENT_INVALID"
            | "DEPENDENCY_UNAVAILABLE"
    ) {
        return Err(ApiError::bad("invalid enrichment failure"));
    }
    let mut s = processing::open(app, op, true).await?;
    let row = validate(&mut s, op).await?;
    if row.get::<&str, _>("enrichment_state") != "succeeded" {
        sqlx::query("UPDATE operations SET enrichment_state='failed',enrichment_error=$2,updated_at=now() WHERE id=$1").bind(op).bind(code).execute(&mut *s.tx).await?;
        processing::discard_uploads(&mut s, op).await?;
        s.tx.commit().await?;
    }
    Ok(())
}
