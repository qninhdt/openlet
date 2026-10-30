use super::{nodes::*, paths, uploads};
use crate::http::{ApiError, App};
use base64::{Engine, prelude::BASE64_STANDARD};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{Row, postgres::PgRow};
use std::collections::{BTreeMap, BTreeSet};
use uuid::Uuid;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Attempt {
    pub operation_id: Uuid,
    pub generation: i32,
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
pub async fn open(app: &App, op: Uuid, lifecycle: bool) -> Result<Session<'_>, ApiError> {
    let fs: Uuid = sqlx::query_scalar(
        "SELECT filesystem_id FROM operations WHERE id=$1 AND kind='process-file'",
    )
    .bind(op)
    .fetch_optional(&app.pool)
    .await?
    .ok_or_else(ApiError::not_found)?;
    if lifecycle {
        lifecycle_session(app, fs).await
    } else {
        session(app, fs, true).await
    }
}
async fn operation(s: &mut Session<'_>, id: Uuid) -> Result<PgRow, ApiError> {
    let row = sqlx::query("SELECT * FROM operations WHERE id=$1 AND filesystem_id=$2 AND kind='process-file' FOR UPDATE")
        .bind(id).bind(s.fs).fetch_optional(&mut *s.tx).await?.ok_or_else(ApiError::not_found)?;
    if row
        .get::<Option<chrono::DateTime<chrono::Utc>>, _>("superseded_at")
        .is_some()
    {
        return Err(ApiError::state("SOURCE_REPLACED"));
    }
    if !matches!(row.get::<&str, _>("state"), "running" | "succeeded") {
        return Err(ApiError::state("PROCESSING_NOT_ACTIVE"));
    }
    Ok(row)
}
async fn source(s: &mut Session<'_>, row: &PgRow) -> Result<(Node, PgRow), ApiError> {
    let scope = paths::Scope {
        actor_id: row.get("actor_id"),
        mounts: vec![paths::Mount {
            path: "/".into(),
            filesystem_id: s.fs,
        }],
    };
    let locator = paths::Locator {
        node_id: Some(row.get("source_id")),
        path: None,
        cwd_id: None,
        expected_node_id: None,
        expected_parent_id: None,
    };
    let node = s.resolve(&scope, &locator).await?;
    node.writable()?;
    let data = sqlx::query("SELECT * FROM file_data WHERE node_id=$1")
        .bind(node.id)
        .fetch_one(&mut *s.tx)
        .await?;
    let identity: Value = row.get("fingerprint");
    let key = data.get::<Option<String>, _>("object_key");
    let digest = data
        .get::<Option<Vec<u8>>, _>("inline_bytes")
        .map(|b| format!("{:x}", Sha256::digest(b)));
    if identity["object_key"] != json!(key) || identity["inline_sha256"] != json!(digest) {
        return Err(ApiError::state("SOURCE_REPLACED"));
    }
    Ok((node, data))
}
pub async fn validate(s: &mut Session<'_>, attempt: &Attempt) -> Result<PgRow, ApiError> {
    let row = operation(s, attempt.operation_id).await?;
    if row.get::<i32, _>("attempt_generation") != attempt.generation
        || row.get::<Option<Uuid>, _>("attempt_id") != Some(attempt.attempt_id)
    {
        return Err(ApiError::state("STALE_PROCESSING_ATTEMPT"));
    }
    source(s, &row).await?;
    Ok(row)
}
async fn discard_uploads(s: &mut Session<'_>, op: Uuid) -> Result<(), ApiError> {
    sqlx::query("INSERT INTO object_deletions(object_key,bucket_id,ambiguous_write,eligible_at) SELECT candidate_key,bucket_id,write_expires_at IS NOT NULL,greatest(now()+interval '15 minutes',transfer_deadline) FROM uploads WHERE processing_operation_id=$1 AND state!='finalized' AND candidate_key IS NOT NULL ON CONFLICT(object_key) DO UPDATE SET state='pending',ambiguous_write=object_deletions.ambiguous_write OR excluded.ambiguous_write,eligible_at=greatest(object_deletions.eligible_at,excluded.eligible_at)")
        .bind(op).execute(&mut *s.tx).await?;
    sqlx::query("UPDATE uploads SET state='aborted',inline_bytes=NULL,updated_at=now() WHERE processing_operation_id=$1 AND state IN ('created','transferring','uploaded')")
        .bind(op).execute(&mut *s.tx).await?;
    Ok(())
}
pub async fn prepare(app: &App, attempt: &Attempt) -> Result<Value, ApiError> {
    if !(1..=3).contains(&attempt.generation) || attempt.attempt_id.is_nil() {
        return Err(ApiError::bad("invalid processing attempt"));
    }
    let mut s = open(app, attempt.operation_id, false).await?;
    let row = operation(&mut s, attempt.operation_id).await?;
    let (node, data) = source(&mut s, &row).await?;
    // A committed publication wins even when Temporal retries after losing the result.
    if row.get::<&str, _>("state") == "succeeded" {
        return Ok(json!({"state":"succeeded","source_id":node.id}));
    }
    let generation = row.get::<i32, _>("attempt_generation");
    if generation > attempt.generation
        || (generation == attempt.generation
            && row.get::<Option<Uuid>, _>("attempt_id") != Some(attempt.attempt_id))
    {
        return Err(ApiError::state("STALE_PROCESSING_ATTEMPT"));
    }
    if generation < attempt.generation {
        discard_uploads(&mut s, attempt.operation_id).await?;
        sqlx::query("UPDATE operations SET attempt_generation=$2,attempt_id=$3,updated_at=now() WHERE id=$1")
            .bind(attempt.operation_id).bind(attempt.generation).bind(attempt.attempt_id).execute(&mut *s.tx).await?;
    }
    let identity: Value = row.get("fingerprint");
    let mut value = json!({"state":"running","source_id":node.id,"format":identity["format"],"size_bytes":node.size_bytes,
        "inline_limit_bytes":app.config.inline_limit,"multipart_threshold_bytes":app.config.storage.multipart_threshold_bytes,"max_outputs":app.config.processing_max_outputs,"max_output_bytes":app.config.processing_max_output_bytes});
    if let Some(key) = data.get::<Option<String>, _>("object_key") {
        let url = crate::storage::download_url(app, &key, "source").await?;
        value["source"] = json!({"transport":"object","url":url.as_str()});
    } else {
        value["source"] = json!({"transport":"inline","bytes_base64":BASE64_STANDARD.encode(data.get::<Vec<u8>,_>("inline_bytes"))});
    }
    s.tx.commit().await?;
    Ok(value)
}
pub async fn prepare_output(
    app: &App,
    attempt: &Attempt,
    output: Output,
) -> Result<Value, ApiError> {
    relative_path(&output.path)?;
    let mut s = open(app, attempt.operation_id, false).await?;
    let row = validate(&mut s, attempt).await?;
    if row.get::<&str, _>("state") != "running" {
        return Err(ApiError::state("PROCESSING_NOT_ACTIVE"));
    }
    let fingerprint = json!({"path":output.path,"storage":output.storage,"size_bytes":output.size_bytes,"content_md5":output.content_md5});
    let old = sqlx::query("SELECT id,input FROM uploads WHERE processing_operation_id=$1 AND processing_generation=$2 AND relative_path=$3")
        .bind(attempt.operation_id).bind(attempt.generation).bind(&output.path).fetch_optional(&mut *s.tx).await?;
    let id = if let Some(old) = old {
        if old.get::<Value, _>("input") != fingerprint {
            return Err(ApiError::state("IDEMPOTENCY_CONFLICT"));
        }
        old.get("id")
    } else {
        let totals = sqlx::query("SELECT count(*) AS count,coalesce(sum(expected_size),0)::bigint AS bytes FROM uploads WHERE processing_operation_id=$1 AND processing_generation=$2")
            .bind(attempt.operation_id).bind(attempt.generation).fetch_one(&mut *s.tx).await?;
        let size = uploads::byte_count(&output.size_bytes)?;
        if totals.get::<i64, _>("count") >= app.config.processing_max_outputs
            || size > app.config.processing_max_output_bytes - totals.get::<i64, _>("bytes")
        {
            return Err(ApiError::state("RESOURCE_LIMIT"));
        }
        let input: Input = serde_json::from_value(json!({"storage":output.storage,"size_bytes":output.size_bytes,"content_md5":output.content_md5}))
            .map_err(|_| ApiError::bad("invalid output metadata"))?;
        let id = uploads::insert(
            &mut s,
            app,
            row.get("actor_id"),
            Uuid::now_v7(),
            fingerprint,
            &input,
        )
        .await?;
        sqlx::query("UPDATE uploads SET processing_operation_id=$2,processing_generation=$3,processing_attempt_id=$4,relative_path=$5 WHERE id=$1")
            .bind(id).bind(attempt.operation_id).bind(attempt.generation).bind(attempt.attempt_id).bind(output.path).execute(&mut *s.tx).await?;
        id
    };
    let fs = s.fs;
    s.tx.commit().await?;
    uploads::prepare_transfer(app, fs, id, &uploads::Access::Processor(attempt.clone())).await
}
pub async fn complete(app: &App, attempt: &Attempt, input: Complete) -> Result<Value, ApiError> {
    if input.uploads.len() as i64 > app.config.processing_max_outputs
        || input.directories.len() as i64 > app.config.processing_max_outputs
    {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    let mut s = open(app, attempt.operation_id, false).await?;
    let op = validate(&mut s, attempt).await?;
    if op.get::<&str, _>("state") == "succeeded" {
        let saved: Option<Value> = op.get("input");
        if saved != Some(json!(input)) {
            return Err(ApiError::state("IDEMPOTENCY_CONFLICT"));
        }
        return Ok(json!({"state":"succeeded","source_id":op.get::<Uuid,_>("source_id")}));
    }
    let rows = sqlx::query("SELECT * FROM uploads WHERE processing_operation_id=$1 AND processing_generation=$2 AND processing_attempt_id=$3 ORDER BY relative_path FOR UPDATE")
        .bind(attempt.operation_id).bind(attempt.generation).bind(attempt.attempt_id).fetch_all(&mut *s.tx).await?;
    let ids: BTreeSet<Uuid> = input.uploads.iter().copied().collect();
    if ids.len() != input.uploads.len()
        || ids.len() != rows.len()
        || rows
            .iter()
            .any(|r| !ids.contains(&r.get("id")) || r.get::<&str, _>("state") != "uploaded")
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
    let source: Uuid = op.get("source_id");
    let source_depth = depth(&mut s.tx, s.fs, source).await? as usize;
    if tree
        .keys()
        .any(|p| source_depth + p.split('/').count() > 128)
    {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    let bytes = rows
        .iter()
        .try_fold(0_i64, |total, r| {
            total.checked_add(r.get::<i64, _>("expected_size"))
        })
        .ok_or_else(|| ApiError::state("RESOURCE_LIMIT"))?;
    if bytes > app.config.processing_max_output_bytes {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    if super::artifacts::has_children(&mut s, source).await? {
        return Err(ApiError::state("PROCESSING_ALREADY_PUBLISHED"));
    }
    s.usage(bytes).await?;
    s.add_nodes(tree.len() as i64).await?;
    let node_ids = tree
        .keys()
        .map(|path| (path.clone(), Uuid::now_v7()))
        .collect::<BTreeMap<_, _>>();
    let entries = tree
        .iter()
        .map(|(path, upload)| {
            let (parent, name) = path
                .rsplit_once('/')
                .map_or((source, path.as_str()), |(p, n)| (node_ids[p], n));
            json!({"id":node_ids[path],"parent":parent,"name":name,"upload":upload})
        })
        .collect::<Vec<_>>();
    sqlx::query("WITH entries AS (SELECT * FROM jsonb_to_recordset($3) AS x(id uuid,parent uuid,name text,upload uuid)) INSERT INTO nodes(id,filesystem_id,parent_id,name,kind,size_bytes,staging_operation_id) SELECT e.id,$1,e.parent,e.name,CASE WHEN e.upload IS NULL THEN 'directory' ELSE 'file' END,coalesce(u.expected_size,0),$2 FROM entries e LEFT JOIN uploads u ON u.id=e.upload")
        .bind(s.fs).bind(attempt.operation_id).bind(json!(entries)).execute(&mut *s.tx).await?;
    sqlx::query("WITH entries AS (SELECT * FROM jsonb_to_recordset($1) AS x(id uuid,parent uuid,name text,upload uuid)) INSERT INTO file_data(node_id,storage_kind,inline_bytes,object_key) SELECT e.id,CASE WHEN u.transport='inline' THEN 'inline' ELSE 'object' END,u.inline_bytes,u.candidate_key FROM entries e JOIN uploads u ON u.id=e.upload")
        .bind(json!(entries)).execute(&mut *s.tx).await?;
    sqlx::query("UPDATE uploads u SET state='finalized',result_node_id=e.id,result=jsonb_build_object('node_id',e.id,'state','finalized','revision','1'),inline_bytes=NULL,updated_at=now() FROM jsonb_to_recordset($1) AS e(id uuid,parent uuid,name text,upload uuid) WHERE u.id=e.upload")
        .bind(json!(entries)).execute(&mut *s.tx).await?;
    sqlx::query("UPDATE operations SET state='succeeded',result_node_id=source_id,input=$2,total_nodes=$3,total_bytes=$4,updated_at=now() WHERE id=$1")
        .bind(attempt.operation_id).bind(json!(input)).bind(tree.len() as i64).bind(bytes).execute(&mut *s.tx).await?;
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
    let mut s = open(app, attempt.operation_id, true).await?;
    let row = validate(&mut s, attempt).await?;
    if row.get::<&str, _>("state") == "succeeded" {
        return Ok(());
    }
    discard_uploads(&mut s, attempt.operation_id).await?;
    sqlx::query("UPDATE operations SET state='failed',error_code=$2,updated_at=now() WHERE id=$1 AND state='running'")
        .bind(attempt.operation_id).bind(code).execute(&mut *s.tx).await?;
    s.tx.commit().await?;
    Ok(())
}
pub async fn maintain(app: &App) -> Result<u32, ApiError> {
    use temporalio_common::protos::temporal::api::{
        common::v1::WorkflowExecution, enums::v1::WorkflowExecutionStatus,
        workflowservice::v1::DescribeWorkflowExecutionRequest,
    };
    let ids: Vec<Uuid> = sqlx::query_scalar("SELECT o.id FROM operations o WHERE o.kind='process-file' AND ((o.state='running' AND o.superseded_at IS NULL) OR EXISTS(SELECT 1 FROM uploads u WHERE u.processing_operation_id=o.id AND u.state IN ('created','transferring','uploaded'))) ORDER BY o.updated_at,o.id LIMIT 16")
        .fetch_all(&app.pool).await?;
    let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(30);
    let mut count = 0;
    for op in ids {
        if tokio::time::Instant::now() >= deadline {
            break;
        }
        let described = tokio::time::timeout(
            std::time::Duration::from_secs(3),
            app.temporal
                .connection()
                .workflow_service()
                .describe_workflow_execution(temporalio_client::tonic::Request::new(
                    DescribeWorkflowExecutionRequest {
                        namespace: app.config.temporal_namespace.clone(),
                        execution: Some(WorkflowExecution {
                            workflow_id: format!("process-file/{op}"),
                            run_id: String::new(),
                        }),
                    },
                )),
        )
        .await;
        let closed = match &described {
            Ok(Ok(response)) => response
                .get_ref()
                .workflow_execution_info
                .as_ref()
                .is_some_and(|v| {
                    WorkflowExecutionStatus::try_from(v.status).is_ok_and(|status| {
                        status != WorkflowExecutionStatus::Running
                            && status != WorkflowExecutionStatus::Unspecified
                    })
                }),
            _ => false,
        };
        let absent =
            matches!(&described,Ok(Err(e)) if e.code()==temporalio_client::tonic::Code::NotFound);
        let mut s = open(app, op, true).await?;
        let row = sqlx::query("SELECT state,superseded_at FROM operations WHERE id=$1 FOR UPDATE")
            .bind(op)
            .fetch_one(&mut *s.tx)
            .await?;
        let current = row.get::<&str, _>("state") == "running"
            && row
                .get::<Option<chrono::DateTime<chrono::Utc>>, _>("superseded_at")
                .is_none();
        if closed && current {
            sqlx::query("UPDATE operations SET state='failed',error_code='PROCESSING_FAILED' WHERE id=$1 AND state='running'").bind(op).execute(&mut *s.tx).await?;
        }
        if !current || closed {
            discard_uploads(&mut s, op).await?;
        }
        sqlx::query("UPDATE operations SET updated_at=now() WHERE id=$1")
            .bind(op)
            .execute(&mut *s.tx)
            .await?;
        s.tx.commit().await?;
        if absent && current {
            crate::temporal::process_file_workflow::dispatch(app, op).await?;
        }
        count += 1;
    }
    Ok(count)
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
