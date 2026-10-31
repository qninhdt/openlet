use super::{nodes::*, paths};
use crate::http::{ApiError, App};
use serde_json::{Value, json};
use sqlx::Row;
use uuid::Uuid;

pub async fn inline(app: &App, fs: Uuid, r: Request) -> Result<Value, ApiError> {
    let key = needed(r.input.request_key)?;
    if key.is_nil() || r.input.text.is_some() || r.input.locators.is_some() {
        return Err(ApiError::bad("invalid copy input"));
    }
    let fingerprint = serde_json::to_value(&r.input).map_err(|_| ApiError::bad("invalid copy"))?;
    let mut s = session(app, fs, true).await?;
    if let Some(row)=sqlx::query("SELECT fingerprint,state,result_node_id,durable FROM operations WHERE filesystem_id=$1 AND actor_id=$2 AND kind='copy' AND request_key=$3 FOR UPDATE").bind(fs).bind(r.scope.actor_id).bind(key).fetch_optional(&mut *s.tx).await? {
        if row.get::<Value,_>("fingerprint")!=fingerprint {return Err(ApiError::state("IDEMPOTENCY_CONFLICT"));}
        if row.get::<bool,_>("durable"){return Err(ApiError::state("DURABLE_COPY_REQUIRED"));}
        return Ok(json!({"node_id":row.get::<Option<Uuid>,_>("result_node_id"),"state":row.get::<String,_>("state")}));
    }
    let l = needed(r.input.locator)?;
    let source = s.resolve(&r.scope, &l).await?;
    paths::guard(&l, source.id, false)?;
    source.revision(r.input.revision.as_deref())?;
    if source.kind != "file" || super::artifacts::has_children(&mut s, source.id).await? {
        return Err(ApiError::state("DURABLE_COPY_REQUIRED"));
    }
    let data = sqlx::query("SELECT storage_kind,inline_bytes FROM file_data WHERE node_id=$1")
        .bind(source.id)
        .fetch_one(&mut *s.tx)
        .await?;
    if data.get::<String, _>("storage_kind") != "inline" {
        return Err(ApiError::state("DURABLE_COPY_REQUIRED"));
    }
    let l = needed(r.input.parent)?;
    let parent = s.resolve(&r.scope, &l).await?;
    paths::guard(&l, parent.id, true)?;
    parent.writable()?;
    parent.directory()?;
    if depth(&mut s.tx, fs, parent.id).await? >= 128 {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    let name = needed(r.input.name)?;
    s.name(parent.id, &name)?;
    let size = source.size_bytes.parse::<i64>().unwrap();
    s.add_nodes(1).await?;
    s.usage(size).await?;
    let id = Uuid::now_v7();
    sqlx::query("INSERT INTO nodes(id,filesystem_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,$4,'file',$5)").bind(id).bind(fs).bind(parent.id).bind(name).bind(size).execute(&mut *s.tx).await?;
    sqlx::query("INSERT INTO file_data(node_id,storage_kind,inline_bytes) VALUES($1,'inline',$2)")
        .bind(id)
        .bind(data.get::<Vec<u8>, _>("inline_bytes"))
        .execute(&mut *s.tx)
        .await?;
    sqlx::query("INSERT INTO operations(id,filesystem_id,actor_id,kind,request_key,fingerprint,state,result_node_id) VALUES($1,$2,$3,'copy',$4,$5,'succeeded',$6)").bind(Uuid::now_v7()).bind(fs).bind(r.scope.actor_id).bind(key).bind(fingerprint).bind(id).execute(&mut *s.tx).await?;
    bump(&mut s.tx, &[parent.id]).await?;
    let n = fetch(&mut s.tx, id).await?;
    let bytes: Vec<u8> = data.get("inline_bytes");
    use sha2::{Digest, Sha256};
    let digest = format!("{:x}", Sha256::digest(&bytes));
    super::artifacts::record_intent(
        &mut s,
        &n,
        r.scope.actor_id,
        Uuid::now_v7(),
        None,
        Some(&digest),
    )
    .await?;
    s.tx.commit().await?;
    super::artifacts::dispatch_pending(app, id).await;
    Ok(json!({"node_id":id,"state":"succeeded"}))
}

#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
pub struct Start {
    pub filesystem_id: Uuid,
    pub request: Request,
}
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
pub struct Continue {
    pub operation_id: Option<Uuid>,
    pub start: Option<Start>,
}

pub async fn existing(app: &App, start: &Start) -> Result<Option<Value>, ApiError> {
    let r = &start.request;
    let key = needed(r.input.request_key)?;
    let row=sqlx::query("SELECT id,filesystem_id,fingerprint,state,result_node_id,total_nodes,total_bytes,error_code FROM operations WHERE filesystem_id=$1 AND actor_id=$2 AND kind='copy' AND request_key=$3")
 .bind(start.filesystem_id).bind(r.scope.actor_id).bind(key).fetch_optional(&app.pool).await?;
    if let Some(row) = row {
        if row.get::<Value, _>("fingerprint") != json!(r.input) {
            return Err(ApiError::state("IDEMPOTENCY_CONFLICT"));
        }
        return Ok(Some(operation_value(&row)));
    }
    Ok(None)
}
pub async fn operation(app: &App, fs: Uuid, op: Uuid) -> Result<Value, ApiError> {
    let row = sqlx::query("SELECT * FROM operations WHERE filesystem_id=$1 AND id=$2")
        .bind(fs)
        .bind(op)
        .fetch_optional(&app.pool)
        .await?
        .ok_or_else(ApiError::not_found)?;
    Ok(operation_value(&row))
}
pub fn operation_value(row: &sqlx::postgres::PgRow) -> Value {
    let state: String = row.get("state");
    let id: Uuid = row.get("id");
    let fs: Uuid = row.get("filesystem_id");
    json!({"operation_id":id,"state":if state=="discarding"{"running"}else{&state},"phase":state,"node_id":row.get::<Option<Uuid>,_>("result_node_id"),"progress":{"nodes":row.get::<i64,_>("total_nodes").to_string(),"bytes":row.get::<i64,_>("total_bytes").to_string()},"error_code":row.get::<Option<String>,_>("error_code"),"status_url":format!("/internal/v1/filesystems/{fs}/operations/{id}")})
}

pub async fn prepare(app: &App, start: Start) -> Result<Uuid, ApiError> {
    let fs = start.filesystem_id;
    let r = start.request;
    let key = needed(r.input.request_key)?;
    if key.is_nil() || r.input.text.is_some() || r.input.locators.is_some() {
        return Err(ApiError::bad("invalid copy input"));
    }
    let mut s = session(app, fs, true).await?;
    if let Some(row)=sqlx::query("SELECT id,fingerprint FROM operations WHERE filesystem_id=$1 AND actor_id=$2 AND kind='copy' AND request_key=$3 FOR UPDATE").bind(fs).bind(r.scope.actor_id).bind(key).fetch_optional(&mut *s.tx).await?{
  if row.get::<Value,_>("fingerprint")!=json!(r.input){return Err(ApiError::state("IDEMPOTENCY_CONFLICT"));}return Ok(row.get("id"));
 }
    super::uploads::capacity(&mut s, app).await?;
    let locator = r
        .input
        .locator
        .as_ref()
        .ok_or_else(|| ApiError::bad("source required"))?;
    let source = s.resolve(&r.scope, locator).await?;
    paths::guard(locator, source.id, false)?;
    source.revision(r.input.revision.as_deref())?;
    let parent_locator = r
        .input
        .parent
        .as_ref()
        .ok_or_else(|| ApiError::bad("parent required"))?;
    let parent = s.resolve(&r.scope, parent_locator).await?;
    paths::guard(parent_locator, parent.id, true)?;
    parent.writable()?;
    parent.directory()?;
    cycle(&mut s.tx, fs, source.id, parent.id).await?;
    let name = needed(r.input.name.clone())?;
    s.name(parent.id, &name)?;
    let conflict: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM nodes WHERE filesystem_id=$1 AND parent_id=$2 AND name=$3)",
    )
    .bind(fs)
    .bind(parent.id)
    .bind(&name)
    .fetch_one(&mut *s.tx)
    .await?;
    if conflict {
        return Err(ApiError::state("NAME_CONFLICT"));
    }
    let max_bytes: i64 = sqlx::query_scalar("SELECT limit_bytes FROM quota_buckets WHERE id=$1")
        .bind(s.bucket)
        .fetch_one(&mut *s.tx)
        .await?;
    let op = Uuid::now_v7();
    let root = Uuid::now_v7();
    sqlx::query("INSERT INTO operations(id,filesystem_id,actor_id,kind,request_key,fingerprint,durable,input,source_id,destination_parent_id,destination_name,staging_root_id,max_copy_bytes,max_copy_nodes,deadline) VALUES($1,$2,$3,'copy',$4,$5,true,$6,$7,$8,$9,$10,$11,$12,now()+interval '1 hour')")
 .bind(op).bind(fs).bind(r.scope.actor_id).bind(key).bind(json!(r.input)).bind(json!({"scope":r.scope,"input":r.input})).bind(source.id).bind(parent.id).bind(name).bind(root).bind(max_bytes).bind(app.config.max_copy_nodes).execute(&mut *s.tx).await?;
    add_items(
        &mut s,
        op,
        vec![json!({"source":source.id,"destination":root,"parent":null,"depth":0})],
    )
    .await?;
    s.tx.commit().await?;
    Ok(op)
}
async fn add_items(s: &mut Session<'_>, op: Uuid, items: Vec<Value>) -> Result<(), ApiError> {
    if items.is_empty() {
        return Ok(());
    }
    let rows=sqlx::query(r#"WITH input AS (SELECT * FROM jsonb_to_recordset($3) AS x(source uuid,destination uuid,parent uuid,depth int))
 INSERT INTO copy_items(operation_id,source_id,source_parent_id,source_name,source_revision,size_bytes,kind,destination_id,destination_parent_id,depth,source_key,target_key,state,file_child_ids)
 SELECT $1,n.id,n.parent_id,n.name,n.revision,n.size_bytes,n.kind,x.destination,x.parent,x.depth,d.object_key,
 CASE WHEN d.storage_kind='object' THEN 'objects/'||$4||'/'||x.destination::text END,
 CASE WHEN n.kind='directory' OR cardinality(children.ids)>0 THEN 'unopened' WHEN d.storage_kind='object' THEN 'pending' ELSE 'ready' END,children.ids
 FROM input x JOIN nodes n ON n.id=x.source AND n.filesystem_id=$2 LEFT JOIN file_data d ON d.node_id=n.id
 CROSS JOIN LATERAL (SELECT ARRAY(SELECT c.id FROM nodes c WHERE n.kind='file' AND c.filesystem_id=$2 AND c.parent_id=n.id ORDER BY c.id LIMIT (SELECT max_copy_nodes+1 FROM operations WHERE id=$1)) AS ids) children
 ON CONFLICT(operation_id,source_id) DO NOTHING RETURNING destination_id,size_bytes"#)
 .bind(op).bind(s.fs).bind(json!(items)).bind(s.bucket.to_string()).fetch_all(&mut *s.tx).await?;
    let ids: Vec<Uuid> = rows.iter().map(|r| r.get("destination_id")).collect();
    let mut bytes = 0_i64;
    for r in &rows {
        bytes = bytes
            .checked_add(r.get::<i64, _>("size_bytes"))
            .ok_or_else(|| ApiError::state("RESOURCE_LIMIT"))?;
    }
    let count = ids.len() as i64;
    let updated=sqlx::query("UPDATE operations SET total_nodes=total_nodes+$2,total_bytes=total_bytes+$3,updated_at=now() WHERE id=$1 AND total_nodes+$2<=max_copy_nodes AND total_bytes+$3<=max_copy_bytes AND deadline>now() AND state='running'").bind(op).bind(count).bind(bytes).execute(&mut *s.tx).await?.rows_affected();
    if updated != 1 {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    s.add_nodes(count).await?;
    sqlx::query("INSERT INTO nodes(id,filesystem_id,parent_id,name,kind,size_bytes,staging_operation_id) SELECT i.destination_id,$2,i.destination_parent_id,CASE WHEN i.destination_parent_id IS NULL THEN o.destination_name ELSE i.source_name END,i.kind,i.size_bytes,$1 FROM copy_items i JOIN operations o ON o.id=i.operation_id WHERE i.operation_id=$1 AND i.destination_id=ANY($3)").bind(op).bind(s.fs).bind(&ids).execute(&mut *s.tx).await?;
    sqlx::query("INSERT INTO file_data(node_id,storage_kind,inline_bytes,object_key) SELECT i.destination_id,CASE WHEN i.target_key IS NULL THEN 'inline' ELSE 'object' END,CASE WHEN i.target_key IS NULL THEN d.inline_bytes END,i.target_key FROM copy_items i JOIN file_data d ON d.node_id=i.source_id WHERE i.operation_id=$1 AND i.destination_id=ANY($2) AND i.kind='file'").bind(op).bind(&ids).execute(&mut *s.tx).await?;
    Ok(())
}
async fn scope_session(app: &App, op: Uuid, lifecycle: bool) -> Result<Session<'_>, ApiError> {
    let fs: Uuid = sqlx::query_scalar("SELECT filesystem_id FROM operations WHERE id=$1")
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
fn id_locator(id: Uuid) -> paths::Locator {
    paths::Locator {
        node_id: Some(id),
        path: None,
        cwd_id: None,
        expected_node_id: None,
        expected_parent_id: None,
    }
}
async fn recheck(
    s: &mut Session<'_>,
    op: Uuid,
    row: &sqlx::postgres::PgRow,
    file: bool,
) -> Result<(), ApiError> {
    let actor: Uuid = sqlx::query_scalar("SELECT actor_id FROM operations WHERE id=$1")
        .bind(op)
        .fetch_one(&mut *s.tx)
        .await?;
    let scope = paths::Scope {
        actor_id: actor,
        mounts: vec![paths::Mount {
            path: "/".into(),
            filesystem_id: s.fs,
        }],
    };
    let current = s
        .resolve(&scope, &id_locator(row.get("source_id")))
        .await
        .map_err(|e| {
            if e.0 == axum::http::StatusCode::NOT_FOUND {
                ApiError::state("SOURCE_CHANGED")
            } else {
                e
            }
        })?;
    if current.parent_id != row.get::<Option<Uuid>, _>("source_parent_id")
        || current.name != row.get::<String, _>("source_name")
        || current.kind != row.get::<String, _>("kind")
        || (file && current.revision != row.get::<i64, _>("source_revision").to_string())
    {
        return Err(ApiError::state("SOURCE_CHANGED"));
    }
    Ok(())
}
pub async fn batch(app: &App, op: Uuid) -> Result<bool, ApiError> {
    let mut s = scope_session(app, op, false).await?;
    let operation = sqlx::query("SELECT state,deadline FROM operations WHERE id=$1 FOR UPDATE")
        .bind(op)
        .fetch_one(&mut *s.tx)
        .await?;
    match operation.get::<String, _>("state").as_str() {
        "succeeded" => return Ok(true),
        "running" => {}
        _ => return Err(ApiError::state("COPY_NOT_RUNNING")),
    }
    if operation.get::<chrono::DateTime<chrono::Utc>, _>("deadline") <= chrono::Utc::now() {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    let item=sqlx::query("SELECT * FROM copy_items WHERE operation_id=$1 AND state!='ready' ORDER BY source_id LIMIT 1 FOR UPDATE").bind(op).fetch_optional(&mut *s.tx).await?;
    let Some(item) = item else { return Ok(true) };
    let source: Uuid = item.get("source_id");
    let destination: Uuid = item.get("destination_id");
    let state: String = item.get("state");
    let file = item.get::<String, _>("kind") == "file";
    recheck(&mut s, op, &item, file || state != "enumerating").await?;
    if state == "unopened" || state == "enumerating" {
        let snapshot = item.get::<Vec<Uuid>, _>("file_child_ids");
        let upper = if state == "unopened" {
            let upper: Option<Uuid> = if file {
                snapshot.last().copied()
            } else {
                sqlx::query_scalar(
                "SELECT id FROM nodes WHERE filesystem_id=$1 AND parent_id=$2 ORDER BY id DESC LIMIT 1",
            )
            .bind(s.fs)
            .bind(source)
            .fetch_optional(&mut *s.tx)
            .await?
            };
            sqlx::query("UPDATE copy_items SET upper_child_id=$3,state='enumerating' WHERE operation_id=$1 AND source_id=$2").bind(op).bind(source).bind(upper).execute(&mut *s.tx).await?;
            upper
        } else {
            item.get("upper_child_id")
        };
        let children=sqlx::query("SELECT id FROM nodes WHERE filesystem_id=$1 AND parent_id=$2 AND id>$3 AND id<=$4 AND (NOT $5 OR id=ANY($6)) ORDER BY id LIMIT 64").bind(s.fs).bind(source).bind(item.get::<Uuid,_>("last_child_id")).bind(upper).bind(file).bind(&snapshot).fetch_all(&mut *s.tx).await?;
        let depth: i32 = item.get("depth");
        if !children.is_empty() && depth >= 128 {
            return Err(ApiError::state("RESOURCE_LIMIT"));
        }
        let additions=children.iter().map(|r|json!({"source":r.get::<Uuid,_>("id"),"destination":Uuid::now_v7(),"parent":destination,"depth":depth+1})).collect();
        add_items(&mut s, op, additions).await?;
        if let Some(last) = children.last() {
            sqlx::query(
                "UPDATE copy_items SET last_child_id=$3 WHERE operation_id=$1 AND source_id=$2",
            )
            .bind(op)
            .bind(source)
            .bind(last.get::<Uuid, _>("id"))
            .execute(&mut *s.tx)
            .await?;
        }
        if children.len() < 64 {
            sqlx::query(
                "UPDATE copy_items SET state=CASE WHEN target_key IS NOT NULL THEN 'pending' ELSE 'ready' END WHERE operation_id=$1 AND source_id=$2",
            )
            .bind(op)
            .bind(source)
            .execute(&mut *s.tx)
            .await?;
        }
        s.tx.commit().await?;
        return Ok(false);
    }
    let from: String = item.get("source_key");
    let to: String = item.get("target_key");
    s.tx.commit().await?;
    use object_store::ObjectStoreExt;
    tokio::time::timeout(
        std::time::Duration::from_secs(120),
        app.storage.copy(
            &object_store::path::Path::from(from.clone()),
            &object_store::path::Path::from(to),
        ),
    )
    .await
    .map_err(|_| {
        ApiError(
            axum::http::StatusCode::SERVICE_UNAVAILABLE,
            "DEPENDENCY_UNAVAILABLE",
            "object copy timed out",
        )
    })?
    .map_err(crate::storage::error)?;
    let mut s = scope_session(app, op, false).await?;
    let state: String = sqlx::query_scalar("SELECT state FROM operations WHERE id=$1 FOR UPDATE")
        .bind(op)
        .fetch_one(&mut *s.tx)
        .await?;
    if state == "succeeded" {
        return Ok(true);
    }
    if state != "running" {
        return Err(ApiError::state("COPY_NOT_RUNNING"));
    }
    recheck(&mut s, op, &item, true).await?;
    let current: Option<String> =
        sqlx::query_scalar("SELECT object_key FROM file_data WHERE node_id=$1")
            .bind(source)
            .fetch_one(&mut *s.tx)
            .await?;
    if current.as_deref() != Some(&from) {
        return Err(ApiError::state("SOURCE_CHANGED"));
    }
    sqlx::query("UPDATE copy_items SET state='ready' WHERE operation_id=$1 AND source_id=$2 AND state='pending'").bind(op).bind(source).execute(&mut *s.tx).await?;
    s.tx.commit().await?;
    Ok(false)
}
pub async fn publish(app: &App, op: Uuid) -> Result<(), ApiError> {
    let mut s = scope_session(app, op, false).await?;
    let row = sqlx::query("SELECT * FROM operations WHERE id=$1 FOR UPDATE")
        .bind(op)
        .fetch_one(&mut *s.tx)
        .await?;
    if row.get::<String, _>("state") == "succeeded" {
        s.tx.commit().await?;
        return dispatch_processing(app, op).await;
    }
    if row.get::<String, _>("state") != "running" {
        return Err(ApiError::state("COPY_NOT_RUNNING"));
    }
    if row.get::<chrono::DateTime<chrono::Utc>, _>("deadline") <= chrono::Utc::now() {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    let pending: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM copy_items WHERE operation_id=$1 AND state!='ready')",
    )
    .bind(op)
    .fetch_one(&mut *s.tx)
    .await?;
    if pending {
        return Err(ApiError::state("COPY_INCOMPLETE"));
    }
    let parent: Uuid = row.get("destination_parent_id");
    let root: Uuid = row.get("staging_root_id");
    let source: Uuid = row.get("source_id");
    let scope = paths::Scope {
        actor_id: row.get("actor_id"),
        mounts: vec![paths::Mount {
            path: "/".into(),
            filesystem_id: s.fs,
        }],
    };
    let p = s.resolve(&scope, &id_locator(parent)).await?;
    p.writable()?;
    p.directory()?;
    s.name(parent, &row.get::<String, _>("destination_name"))?;
    cycle(&mut s.tx, s.fs, source, parent).await?;
    if depth(&mut s.tx, s.fs, parent).await? + 1 + subtree_height(&mut s.tx, s.fs, root).await?
        > 128
    {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    s.usage(row.get("total_bytes")).await?;
    sqlx::query("UPDATE nodes SET parent_id=$2 WHERE id=$1")
        .bind(root)
        .bind(parent)
        .execute(&mut *s.tx)
        .await?;
    bump(&mut s.tx, &[parent]).await?;
    sqlx::query("UPDATE operations SET state='succeeded',result_node_id=staging_root_id,updated_at=now() WHERE id=$1").bind(op).execute(&mut *s.tx).await?;
    let roots:Vec<sqlx::postgres::PgRow>=sqlx::query("WITH RECURSIVE tree AS (SELECT id,parent_id FROM nodes WHERE id=$1 UNION ALL SELECT n.id,n.parent_id FROM nodes n JOIN tree t ON n.parent_id=t.id) SELECT n.*,d.object_key,d.inline_bytes FROM tree t JOIN nodes n ON n.id=t.id JOIN file_data d ON d.node_id=n.id WHERE NOT EXISTS(SELECT 1 FROM tree p JOIN file_data pd ON pd.node_id=p.id WHERE p.id=n.parent_id)").bind(root).fetch_all(&mut *s.tx).await?;
    for source in roots {
        use sha2::{Digest, Sha256};
        let n = Node::from_row(&source);
        let object: Option<String> = source.get("object_key");
        let digest = source
            .get::<Option<Vec<u8>>, _>("inline_bytes")
            .map(|b| format!("{:x}", Sha256::digest(b)));
        if let Some(intent) = super::artifacts::record_intent(
            &mut s,
            &n,
            row.get("actor_id"),
            Uuid::now_v7(),
            object.as_deref(),
            digest.as_deref(),
        )
        .await?
            && super::artifacts::has_children(&mut s, n.id).await?
        {
            sqlx::query("UPDATE operations SET state='succeeded',result_node_id=$2 WHERE id=$1")
                .bind(intent)
                .bind(n.id)
                .execute(&mut *s.tx)
                .await?;
        }
    }
    s.tx.commit().await?;
    dispatch_processing(app, op).await
}

async fn dispatch_processing(app: &App, copy: Uuid) -> Result<(), ApiError> {
    use futures::{StreamExt, TryStreamExt};
    let ids: Vec<Uuid> = sqlx::query_scalar("SELECT o.id FROM operations o JOIN nodes n ON n.id=o.source_id WHERE n.staging_operation_id=$1 AND o.kind='process-file' AND o.superseded_at IS NULL AND o.workflow_started_at IS NULL AND o.index_state!='succeeded' ORDER BY o.id")
        .bind(copy).fetch_all(&app.pool).await?;
    futures::stream::iter(
        ids.into_iter().map(|op| async move {
            crate::temporal::process_file_workflow::dispatch(app, op).await
        }),
    )
    .buffer_unordered(8)
    .try_collect::<Vec<_>>()
    .await?;
    Ok(())
}
pub async fn mark_discarding(app: &App, op: Uuid, code: &str) -> Result<(), ApiError> {
    let mut s = scope_session(app, op, true).await?;
    sqlx::query("UPDATE operations SET state='discarding',error_code=$2,updated_at=now() WHERE id=$1 AND state='running'").bind(op).bind(code).execute(&mut *s.tx).await?;
    s.tx.commit().await?;
    Ok(())
}
pub async fn discard_batch(app: &App, op: Uuid) -> Result<bool, ApiError> {
    let mut s = scope_session(app, op, true).await?;
    let state: String = sqlx::query_scalar("SELECT state FROM operations WHERE id=$1 FOR UPDATE")
        .bind(op)
        .fetch_one(&mut *s.tx)
        .await?;
    if state == "succeeded" || state == "failed" {
        return Ok(true);
    }
    if state != "discarding" {
        return Err(ApiError::state("COPY_NOT_DISCARDING"));
    }
    let ids:Vec<Uuid>=sqlx::query_scalar("SELECT n.id FROM nodes n WHERE staging_operation_id=$1 AND NOT EXISTS(SELECT 1 FROM nodes c WHERE c.parent_id=n.id AND c.filesystem_id=n.filesystem_id) ORDER BY n.id LIMIT 64").bind(op).fetch_all(&mut *s.tx).await?;
    super::deletion::remove(&mut s, &ids).await?;
    let remaining: bool =
        sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM nodes WHERE staging_operation_id=$1)")
            .bind(op)
            .fetch_one(&mut *s.tx)
            .await?;
    if !remaining {
        sqlx::query("UPDATE operations SET state='failed',updated_at=now() WHERE id=$1 AND state='discarding'").bind(op).execute(&mut *s.tx).await?;
    }
    s.tx.commit().await?;
    Ok(!remaining)
}

pub async fn preflight(app: &App, start: &Start) -> Result<(), ApiError> {
    let r = &start.request;
    let fs = start.filesystem_id;
    let source = r
        .input
        .locator
        .as_ref()
        .ok_or_else(|| ApiError::bad("source required"))?;
    let parent = r
        .input
        .parent
        .as_ref()
        .ok_or_else(|| ApiError::bad("parent required"))?;
    super::validate_name(
        r.input
            .name
            .as_deref()
            .ok_or_else(|| ApiError::bad("name required"))?,
    )?;
    let mut s = session(app, fs, false).await?;
    let nodes = paths::resolve(
        &mut s.tx,
        fs,
        s.root,
        &r.scope,
        &[source.clone(), parent.clone()],
    )
    .await?;
    paths::guard(source, nodes[0].id, false)?;
    nodes[0].revision(r.input.revision.as_deref())?;
    paths::guard(parent, nodes[1].id, true)?;
    nodes[1].writable()?;
    nodes[1].directory()?;
    s.name(
        nodes[1].id,
        r.input
            .name
            .as_deref()
            .ok_or_else(|| ApiError::bad("name required"))?,
    )?;
    cycle(&mut s.tx, fs, nodes[0].id, nodes[1].id).await?;
    Ok(())
}
