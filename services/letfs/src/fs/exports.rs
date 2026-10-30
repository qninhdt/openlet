use super::{
    nodes::{self, Session},
    paths::{self, Locator, Scope},
};
use crate::http::{ApiError, App};
use chrono::{DateTime, Utc};
use object_store::signer::Signer;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sqlx::{Row, postgres::PgRow};
use std::collections::{BTreeMap, BTreeSet};
use uuid::Uuid;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Selection {
    pub locators: Vec<Locator>,
    #[serde(default)]
    pub artifacts: bool,
    pub request_key: Uuid,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Start {
    pub filesystem_id: Uuid,
    pub scope: Scope,
    pub selection: Selection,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Entry {
    pub id: Uuid,
    pub parent: Option<Uuid>,
    pub name: String,
    pub path: String,
    pub kind: String,
    pub revision: i64,
    pub size: i64,
    pub key: Option<String>,
}
pub struct Snapshot {
    pub name: String,
    pub entries: Vec<Entry>,
}
pub struct Attempt {
    pub id: Uuid,
    pub operation: Uuid,
    pub key: String,
    pub start: Start,
    pub snapshot: Snapshot,
}

pub fn safe_component(name: &str) -> Result<(), ApiError> {
    super::validate_name(name)?;
    let stem = name.split('.').next().unwrap().to_ascii_uppercase();
    if name
        .chars()
        .any(|c| c.is_control() || "\\:<>\"|?*".contains(c))
        || name.ends_with(['.', ' '])
        || matches!(stem.as_str(), "CON" | "PRN" | "AUX" | "NUL")
        || (stem.chars().count() == 4
            && (stem.starts_with("COM") || stem.starts_with("LPT"))
            && matches!(stem.chars().last(), Some('1'..='9' | '¹' | '²' | '³')))
    {
        return Err(ApiError::bad("unsafe archive name"));
    }
    Ok(())
}

pub async fn enumerate(
    app: &App,
    s: &mut Session<'_>,
    start: &Start,
) -> Result<Snapshot, ApiError> {
    let selection = &start.selection;
    if selection.request_key.is_nil()
        || selection.locators.is_empty()
        || selection.locators.len() as i64 > app.config.exports.max_roots
        || (selection.artifacts && selection.locators.len() != 1)
    {
        return Err(ApiError::bad("invalid export selection"));
    }
    let selected =
        paths::resolve(&mut s.tx, s.fs, s.root, &start.scope, &selection.locators).await?;
    let name = if selected.len() == 1 {
        format!(
            "{}{}.zip",
            selected[0].name,
            if selection.artifacts {
                "-artifacts"
            } else {
                ""
            }
        )
    } else {
        "download.zip".into()
    };
    let ids = selected
        .iter()
        .map(|n| n.id)
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();
    if selection.artifacts && selected[0].kind != "file" {
        return Err(ApiError::bad("artifact source must be a file"));
    }
    let roots = if selection.artifacts {
        sqlx::query_scalar::<_, Uuid>(
            "SELECT id FROM nodes WHERE filesystem_id=$1 AND parent_id=$2 ORDER BY id LIMIT $3",
        )
        .bind(s.fs)
        .bind(ids[0])
        .bind(app.config.exports.max_entries + 1)
        .fetch_all(&mut *s.tx)
        .await?
    } else {
        ids
    };
    if roots.len() as i64 > app.config.exports.max_entries {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    let mut rows = sqlx::query(r#"WITH RECURSIVE tree(root,id,parent_id,name,kind,size_bytes,revision,parts,depth) AS (
        SELECT n.id,n.id,n.parent_id,n.name,n.kind,n.size_bytes,n.revision,ARRAY[n.name],0
        FROM nodes n WHERE n.filesystem_id=$1 AND n.id=ANY($2)
        UNION ALL SELECT t.root,n.id,n.parent_id,n.name,n.kind,n.size_bytes,n.revision,t.parts||n.name,t.depth+1
        FROM tree t JOIN nodes n ON n.filesystem_id=$1 AND n.parent_id=t.id
        WHERE t.kind='directory' AND t.depth<128 AND NOT EXISTS(SELECT 1 FROM trash_entries x WHERE x.node_id=n.id)
    ) SELECT t.*,d.object_key,d.storage_kind FROM tree t LEFT JOIN file_data d ON d.node_id=t.id LIMIT $3"#)
        .bind(s.fs).bind(&roots).bind(app.config.exports.max_entries+1).fetch_all(&mut *s.tx).await?;
    if rows.len() as i64 > app.config.exports.max_entries {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    rows.sort_by_key(|r| {
        (
            r.get::<Uuid, _>("root"),
            r.get::<i32, _>("depth"),
            r.get::<Uuid, _>("id"),
        )
    });
    let nested: BTreeSet<Uuid> = rows
        .iter()
        .filter(|r| r.get::<i32, _>("depth") > 0 && roots.contains(&r.get("id")))
        .map(|r| r.get("id"))
        .collect();
    let mut used = BTreeSet::new();
    let mut root_names = BTreeMap::new();
    for row in rows
        .iter()
        .filter(|r| r.get::<i32, _>("depth") == 0 && !nested.contains(&r.get("root")))
    {
        let original: String = row.get("name");
        safe_component(&original)?;
        let mut name = original.clone();
        let mut number = 2;
        while !used.insert(name.to_lowercase()) {
            let suffix = format!(" ({number})");
            let mut prefix = original.clone();
            while prefix.len() + suffix.len() > 255 {
                prefix.pop();
            }
            name = format!("{prefix}{suffix}");
            number += 1;
        }
        root_names.insert(row.get::<Uuid, _>("root"), name);
    }
    let mut entries = Vec::new();
    let mut total = 0_i64;
    let mut archive_names = BTreeSet::new();
    for row in rows {
        let root: Uuid = row.get("root");
        let Some(root_name) = root_names.get(&root) else {
            continue;
        };
        let mut parts: Vec<String> = row.get("parts");
        for part in &parts {
            safe_component(part)?;
        }
        parts[0] = root_name.clone();
        let path = parts.join("/");
        if path.len() > 4096 || !archive_names.insert(path.to_lowercase()) {
            return Err(ApiError::bad("ambiguous archive path"));
        }
        let kind: String = row.get("kind");
        let size: i64 = row.get("size_bytes");
        if kind == "file" && row.get::<Option<String>, _>("storage_kind").is_none() {
            return Err(ApiError::state("SOURCE_CHANGED"));
        }
        total = total
            .checked_add(size)
            .ok_or_else(|| ApiError::state("RESOURCE_LIMIT"))?;
        if total > app.config.exports.max_source_bytes {
            return Err(ApiError::state("RESOURCE_LIMIT"));
        }
        entries.push(Entry {
            id: row.get("id"),
            parent: row.get("parent_id"),
            name: row.get("name"),
            path,
            kind,
            revision: row.get("revision"),
            size,
            key: row.get("object_key"),
        });
    }
    entries.sort_by(|a, b| a.path.cmp(&b.path));
    Ok(Snapshot { name, entries })
}
pub async fn preflight(app: &App, start: &Start) -> Result<(), ApiError> {
    let mut s = nodes::session(app, start.filesystem_id, false).await?;
    enumerate(app, &mut s, start).await?;
    Ok(())
}
fn state(row: &PgRow) -> Value {
    let expired = row
        .get::<Option<DateTime<Utc>>, _>("expires_at")
        .is_some_and(|v| v <= Utc::now());
    json!({"operation_id":row.get::<Uuid,_>("id"),"state":if expired {"expired"} else {row.get::<&str,_>("state")},"error_code":row.get::<Option<String>,_>("error_code"),"name":row.get::<Option<String>,_>("destination_name"),"expires_at":row.get::<Option<DateTime<Utc>>,_>("expires_at"),"size_bytes":row.get::<Option<i64>,_>("size_bytes").map(|v|v.to_string())})
}
pub async fn existing(app: &App, start: &Start) -> Result<Option<Value>, ApiError> {
    if !start
        .scope
        .mounts
        .iter()
        .any(|m| m.filesystem_id == start.filesystem_id)
    {
        return Err(ApiError::not_found());
    }
    let mut s = nodes::session(app, start.filesystem_id, false).await?;
    let row = sqlx::query("SELECT o.*,a.expires_at,a.size_bytes,a.object_key FROM operations o LEFT JOIN export_attempts a ON a.id=o.attempt_id WHERE o.filesystem_id=$1 AND o.actor_id=$2 AND o.kind='export-archive' AND o.request_key=$3")
        .bind(start.filesystem_id).bind(start.scope.actor_id).bind(start.selection.request_key).fetch_optional(&mut *s.tx).await?;
    if let Some(row) = row {
        if row.get::<Value, _>("fingerprint") != json!(start.selection) {
            return Err(ApiError::state("IDEMPOTENCY_CONFLICT"));
        }
        return Ok(Some(state(&row)));
    }
    Ok(None)
}
pub async fn status(
    app: &App,
    fs: Uuid,
    actor: Uuid,
    id: Uuid,
    download: bool,
) -> Result<Value, ApiError> {
    let mut s = nodes::session(app, fs, false).await?;
    let row = sqlx::query("SELECT o.*,a.expires_at,a.size_bytes,a.object_key FROM operations o LEFT JOIN export_attempts a ON a.id=o.attempt_id WHERE o.filesystem_id=$1 AND o.actor_id=$2 AND o.id=$3 AND o.kind='export-archive'")
        .bind(fs).bind(actor).bind(id).fetch_optional(&mut *s.tx).await?.ok_or_else(ApiError::not_found)?;
    let mut result = state(&row);
    if download {
        if result["state"] != "succeeded" {
            return Err(ApiError::state("EXPORT_NOT_READY"));
        }
        let expiry: DateTime<Utc> = row.get("expires_at");
        let seconds = (expiry - Utc::now())
            .num_seconds()
            .min(app.config.storage.download_url_ttl_seconds as i64);
        if seconds <= 0 {
            return Err(ApiError::state("EXPORT_EXPIRED"));
        }
        let url = app
            .signer
            .signed_url_opts(
                axum::http::Method::GET,
                &object_store::path::Path::from(row.get::<String, _>("object_key")),
                std::time::Duration::from_secs(seconds as u64),
                &crate::storage::download_options(row.get::<&str, _>("destination_name")),
            )
            .await
            .map_err(crate::storage::error)?;
        result["download"] = json!({"transport":"object","url":url.as_str(),"expires_at":Utc::now()+chrono::Duration::seconds(seconds)});
    }
    Ok(result)
}

pub async fn prepare(
    app: &App,
    start: &Start,
    generation: i32,
    attempt: Uuid,
) -> Result<Option<Attempt>, ApiError> {
    let mut s = nodes::session(app, start.filesystem_id, true).await?;
    let old = sqlx::query("SELECT * FROM operations WHERE filesystem_id=$1 AND actor_id=$2 AND kind='export-archive' AND request_key=$3 FOR UPDATE")
        .bind(s.fs).bind(start.scope.actor_id).bind(start.selection.request_key).fetch_optional(&mut *s.tx).await?;
    let op = if let Some(row) = old {
        if row.get::<Value, _>("fingerprint") != json!(start.selection) {
            return Err(ApiError::state("IDEMPOTENCY_CONFLICT"));
        }
        match row.get::<&str, _>("state") {
            "succeeded" => return Ok(None),
            "running" if row.get::<i32, _>("attempt_generation") < generation => row.get("id"),
            _ => return Err(ApiError::state("STALE_EXPORT_ATTEMPT")),
        }
    } else {
        super::uploads::capacity(&mut s, app).await?;
        sqlx::query("SELECT pg_advisory_xact_lock(581245930)")
            .execute(&mut *s.tx)
            .await?;
        let count: i64 = sqlx::query_scalar(
            "SELECT count(*) FROM operations WHERE kind='export-archive' AND state='running'",
        )
        .fetch_one(&mut *s.tx)
        .await?;
        if count >= app.config.exports.max_concurrent {
            return Err(ApiError::state("RESOURCE_LIMIT"));
        }
        let op = Uuid::now_v7();
        sqlx::query("INSERT INTO operations(id,filesystem_id,actor_id,kind,request_key,fingerprint,input,durable) VALUES($1,$2,$3,'export-archive',$4,$5,$6,true)")
            .bind(op).bind(s.fs).bind(start.scope.actor_id).bind(start.selection.request_key).bind(json!(start.selection)).bind(json!(start)).execute(&mut *s.tx).await?;
        op
    };
    let snapshot = enumerate(app, &mut s, start).await?;
    let key = format!("exports/{op}/{attempt}.zip");
    sqlx::query("INSERT INTO export_attempts(id,operation_id,object_key,deadline) VALUES($1,$2,$3,now()+$4*interval '1 second')")
        .bind(attempt).bind(op).bind(&key).bind(app.config.exports.runtime_seconds).execute(&mut *s.tx).await?;
    sqlx::query("INSERT INTO object_deletions(object_key,bucket_id,ambiguous_write,eligible_at) VALUES($1,$2,true,now()+($3+900)*interval '1 second')")
        .bind(&key).bind(s.bucket).bind(app.config.exports.runtime_seconds).execute(&mut *s.tx).await?;
    sqlx::query("UPDATE operations SET attempt_generation=$2,attempt_id=$3,destination_name=$4,updated_at=now() WHERE id=$1")
        .bind(op).bind(generation).bind(attempt).bind(&snapshot.name).execute(&mut *s.tx).await?;
    s.tx.commit().await?;
    Ok(Some(Attempt {
        id: attempt,
        operation: op,
        key,
        start: start.clone(),
        snapshot,
    }))
}
pub async fn publish(app: &App, attempt: &Attempt, size: i64) -> Result<(), ApiError> {
    let mut s = nodes::session(app, attempt.start.filesystem_id, true).await?;
    let current: Option<Uuid> = sqlx::query_scalar("SELECT o.id FROM operations o JOIN export_attempts a ON a.id=o.attempt_id WHERE o.id=$1 AND o.state='running' AND o.attempt_id=$2 AND a.deadline>now() FOR UPDATE OF o")
        .bind(attempt.operation).bind(attempt.id).fetch_optional(&mut *s.tx).await?;
    if current.is_none() {
        return Err(ApiError::state("STALE_EXPORT_ATTEMPT"));
    }
    let fresh = enumerate(app, &mut s, &attempt.start).await?;
    if fresh.entries != attempt.snapshot.entries || fresh.name != attempt.snapshot.name {
        return Err(ApiError::state("SOURCE_CHANGED"));
    }
    sqlx::query("UPDATE export_attempts SET expires_at=now()+$2*interval '1 second',size_bytes=$3,multipart_id=NULL WHERE id=$1")
        .bind(attempt.id).bind(app.config.exports.retention_seconds).bind(size).execute(&mut *s.tx).await?;
    sqlx::query(
        "UPDATE object_deletions SET eligible_at=now()+$2*interval '1 second' WHERE object_key=$1",
    )
    .bind(&attempt.key)
    .bind(app.config.exports.retention_seconds)
    .execute(&mut *s.tx)
    .await?;
    sqlx::query("UPDATE operations SET state='succeeded',total_nodes=$2,total_bytes=$3,updated_at=now() WHERE id=$1")
        .bind(attempt.operation).bind(attempt.snapshot.entries.len() as i64).bind(size).execute(&mut *s.tx).await?;
    s.tx.commit().await?;
    Ok(())
}

pub async fn maintain(app: &App) -> Result<u32, ApiError> {
    use object_store::multipart::MultipartStore;
    use temporalio_common::protos::temporal::api::{
        common::v1::WorkflowExecution, enums::v1::WorkflowExecutionStatus,
        workflowservice::v1::DescribeWorkflowExecutionRequest,
    };
    let rows = sqlx::query("SELECT id,input FROM operations WHERE kind='export-archive' AND state='running' ORDER BY updated_at,id LIMIT 16").fetch_all(&app.pool).await?;
    let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(30);
    let mut count = 0;
    for row in rows {
        if tokio::time::Instant::now() >= deadline {
            return Ok(count);
        }
        let id: Uuid = row.get("id");
        let start: Start = serde_json::from_value(row.get("input"))
            .map_err(|_| ApiError::state("INVALID_EXPORT_STATE"))?;
        let description = tokio::time::timeout(
            std::time::Duration::from_secs(3),
            app.temporal
                .connection()
                .workflow_service()
                .describe_workflow_execution(temporalio_client::tonic::Request::new(
                    DescribeWorkflowExecutionRequest {
                        namespace: app.config.temporal_namespace.clone(),
                        execution: Some(WorkflowExecution {
                            workflow_id: crate::temporal::export_archive_workflow::workflow_id(
                                &start,
                            ),
                            run_id: String::new(),
                        }),
                    },
                )),
        )
        .await;
        let closed = match &description {
            Ok(Ok(response)) => response
                .get_ref()
                .workflow_execution_info
                .as_ref()
                .is_some_and(|info| {
                    WorkflowExecutionStatus::try_from(info.status).is_ok_and(|status| {
                        status != WorkflowExecutionStatus::Running
                            && status != WorkflowExecutionStatus::Unspecified
                    })
                }),
            _ => false,
        };
        sqlx::query("UPDATE operations SET state=CASE WHEN $2 THEN 'failed' ELSE state END,error_code=CASE WHEN $2 THEN 'EXPORT_FAILED' ELSE error_code END,updated_at=now() WHERE id=$1 AND state='running'")
            .bind(id).bind(closed).execute(&app.pool).await?;
        count += 1;
    }
    let rows=sqlx::query("SELECT a.id,a.object_key,a.multipart_id FROM export_attempts a JOIN operations o ON o.id=a.operation_id WHERE a.multipart_id IS NOT NULL AND (a.deadline<=now() OR o.state!='running' OR o.attempt_id!=a.id) ORDER BY a.deadline,a.id LIMIT 16").fetch_all(&app.pool).await?;
    for row in rows {
        if tokio::time::Instant::now() >= deadline {
            break;
        }
        let key: String = row.get("object_key");
        let remote: String = row.get("multipart_id");
        match tokio::time::timeout(
            std::time::Duration::from_secs(10)
                .min(deadline.saturating_duration_since(tokio::time::Instant::now())),
            app.storage
                .abort_multipart(&object_store::path::Path::from(key), &remote),
        )
        .await
        {
            Ok(Ok(())) | Ok(Err(object_store::Error::NotFound { .. })) => {
                sqlx::query(
                    "UPDATE export_attempts SET multipart_id=NULL WHERE id=$1 AND multipart_id=$2",
                )
                .bind(row.get::<Uuid, _>("id"))
                .bind(remote)
                .execute(&app.pool)
                .await?;
            }
            Ok(Err(e)) => return Err(crate::storage::error(e)),
            Err(_) => break,
        }
        count += 1;
    }
    Ok(count)
}

#[cfg(test)]
mod tests {
    #[test]
    fn archive_names_reject_extraction_ambiguity() {
        for name in [
            "",
            ".",
            "..",
            "a/b",
            "a\\b",
            "/root",
            "C:drive",
            "CON.txt",
            "lpt1",
            "a.",
            "a ",
            "x\ny",
            "a?b",
            "COM¹.txt",
            "LPT²",
            "com³.csv",
        ] {
            assert!(super::safe_component(name).is_err(), "{name}");
        }
        for name in ["Việt Nam", "report.pdf", "composition", "COM10.txt"] {
            assert!(super::safe_component(name).is_ok());
        }
    }
}
