use super::{
    nodes::*,
    processing::{self, Attempt, Generation},
    uploads,
};
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
        let valid = self
            .semantic_type
            .split_once(':')
            .is_some_and(|(family, kind)| {
                let allowed = match family {
                    "document" => "research_paper report article book manual contract other",
                    "text" => "content summary notes overview transcript other",
                    "image" => "photo screenshot chart diagram illustration other",
                    "table" => "records summary time_series other",
                    "spreadsheet" => "dataset financial tracker other",
                    "presentation" => "lecture pitch report other",
                    "code" => "source configuration notebook other",
                    "other" => "unknown",
                    _ => "",
                };
                allowed.split_whitespace().any(|value| value == kind)
            });
        if !valid {
            return Err(ApiError::bad("invalid semantic type"));
        }
        Ok(())
    }
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Update {
    pub id: Uuid,
    pub path: String,
    pub metadata: Option<Metadata>,
    pub upload_id: Option<Uuid>,
}
#[derive(Deserialize, Serialize)]
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

pub async fn validate(s: &mut Session<'_>, source: Generation) -> Result<PgRow, ApiError> {
    let row = processing::current(s, source).await?;
    processing::source(s, &row).await?;
    if !matches!(row.get::<&str, _>("publication_status"), "parsed" | "ready") {
        return Err(ApiError::state("PARSE_NOT_COMPLETE"));
    }
    Ok(row)
}
pub async fn validate_attempt(s: &mut Session<'_>, attempt: &Attempt) -> Result<PgRow, ApiError> {
    let row = validate(s, attempt.source).await?;
    if row.get::<&str, _>("publication_status") != "ready" {
        processing::check_attempt(&row, attempt)?;
    }
    Ok(row)
}

pub async fn inventory(
    s: &mut Session<'_>,
    source: Uuid,
    limit: i64,
) -> Result<Vec<PgRow>, ApiError> {
    let rows = sqlx::query(r#"WITH RECURSIVE tree AS (
        SELECT n.*,''::text COLLATE "C" AS path,0 AS depth FROM nodes n WHERE id=coalesce((SELECT artifact_root_id FROM files WHERE node_id=$1),$1) AND filesystem_id=$2
        UNION ALL SELECT n.*,CASE WHEN t.path='' THEN n.name ELSE t.path||'/'||n.name END,t.depth+1
        FROM nodes n JOIN tree t ON n.parent_id=t.id WHERE n.filesystem_id=$2 AND t.depth<128
    ) SELECT t.*,d.storage_kind,d.inline_bytes,d.object_key,d.media_type,d.title,d.description,d.semantic_type,d.context FROM tree t LEFT JOIN files d ON d.node_id=t.id ORDER BY depth,path LIMIT $3"#)
        .bind(source).bind(s.fs).bind(limit+2).fetch_all(&mut *s.tx).await?;
    if rows.len() as i64 > limit + 1 {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    Ok(rows)
}

pub async fn prepare(app: &App, attempt: &Attempt) -> Result<Value, ApiError> {
    let mut s = processing::open(app, attempt.source, false).await?;
    let row = validate(&mut s, attempt.source).await?;
    if row.get::<&str, _>("publication_status") == "ready" {
        return Ok(json!({"state":"succeeded","source_id":attempt.source.file_id}));
    }
    processing::accept(&mut s, &row, attempt, "enrichment").await?;
    let rows = inventory(
        &mut s,
        attempt.source.file_id,
        app.config.processing_max_outputs,
    )
    .await?;
    let nodes = inventory_value(app, rows, attempt.source.file_id).await?;
    s.tx.commit().await?;
    Ok(
        json!({"state":"running","source_id":attempt.source.file_id,"nodes":nodes,"inline_limit_bytes":app.config.inline_limit,"multipart_threshold_bytes":app.config.storage.multipart_threshold_bytes,"max_output_bytes":app.config.processing_max_output_bytes}),
    )
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
                json!({"transport":"object","url":crate::storage::processor_download_url(app,&key,"evidence").await?.as_str()})
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
    attempt: &Attempt,
    output: processing::Output,
) -> Result<Value, ApiError> {
    let mut s = processing::open(app, attempt.source, false).await?;
    let row = validate_attempt(&mut s, attempt).await?;
    if row.get::<&str, _>("publication_status") == "ready" {
        return Err(ApiError::state("ENRICHMENT_COMPLETE"));
    }
    let id = processing::insert_output(
        &mut s,
        app,
        attempt,
        "enrichment",
        &output,
        row.get("processing_actor_id"),
    )
    .await?;
    let fs = s.fs;
    s.tx.commit().await?;
    uploads::prepare_transfer(app, fs, id, &uploads::Access::Enrichment(attempt.clone())).await
}

pub async fn complete(
    app: &App,
    attempt: &Attempt,
    mut input: Complete,
) -> Result<Value, ApiError> {
    if input.nodes.len() as i64 > app.config.processing_max_outputs + 1 {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    let mut s = processing::open(app, attempt.source, false).await?;
    let current = validate(&mut s, attempt.source).await?;
    let source = attempt.source.file_id;
    input.nodes.sort_by_key(|n| n.id);
    let manifest = processing::hash(&input)?;
    if current.get::<&str, _>("publication_status") == "ready" {
        if current
            .get::<Option<String>, _>("publication_manifest_hash")
            .as_deref()
            != Some(&manifest)
        {
            return Err(ApiError::state("IDEMPOTENCY_CONFLICT"));
        }
        return Ok(json!({"state":"succeeded","source_id":source}));
    }
    processing::check_attempt(&current, attempt)?;
    let rows = inventory(&mut s, source, app.config.processing_max_outputs).await?;
    let root = current
        .get::<Option<Uuid>, _>("artifact_root_id")
        .unwrap_or(source);
    validate_manifest(&rows, &input.nodes, root)?;
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
            let u=sqlx::query("SELECT * FROM uploads WHERE id=$1 AND processing_file_id=$2 AND processing_generation=$3 AND processing_attempt=$4 AND processing_attempt_id=$5 AND processing_stage='enrichment' AND state='finalized' AND result_node_id IS NULL FOR UPDATE")
                .bind(upload).bind(source).bind(attempt.source.generation).bind(attempt.number).bind(attempt.attempt_id).fetch_optional(&mut *s.tx).await?.ok_or_else(||ApiError::state("OUTPUTS_INCOMPLETE"))?;
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
        .bind(root)
        .execute(&mut *s.tx)
        .await?;
    for row in &rows {
        let id: Uuid = row.get("id");
        let update = updates[&id];
        let name = if id == root {
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
        sqlx::query("UPDATE nodes SET name=$2,revision=revision+1,updated_at=now() WHERE id=$1")
            .bind(id)
            .bind(&name)
            .execute(&mut *s.tx)
            .await?;
        if row.get::<&str, _>("kind") == "file" {
            let metadata = update
                .metadata
                .as_ref()
                .ok_or_else(|| ApiError::bad("file metadata required"))?;
            sqlx::query("UPDATE files SET title=$2,description=$3,semantic_type=$4,context=$5,media_type=$6 WHERE node_id=$1")
                .bind(id).bind(&metadata.title).bind(&metadata.description).bind(&metadata.semantic_type).bind(&metadata.context).bind(mime).execute(&mut *s.tx).await?;
        }
        if let Some(upload) = replacements.get(&id) {
            super::trash::queue_object(&mut s.tx, id, s.bucket).await?;
            sqlx::query(
                "UPDATE files SET storage_kind=$2,inline_bytes=$3,object_key=$4 WHERE node_id=$1",
            )
            .bind(id)
            .bind(if upload.get::<&str, _>("transport") == "inline" {
                "inline"
            } else {
                "object"
            })
            .bind(upload.get::<Option<Vec<u8>>, _>("inline_bytes"))
            .bind(upload.get::<Option<String>, _>("candidate_key"))
            .execute(&mut *s.tx)
            .await?;
            sqlx::query("UPDATE nodes SET size_bytes=$2 WHERE id=$1")
                .bind(id)
                .bind(upload.get::<i64, _>("expected_size"))
                .execute(&mut *s.tx)
                .await?;
            sqlx::query("UPDATE uploads SET result_node_id=$2,inline_bytes=NULL,updated_at=now() WHERE id=$1")
                .bind(upload.get::<Uuid,_>("id")).bind(id).execute(&mut *s.tx).await?;
        }
    }
    if root != source {
        let readme = rows
            .iter()
            .find(|r| {
                r.get::<Option<Uuid>, _>("parent_id") == Some(root)
                    && r.get::<&str, _>("name") == "README.md"
                    && r.get::<&str, _>("kind") == "file"
            })
            .ok_or_else(|| ApiError::state("OUTPUTS_INCOMPLETE"))?;
        let metadata = updates[&readme.get::<Uuid, _>("id")]
            .metadata
            .as_ref()
            .ok_or_else(|| ApiError::bad("README metadata required"))?;
        sqlx::query(
            "UPDATE files SET title=$2,description=$3,semantic_type=$4,context=$5 WHERE node_id=$1",
        )
        .bind(source)
        .bind(&metadata.title)
        .bind(&metadata.description)
        .bind(&metadata.semantic_type)
        .bind(&metadata.context)
        .execute(&mut *s.tx)
        .await?;
    }
    processing::discard_uploads(&mut s, attempt.source, None).await?;
    sqlx::query("UPDATE files SET publication_status='ready',published_generation=desired_generation,publication_manifest_hash=$2,processing_error=NULL,processing_updated_at=now() WHERE node_id=$1")
        .bind(source).bind(manifest).execute(&mut *s.tx).await?;
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
        if row.get::<&str, _>("kind") == "directory" {
            if update.metadata.is_some() {
                return Err(ApiError::bad("directory cannot own semantic metadata"));
            }
        } else {
            update
                .metadata
                .as_ref()
                .ok_or_else(|| ApiError::bad("file metadata required"))?
                .validate()?;
        }
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

pub async fn fail(app: &App, attempt: &Attempt, code: &str) -> Result<(), ApiError> {
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
    let mut s = processing::open(app, attempt.source, true).await?;
    let row = validate_attempt(&mut s, attempt).await?;
    if row.get::<&str, _>("publication_status") != "ready" {
        processing::fail(&mut s, attempt.source, code).await?;
        s.tx.commit().await?;
    }
    Ok(())
}
