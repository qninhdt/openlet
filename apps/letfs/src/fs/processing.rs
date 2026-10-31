use super::{nodes::*, paths, uploads};
use crate::http::{ApiError, App};
use base64::{Engine, prelude::BASE64_STANDARD};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{Row, postgres::PgRow};
use std::collections::{BTreeMap, BTreeSet};
use uuid::Uuid;

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Generation {
    pub file_id: Uuid,
    pub generation: i64,
}
impl Generation {
    pub fn workflow_id(self) -> String {
        format!("process-file/{}/{}", self.file_id, self.generation)
    }
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Attempt {
    pub source: Generation,
    pub number: i32,
    pub attempt_id: Uuid,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Output {
    pub path: String,
    pub storage: uploads::StorageMode,
    pub size_bytes: String,
    pub content_md5: Option<String>,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Complete {
    pub uploads: Vec<Uuid>,
    pub directories: Vec<String>,
}
pub fn hash(value: &impl Serialize) -> Result<String, ApiError> {
    Ok(format!(
        "{:x}",
        Sha256::digest(
            serde_json::to_vec(value).map_err(|_| ApiError::bad("invalid publication manifest"))?
        )
    ))
}
pub fn content_identity(key: Option<&str>, digest: Option<&str>) -> Result<String, ApiError> {
    match (key, digest) {
        (Some(key), None) => Ok(format!("object:{key}")),
        (None, Some(digest)) => Ok(format!("inline:{digest}")),
        _ => Err(ApiError::state("INVALID_SOURCE_IDENTITY")),
    }
}
pub async fn open(app: &App, source: Generation, lifecycle: bool) -> Result<Session<'_>, ApiError> {
    let fs: Uuid = sqlx::query_scalar("SELECT filesystem_id FROM nodes WHERE id=$1")
        .bind(source.file_id)
        .fetch_optional(&app.pool)
        .await?
        .ok_or_else(ApiError::not_found)?;
    if lifecycle {
        lifecycle_session(app, fs).await
    } else {
        session(app, fs, true).await
    }
}
pub async fn current(s: &mut Session<'_>, source: Generation) -> Result<PgRow, ApiError> {
    let row = sqlx::query("SELECT f.* FROM files f JOIN nodes n ON n.id=f.node_id WHERE f.node_id=$1 AND n.filesystem_id=$2 FOR UPDATE OF f")
        .bind(source.file_id).bind(s.fs).fetch_optional(&mut *s.tx).await?.ok_or_else(ApiError::not_found)?;
    if row.get::<i64, _>("desired_generation") != source.generation {
        return Err(ApiError::state("SOURCE_REPLACED"));
    }
    if matches!(
        row.get::<&str, _>("publication_status"),
        "failed" | "not_required"
    ) {
        return Err(ApiError::state("PROCESSING_NOT_ACTIVE"));
    }
    Ok(row)
}
pub async fn source(s: &mut Session<'_>, row: &PgRow) -> Result<Node, ApiError> {
    let scope = paths::Scope {
        actor_id: row.get("processing_actor_id"),
        mounts: vec![paths::Mount {
            path: "/".into(),
            filesystem_id: s.fs,
        }],
    };
    let locator = paths::Locator {
        node_id: Some(row.get("node_id")),
        path: None,
        cwd_id: None,
        expected_node_id: None,
        expected_parent_id: None,
    };
    let node = s.resolve(&scope, &locator).await?;
    node.writable()?;
    let key = row.get::<Option<String>, _>("object_key");
    let digest = row
        .get::<Option<Vec<u8>>, _>("inline_bytes")
        .map(|bytes| format!("{:x}", Sha256::digest(bytes)));
    if content_identity(key.as_deref(), digest.as_deref())?
        != row.get::<String, _>("processing_source_identity")
    {
        return Err(ApiError::state("SOURCE_REPLACED"));
    }
    Ok(node)
}
pub async fn validate(s: &mut Session<'_>, attempt: &Attempt) -> Result<PgRow, ApiError> {
    let row = current(s, attempt.source).await?;
    source(s, &row).await?;
    if row.get::<&str, _>("publication_status") == "pending" {
        check_attempt(&row, attempt)?;
    }
    Ok(row)
}
pub fn check_attempt(row: &PgRow, attempt: &Attempt) -> Result<(), ApiError> {
    if row.get::<i32, _>("accepted_attempt") != attempt.number
        || row.get::<Option<Uuid>, _>("accepted_attempt_id") != Some(attempt.attempt_id)
    {
        return Err(ApiError::state("STALE_PROCESSING_ATTEMPT"));
    }
    Ok(())
}
pub async fn accept(
    s: &mut Session<'_>,
    row: &PgRow,
    attempt: &Attempt,
    stage: &str,
) -> Result<(), ApiError> {
    if !(1..=3).contains(&attempt.number) || attempt.attempt_id.is_nil() {
        return Err(ApiError::bad("invalid processing attempt"));
    }
    let prior = row.get::<i32, _>("accepted_attempt");
    if prior > attempt.number
        || (prior == attempt.number
            && row.get::<Option<Uuid>, _>("accepted_attempt_id") != Some(attempt.attempt_id))
    {
        return Err(ApiError::state("STALE_PROCESSING_ATTEMPT"));
    }
    if prior < attempt.number {
        discard_uploads(s, attempt.source, Some(stage)).await?;
        sqlx::query("UPDATE files SET accepted_attempt=$2,accepted_attempt_id=$3,processing_updated_at=now() WHERE node_id=$1")
            .bind(attempt.source.file_id).bind(attempt.number).bind(attempt.attempt_id).execute(&mut *s.tx).await?;
    }
    Ok(())
}
pub async fn discard_uploads(
    s: &mut Session<'_>,
    source: Generation,
    stage: Option<&str>,
) -> Result<(), ApiError> {
    sqlx::query("INSERT INTO object_deletions(object_key,bucket_id,ambiguous_write,eligible_at) SELECT candidate_key,bucket_id,write_expires_at IS NOT NULL,greatest(now()+interval '15 minutes',transfer_deadline) FROM uploads WHERE processing_file_id=$1 AND processing_generation=$2 AND ($3::text IS NULL OR processing_stage=$3) AND result_node_id IS NULL AND candidate_key IS NOT NULL ON CONFLICT(object_key) DO UPDATE SET state='pending',ambiguous_write=object_deletions.ambiguous_write OR excluded.ambiguous_write,eligible_at=greatest(object_deletions.eligible_at,excluded.eligible_at)")
        .bind(source.file_id).bind(source.generation).bind(stage).execute(&mut *s.tx).await?;
    sqlx::query("UPDATE uploads SET state=CASE WHEN state IN ('open','completing') THEN 'aborted' ELSE state END,inline_bytes=NULL,updated_at=now() WHERE processing_file_id=$1 AND processing_generation=$2 AND ($3::text IS NULL OR processing_stage=$3) AND result_node_id IS NULL")
        .bind(source.file_id).bind(source.generation).bind(stage).execute(&mut *s.tx).await?;
    Ok(())
}
pub async fn prepare(app: &App, attempt: &Attempt) -> Result<Value, ApiError> {
    let mut s = open(app, attempt.source, false).await?;
    let row = current(&mut s, attempt.source).await?;
    let node = source(&mut s, &row).await?;
    if row.get::<&str, _>("publication_status") != "pending" {
        return Ok(json!({"state":"succeeded","source_id":node.id}));
    }
    accept(&mut s, &row, attempt, "parse").await?;
    let mut value = json!({"state":"running","source_id":node.id,"format":row.get::<String,_>("processing_format"),"size_bytes":node.size_bytes,
        "inline_limit_bytes":app.config.inline_limit,"multipart_threshold_bytes":app.config.storage.multipart_threshold_bytes,"max_outputs":app.config.processing_max_outputs,"max_output_bytes":app.config.processing_max_output_bytes});
    if let Some(key) = row.get::<Option<String>, _>("object_key") {
        value["source"] = json!({"transport":"object","url":crate::storage::processor_download_url(app,&key,"source").await?.as_str()});
    } else {
        value["source"] = json!({"transport":"inline","bytes_base64":BASE64_STANDARD.encode(row.get::<Vec<u8>,_>("inline_bytes"))});
    }
    s.tx.commit().await?;
    Ok(value)
}
pub async fn prepare_output(
    app: &App,
    attempt: &Attempt,
    output: Output,
) -> Result<Value, ApiError> {
    let mut s = open(app, attempt.source, false).await?;
    let row = validate(&mut s, attempt).await?;
    if row.get::<&str, _>("publication_status") != "pending" {
        return Err(ApiError::state("PROCESSING_NOT_ACTIVE"));
    }
    let id = insert_output(
        &mut s,
        app,
        attempt,
        "parse",
        &output,
        row.get("processing_actor_id"),
    )
    .await?;
    let fs = s.fs;
    s.tx.commit().await?;
    uploads::prepare_transfer(app, fs, id, &uploads::Access::Processor(attempt.clone())).await
}
pub async fn insert_output(
    s: &mut Session<'_>,
    app: &App,
    attempt: &Attempt,
    stage: &str,
    output: &Output,
    actor: Uuid,
) -> Result<Uuid, ApiError> {
    relative_path(&output.path)?;
    let fingerprint = json!({"path":output.path,"storage":output.storage,"size_bytes":output.size_bytes,"content_md5":output.content_md5});
    if let Some(old)=sqlx::query("SELECT id,input FROM uploads WHERE processing_file_id=$1 AND processing_generation=$2 AND processing_attempt=$3 AND processing_stage=$4 AND relative_path=$5")
        .bind(attempt.source.file_id).bind(attempt.source.generation).bind(attempt.number).bind(stage).bind(&output.path).fetch_optional(&mut *s.tx).await? {
        if old.get::<Value,_>("input")!=fingerprint { return Err(ApiError::state("IDEMPOTENCY_CONFLICT")); }
        return Ok(old.get("id"));
    }
    let totals=sqlx::query("SELECT count(*) AS count,coalesce(sum(expected_size),0)::bigint AS bytes FROM uploads WHERE processing_file_id=$1 AND processing_generation=$2 AND processing_attempt=$3 AND processing_stage=$4")
        .bind(attempt.source.file_id).bind(attempt.source.generation).bind(attempt.number).bind(stage).fetch_one(&mut *s.tx).await?;
    let size = uploads::byte_count(&output.size_bytes)?;
    if totals.get::<i64, _>("count") >= app.config.processing_max_outputs
        || size > app.config.processing_max_output_bytes - totals.get::<i64, _>("bytes")
    {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    let input:Input=serde_json::from_value(json!({"storage":output.storage,"size_bytes":output.size_bytes,"content_md5":output.content_md5})).map_err(|_|ApiError::bad("invalid output metadata"))?;
    let id = uploads::insert(s, app, actor, fingerprint, &input).await?;
    sqlx::query("UPDATE uploads SET processing_file_id=$2,processing_generation=$3,processing_attempt=$4,processing_attempt_id=$5,relative_path=$6,processing_stage=$7 WHERE id=$1")
        .bind(id).bind(attempt.source.file_id).bind(attempt.source.generation).bind(attempt.number).bind(attempt.attempt_id).bind(&output.path).bind(stage).execute(&mut *s.tx).await?;
    Ok(id)
}
pub async fn complete(
    app: &App,
    attempt: &Attempt,
    mut input: Complete,
) -> Result<Value, ApiError> {
    if input.uploads.len() as i64 > app.config.processing_max_outputs
        || input.directories.len() as i64 > app.config.processing_max_outputs
    {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    input.uploads.sort();
    input.directories.sort();
    let manifest = hash(&input)?;
    let mut s = open(app, attempt.source, false).await?;
    let row = current(&mut s, attempt.source).await?;
    source(&mut s, &row).await?;
    if row.get::<&str, _>("publication_status") != "pending" {
        if row
            .get::<Option<String>, _>("parse_manifest_hash")
            .as_deref()
            != Some(&manifest)
        {
            return Err(ApiError::state("IDEMPOTENCY_CONFLICT"));
        }
        return Ok(json!({"state":"succeeded","source_id":attempt.source.file_id}));
    }
    check_attempt(&row, attempt)?;
    let rows=sqlx::query("SELECT * FROM uploads WHERE processing_file_id=$1 AND processing_generation=$2 AND processing_attempt=$3 AND processing_attempt_id=$4 AND processing_stage='parse' ORDER BY relative_path FOR UPDATE")
        .bind(attempt.source.file_id).bind(attempt.source.generation).bind(attempt.number).bind(attempt.attempt_id).fetch_all(&mut *s.tx).await?;
    let ids: BTreeSet<Uuid> = input.uploads.iter().copied().collect();
    if ids.len() != input.uploads.len()
        || ids.len() != rows.len()
        || rows.iter().any(|r| {
            !ids.contains(&r.get("id"))
                || r.get::<&str, _>("state") != "finalized"
                || r.get::<Option<Uuid>, _>("result_node_id").is_some()
        })
    {
        return Err(ApiError::state("OUTPUTS_INCOMPLETE"));
    }
    let files = rows
        .iter()
        .map(|r| (r.get::<String, _>("relative_path"), r.get::<Uuid, _>("id")))
        .collect::<Vec<_>>();
    let tree = output_tree(
        &files,
        &input.directories,
        app.config.processing_max_outputs as usize,
    )?;
    let source = attempt.source.file_id;
    let source_depth = depth(&mut s.tx, s.fs, source).await? as usize;
    if tree
        .keys()
        .any(|p| source_depth + 1 + p.split('/').count() > 128)
    {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    let bytes = rows
        .iter()
        .try_fold(0_i64, |n, r| {
            n.checked_add(r.get::<i64, _>("expected_size"))
        })
        .ok_or_else(|| ApiError::state("RESOURCE_LIMIT"))?;
    if bytes > app.config.processing_max_output_bytes {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    if super::artifacts::has_children(&mut s, source).await? {
        return Err(ApiError::state("PROCESSING_ALREADY_PUBLISHED"));
    }
    s.usage(bytes).await?;
    s.add_nodes(tree.len() as i64 + 1).await?;
    let root = Uuid::now_v7();
    sqlx::query("INSERT INTO nodes(id,filesystem_id,parent_id,name,kind) VALUES($1,$2,$3,'artifacts','directory')").bind(root).bind(s.fs).bind(source).execute(&mut *s.tx).await?;
    let node_ids = tree
        .keys()
        .map(|path| (path.clone(), Uuid::now_v7()))
        .collect::<BTreeMap<_, _>>();
    let entries=tree.iter().map(|(path,upload)|{
        let (parent,name)=path.rsplit_once('/').map_or((root,path.as_str()),|(p,n)|(node_ids[p],n));
        json!({"id":node_ids[path],"parent":parent,"name":name,"upload":upload,"media_type":super::enrichment::media_type(name)})
    }).collect::<Vec<_>>();
    sqlx::query("WITH entries AS (SELECT * FROM jsonb_to_recordset($2) AS x(id uuid,parent uuid,name text,upload uuid)) INSERT INTO nodes(id,filesystem_id,parent_id,name,kind,size_bytes) SELECT e.id,$1,e.parent,e.name,CASE WHEN e.upload IS NULL THEN 'directory' ELSE 'file' END,coalesce(u.expected_size,0) FROM entries e LEFT JOIN uploads u ON u.id=e.upload")
        .bind(s.fs).bind(json!(entries)).execute(&mut *s.tx).await?;
    sqlx::query("WITH entries AS (SELECT * FROM jsonb_to_recordset($1) AS x(id uuid,parent uuid,name text,upload uuid,media_type text)) INSERT INTO files(node_id,storage_kind,inline_bytes,object_key,media_type) SELECT e.id,CASE WHEN u.transport='inline' THEN 'inline' ELSE 'object' END,u.inline_bytes,u.candidate_key,e.media_type FROM entries e JOIN uploads u ON u.id=e.upload")
        .bind(json!(entries)).execute(&mut *s.tx).await?;
    sqlx::query("UPDATE uploads u SET result_node_id=e.id,inline_bytes=NULL,updated_at=now() FROM jsonb_to_recordset($1) AS e(id uuid,parent uuid,name text,upload uuid) WHERE u.id=e.upload")
        .bind(json!(entries)).execute(&mut *s.tx).await?;
    sqlx::query("UPDATE files SET publication_status='parsed',artifact_root_id=$2,parse_manifest_hash=$3,accepted_attempt=0,accepted_attempt_id=NULL,processing_updated_at=now() WHERE node_id=$1")
        .bind(source).bind(root).bind(manifest).execute(&mut *s.tx).await?;
    s.tx.commit().await?;
    Ok(json!({"state":"succeeded","source_id":source}))
}
pub async fn abort(app: &App, attempt: &Attempt, code: &str) -> Result<(), ApiError> {
    if !matches!(
        code,
        "PROCESSING_FAILED"
            | "PROCESSING_CANCELLED"
            | "DOCUMENT_INVALID"
            | "RESOURCE_LIMIT"
            | "QUOTA_EXCEEDED"
    ) {
        return Err(ApiError::bad("invalid processing failure code"));
    }
    let mut s = open(app, attempt.source, true).await?;
    let row = validate(&mut s, attempt).await?;
    if row.get::<&str, _>("publication_status") != "pending" {
        return Ok(());
    }
    fail(&mut s, attempt.source, code).await?;
    s.tx.commit().await?;
    Ok(())
}
pub async fn complete_receipt(s: &mut Session<'_>, source: Generation) -> Result<(), ApiError> {
    sqlx::query("UPDATE idempotency_keys SET completed_at=now(),expires_at=now()+interval '24 hours' WHERE operation='process-file' AND result->>'file_id'=$1 AND result->>'generation'=$2 AND completed_at IS NULL")
        .bind(source.file_id.to_string()).bind(source.generation.to_string()).execute(&mut *s.tx).await?;
    Ok(())
}
pub async fn fail(s: &mut Session<'_>, source: Generation, code: &str) -> Result<(), ApiError> {
    discard_uploads(s, source, None).await?;
    sqlx::query("UPDATE files SET publication_status=CASE WHEN publication_status='ready' THEN publication_status ELSE 'failed' END,index_status=CASE WHEN index_status='ready' THEN index_status ELSE 'failed' END,processing_error=$2,processing_updated_at=now() WHERE node_id=$1")
        .bind(source.file_id).bind(code).execute(&mut *s.tx).await?;
    complete_receipt(s, source).await
}
pub async fn maintain(app: &App) -> Result<u32, ApiError> {
    super::indexing::reconcile_space(app).await?;
    let rows=sqlx::query("SELECT f.* FROM files f JOIN nodes n ON n.id=f.node_id JOIN filesystems fs ON fs.id=n.filesystem_id WHERE fs.state='active' AND (f.publication_status IN ('pending','parsed') OR (f.publication_status='ready' AND f.index_status='pending')) ORDER BY f.processing_updated_at,f.node_id LIMIT 16")
        .fetch_all(&app.pool).await?;
    let mut count = 0;
    for row in rows {
        let source = Generation {
            file_id: row.get("node_id"),
            generation: row.get("desired_generation"),
        };
        let updated = row.get::<chrono::DateTime<chrono::Utc>, _>("processing_updated_at");
        let base = workflow_status_since(app, &source.workflow_id(), Some(updated)).await?;
        if base == Some(true) {
            continue;
        }
        let status = if row.get::<&str, _>("publication_status") == "ready" {
            let id = crate::temporal::process_file_workflow::index_workflow_id(
                source,
                &super::indexing::VectorSpace::configured(app),
            )?;
            workflow_status_since(app, &id, Some(updated)).await?
        } else {
            base
        };
        if status == Some(true) {
            continue;
        }
        let mut s = open(app, source, true).await?;
        let row = current(&mut s, source).await?;
        if row.get::<chrono::DateTime<chrono::Utc>, _>("processing_updated_at") != updated {
            continue;
        }
        if source_is_live(&mut s, &row).await? {
            if status == Some(false) {
                fail(&mut s, source, "PROCESSING_FAILED").await?;
            }
        } else {
            fail(&mut s, source, "SOURCE_TRASHED").await?;
        }
        s.tx.commit().await?;
        if status.is_none() {
            super::artifacts::dispatch_pending(app, source.file_id).await;
        }
        count += 1;
    }
    Ok(count)
}
async fn source_is_live(s: &mut Session<'_>, row: &PgRow) -> Result<bool, ApiError> {
    match source(s, row).await {
        Ok(_) => Ok(true),
        Err(e) if e.0.is_client_error() => Ok(false),
        Err(e) => Err(e),
    }
}
pub async fn workflow_running(app: &App, source: Generation) -> Result<bool, ApiError> {
    Ok(workflow_status(app, source).await? == Some(true))
}
pub async fn workflow_status(app: &App, source: Generation) -> Result<Option<bool>, ApiError> {
    workflow_status_since(app, &source.workflow_id(), None).await
}
pub async fn workflow_status_since(
    app: &App,
    id: &str,
    since: Option<chrono::DateTime<chrono::Utc>>,
) -> Result<Option<bool>, ApiError> {
    use temporalio_common::protos::temporal::api::{
        common::v1::WorkflowExecution, enums::v1::WorkflowExecutionStatus,
        workflowservice::v1::DescribeWorkflowExecutionRequest,
    };
    let response = tokio::time::timeout(
        std::time::Duration::from_secs(3),
        app.temporal
            .connection()
            .workflow_service()
            .describe_workflow_execution(temporalio_client::tonic::Request::new(
                DescribeWorkflowExecutionRequest {
                    namespace: app.config.temporal_namespace.clone(),
                    execution: Some(WorkflowExecution {
                        workflow_id: id.to_owned(),
                        run_id: String::new(),
                    }),
                },
            )),
    )
    .await
    .map_err(|_| super::indexing::dependency())?;
    match response {
        Ok(response) => {
            let info = response
                .into_inner()
                .workflow_execution_info
                .ok_or_else(super::indexing::dependency)?;
            let status = WorkflowExecutionStatus::try_from(info.status)
                .map_err(|_| super::indexing::dependency())?;
            if status == WorkflowExecutionStatus::Unspecified {
                return Err(super::indexing::dependency());
            }
            if status != WorkflowExecutionStatus::Running {
                let closed = info
                    .close_time
                    .and_then(|t| chrono::DateTime::from_timestamp(t.seconds, t.nanos as u32))
                    .ok_or_else(super::indexing::dependency)?;
                if since.is_some_and(|admitted| closed < admitted) {
                    return Ok(None);
                }
            }
            Ok(Some(status == WorkflowExecutionStatus::Running))
        }
        Err(e) if e.code() == temporalio_client::tonic::Code::NotFound => Ok(None),
        Err(_) => Err(super::indexing::dependency()),
    }
}
pub fn relative_path(path: &str) -> Result<(), ApiError> {
    if path.is_empty() || path.len() > 4096 || path.contains('\\') || path.split('/').count() > 128
    {
        return Err(ApiError::bad("invalid artifact relative path"));
    }
    for part in path.split('/') {
        super::validate_name(part)?;
    }
    Ok(())
}
fn output_tree(
    files: &[(String, Uuid)],
    directories: &[String],
    limit: usize,
) -> Result<BTreeMap<String, Option<Uuid>>, ApiError> {
    let mut tree = BTreeMap::new();
    let mut explicit = BTreeSet::new();
    for (path, upload) in files
        .iter()
        .map(|(p, id)| (p, Some(*id)))
        .chain(directories.iter().map(|p| (p, None)))
    {
        relative_path(path)?;
        if !explicit.insert(path) {
            return Err(ApiError::bad("duplicate artifact path"));
        }
        if let Some(old) = tree.insert(path.clone(), upload)
            && (old.is_some() || upload.is_some())
        {
            return Err(ApiError::bad("artifact file/directory collision"));
        }
        let mut parent = path.as_str();
        while let Some((p, _)) = parent.rsplit_once('/') {
            if tree.get(p).is_some_and(Option::is_some) {
                return Err(ApiError::bad("artifact file/directory collision"));
            }
            tree.entry(p.to_owned()).or_insert(None);
            parent = p;
        }
        if tree.len() > limit {
            return Err(ApiError::state("RESOURCE_LIMIT"));
        }
    }
    Ok(tree)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn tree_rejects_unsafe_duplicate_and_conflicting_paths() {
        let id = Uuid::now_v7();
        for path in ["", "/a", "a/", "a//b", "../a", "a/./b", "a\\b", "a\0b"] {
            assert!(relative_path(path).is_err(), "{path:?}");
        }
        let file = |p: &str| (p.to_owned(), id);
        for files in [
            vec![file("a"), file("a")],
            vec![file("a"), file("a/b")],
            vec![file("a/b"), file("a")],
        ] {
            assert!(output_tree(&files, &[], 10).is_err());
        }
        assert!(output_tree(&[file("a")], &["a".into()], 10).is_err());
        assert!(output_tree(&[file("a/b")], &[], 1).is_err());
        let tree = output_tree(
            &[file("sheet/table.csv")],
            &["empty".into(), "sheet".into()],
            4,
        )
        .unwrap();
        assert_eq!(tree.len(), 3);
        assert_eq!(tree["sheet/table.csv"], Some(id));
        assert_eq!(tree["sheet"], None);
        assert_eq!(tree["empty"], None);
    }
}
