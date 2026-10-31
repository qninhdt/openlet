use super::{nodes::*, paths};
use crate::http::{ApiError, App};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use sqlx::Row;
use uuid::Uuid;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Input {
    pub source_id: Uuid,
    pub parent_id: Uuid,
    pub name: String,
    pub revision: String,
    pub request_key: Uuid,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub scope: paths::Scope,
    pub input: Input,
}
// Selections contain identities, never object or inline bytes.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Item {
    pub source: Uuid,
    pub source_parent: Option<Uuid>,
    pub source_name: String,
    pub revision: String,
    pub kind: String,
    pub size: i64,
    pub object_key: Option<String>,
    pub inline_sha256: Option<String>,
    pub upper: Option<Uuid>,
    pub destination: Uuid,
    pub parent: Uuid,
    pub parent_revision: String,
    pub name: String,
    pub derived: bool,
    pub depth: i64,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Admission {
    pub id: Uuid,
    pub filesystem_id: Uuid,
    pub actor_id: Uuid,
    pub root: Item,
    pub max_nodes: i64,
    pub max_bytes: i64,
    pub deadline: chrono::DateTime<chrono::Utc>,
}
impl Admission {
    pub fn workflow_id(&self) -> String {
        format!("copy/{}/{}", self.filesystem_id, self.id)
    }
    pub fn value(&self) -> serde_json::Value {
        serde_json::json!({"id":self.id,"destination_root_id":self.root.destination,"status":"accepted","committed_nodes":"0","committed_bytes":"0","error_code":null})
    }
}
pub fn destination(copy: Uuid, source: Uuid) -> Uuid {
    let mut hash = Sha256::new();
    hash.update(b"openlet-copy-node");
    hash.update(copy.as_bytes());
    hash.update(source.as_bytes());
    let digest = hash.finalize();
    let mut bytes = [0; 16];
    bytes.copy_from_slice(&digest[..16]);
    uuid::Builder::from_custom_bytes(bytes).into_uuid()
}
fn locator(id: Uuid) -> paths::Locator {
    paths::Locator {
        node_id: Some(id),
        path: None,
        cwd_id: None,
        expected_node_id: None,
        expected_parent_id: None,
    }
}
fn scope(admission: &Admission) -> paths::Scope {
    paths::Scope {
        actor_id: admission.actor_id,
        mounts: vec![paths::Mount {
            path: "/".into(),
            filesystem_id: admission.filesystem_id,
        }],
    }
}
async fn select(
    s: &mut Session<'_>,
    copy: Uuid,
    n: Node,
    parent: &Node,
    name: String,
    derived: bool,
    depth: i64,
) -> Result<Item, ApiError> {
    let payload = sqlx::query("SELECT object_key,inline_bytes FROM files WHERE node_id=$1")
        .bind(n.id)
        .fetch_optional(&mut *s.tx)
        .await?;
    let object_key = payload.as_ref().and_then(|row| row.get("object_key"));
    let inline_sha256 = payload
        .and_then(|row| row.get::<Option<Vec<u8>>, _>("inline_bytes"))
        .map(|bytes| format!("{:x}", Sha256::digest(bytes)));
    let upper = sqlx::query_scalar(
        "SELECT id FROM nodes WHERE filesystem_id=$1 AND parent_id=$2 ORDER BY id DESC LIMIT 1",
    )
    .bind(s.fs)
    .bind(n.id)
    .fetch_optional(&mut *s.tx)
    .await?;
    Ok(Item {
        source: n.id,
        source_parent: n.parent_id,
        source_name: n.name,
        revision: n.revision,
        kind: n.kind,
        size: n
            .size_bytes
            .parse()
            .map_err(|_| ApiError::state("RESOURCE_LIMIT"))?,
        object_key,
        inline_sha256,
        upper,
        destination: destination(copy, n.id),
        parent: parent.id,
        parent_revision: parent.revision.clone(),
        name,
        derived,
        depth,
    })
}
pub async fn admit(app: &App, fs: Uuid, request: Request) -> Result<Admission, ApiError> {
    paths::validate_scope(fs, &request.scope)?;
    let input = &request.input;
    if input.request_key.is_nil() || input.source_id.is_nil() || input.parent_id.is_nil() {
        return Err(ApiError::bad("copy identities required"));
    }
    super::validate_name(&input.name)?;
    let hash = format!(
        "{:x}",
        Sha256::digest(serde_json::to_vec(input).map_err(|_| ApiError::bad("invalid copy"))?)
    );
    let receipt_scope = format!("filesystem/{fs}/actor/{}", request.scope.actor_id);
    let mut s = session(app, fs, true).await?;
    if let Some(prior) = sqlx::query("SELECT request_hash,result FROM idempotency_keys WHERE scope=$1 AND operation='copy-node' AND request_key=$2 AND (expires_at IS NULL OR expires_at>now())")
        .bind(&receipt_scope).bind(input.request_key.to_string()).fetch_optional(&mut *s.tx).await? {
        if prior.get::<String,_>("request_hash") != hash { return Err(ApiError::state("IDEMPOTENCY_CONFLICT")); }
        return serde_json::from_value(prior.get("result")).map_err(|_| ApiError::conflict());
    }
    super::uploads::capacity(&mut s, app).await?;
    let source = s.resolve(&request.scope, &locator(input.source_id)).await?;
    source.revision(Some(&input.revision))?;
    let parent = s.resolve(&request.scope, &locator(input.parent_id)).await?;
    parent.writable()?;
    parent.directory()?;
    s.name(parent.id, &input.name)?;
    cycle(&mut s.tx, fs, source.id, parent.id).await?;
    vacant(&mut s, parent.id, &input.name).await?;
    let depth = super::nodes::depth(&mut s.tx, fs, parent.id).await? + 1;
    if depth > 128 {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    let id = Uuid::now_v7();
    let root = select(
        &mut s,
        id,
        source,
        &parent,
        input.name.clone(),
        false,
        depth,
    )
    .await?;
    let max_bytes = sqlx::query_scalar("SELECT limit_bytes FROM quota_buckets WHERE id=$1")
        .bind(s.bucket)
        .fetch_one(&mut *s.tx)
        .await?;
    let admission = Admission {
        id,
        filesystem_id: fs,
        actor_id: request.scope.actor_id,
        root,
        max_nodes: app.config.max_copy_nodes,
        max_bytes,
        deadline: chrono::Utc::now() + chrono::Duration::hours(1),
    };
    sqlx::query("INSERT INTO idempotency_keys(scope,operation,request_key,request_hash,result) VALUES($1,'copy-node',$2,$3,$4) ON CONFLICT(scope,operation,request_key) DO UPDATE SET request_hash=excluded.request_hash,result=excluded.result,completed_at=NULL,expires_at=NULL WHERE idempotency_keys.expires_at<=now()")
        .bind(receipt_scope).bind(input.request_key.to_string()).bind(hash).bind(serde_json::json!(admission)).execute(&mut *s.tx).await?;
    s.tx.commit().await?;
    Ok(admission)
}
async fn vacant(s: &mut Session<'_>, parent: Uuid, name: &str) -> Result<(), ApiError> {
    let occupied: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM nodes WHERE filesystem_id=$1 AND parent_id=$2 AND name=$3)",
    )
    .bind(s.fs)
    .bind(parent)
    .bind(name)
    .fetch_one(&mut *s.tx)
    .await?;
    if occupied {
        return Err(ApiError::state("NAME_CONFLICT"));
    }
    Ok(())
}
async fn source(
    s: &mut Session<'_>,
    admission: &Admission,
    item: &Item,
    exact: bool,
) -> Result<Node, ApiError> {
    let n = s
        .resolve(&scope(admission), &locator(item.source))
        .await
        .map_err(|e| {
            if e.0 == axum::http::StatusCode::NOT_FOUND {
                ApiError::state("SOURCE_REPLACED")
            } else {
                e
            }
        })?;
    if n.parent_id != item.source_parent
        || n.name != item.source_name
        || n.kind != item.kind
        || ((exact || n.kind == "file") && n.revision != item.revision)
    {
        return Err(ApiError::state("SOURCE_REPLACED"));
    }
    if n.kind == "file" {
        let payload = sqlx::query("SELECT object_key,inline_bytes FROM files WHERE node_id=$1")
            .bind(n.id)
            .fetch_one(&mut *s.tx)
            .await?;
        let digest = payload
            .get::<Option<Vec<u8>>, _>("inline_bytes")
            .map(|bytes| format!("{:x}", Sha256::digest(bytes)));
        if payload.get::<Option<String>, _>("object_key") != item.object_key
            || digest != item.inline_sha256
            || n.size_bytes != item.size.to_string()
        {
            return Err(ApiError::state("SOURCE_REPLACED"));
        }
    }
    Ok(n)
}
fn deadline(admission: &Admission) -> Result<(), ApiError> {
    if chrono::Utc::now() >= admission.deadline {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    Ok(())
}
fn candidate(bucket: Uuid, item: &Item) -> String {
    format!("objects/{bucket}/{}", item.destination)
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Step {
    pub admission: Admission,
    pub item: Item,
}
// Recognition precedes source validation: a lost acknowledgment still recognizes its committed effect.
async fn committed(
    s: &mut Session<'_>,
    admission: &Admission,
    item: &Item,
) -> Result<bool, ApiError> {
    let parent = s.resolve(&scope(admission), &locator(item.parent)).await?;
    cycle(&mut s.tx, s.fs, admission.root.source, parent.id).await?;
    if depth(&mut s.tx, s.fs, parent.id).await? >= 128 {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    let existing = sqlx::query("SELECT n.*,f.object_key,f.media_type,f.title,f.description,f.semantic_type,f.context FROM nodes n LEFT JOIN files f ON f.node_id=n.id WHERE n.id=$1 AND n.filesystem_id=$2")
        .bind(item.destination).bind(s.fs).fetch_optional(&mut *s.tx).await?;
    if let Some(row) = existing {
        let n = Node::from_row(&row);
        let expected = item
            .parent_revision
            .parse::<i64>()
            .map_err(|_| ApiError::conflict())?
            + 1;
        if n.parent_id != Some(item.parent)
            || n.name != item.name
            || n.kind != item.kind
            || n.revision != "1"
            || n.size_bytes != item.size.to_string()
            || parent.revision != expected.to_string()
        {
            return Err(ApiError::state("DESTINATION_CHANGED"));
        }
        return Ok(true);
    }
    if parent.revision != item.parent_revision {
        return Err(ApiError::state("DESTINATION_CHANGED"));
    }
    if !item.derived {
        parent.writable()?;
        parent.directory()?;
    }
    vacant(s, item.parent, &item.name).await?;
    Ok(false)
}
async fn active(s: &mut Session<'_>, admission: &Admission) -> Result<(), ApiError> {
    let active:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM idempotency_keys WHERE operation='copy-node' AND result->>'id'=$1 AND completed_at IS NULL)").bind(admission.id.to_string()).fetch_one(&mut *s.tx).await?;
    if !active {
        return Err(ApiError::state("COPY_CLOSED"));
    }
    Ok(())
}
async fn release_candidate(s: &mut Session<'_>, key: &str) -> Result<(), ApiError> {
    sqlx::query("DELETE FROM object_deletions d WHERE object_key=$1 AND open_writes=0 AND NOT ambiguous_write AND attempts=0 AND EXISTS(SELECT 1 FROM files f WHERE f.object_key=d.object_key)").bind(key).execute(&mut *s.tx).await?;
    Ok(())
}
pub async fn commit_item(app: &App, step: Step) -> Result<(), ApiError> {
    let Step { admission, item } = step;
    deadline(&admission)?;
    let mut s = session(app, admission.filesystem_id, true).await?;
    if committed(&mut s, &admission, &item).await? {
        return Ok(());
    }
    active(&mut s, &admission).await?;
    source(&mut s, &admission, &item, true).await?;
    let key = item.object_key.as_ref().map(|_| candidate(s.bucket, &item));
    if let Some(key) = &key {
        // Each unresolved backend request remains counted, including after process death.
        let registered=sqlx::query("INSERT INTO object_deletions(object_key,bucket_id,open_writes) VALUES($1,$2,1) ON CONFLICT(object_key) DO UPDATE SET open_writes=object_deletions.open_writes+1,state='pending',eligible_at=now()+interval '15 minutes' WHERE object_deletions.attempts=0")
            .bind(key).bind(s.bucket).execute(&mut *s.tx).await?.rows_affected();
        if registered != 1 {
            return Err(ApiError::state("COPY_CANDIDATE_CLOSED"));
        }
        s.tx.commit().await?;
        use object_store::ObjectStoreExt;
        tokio::time::timeout(
            std::time::Duration::from_secs(120),
            app.storage.copy(
                &object_store::path::Path::from(item.object_key.clone().unwrap()),
                &object_store::path::Path::from(key.clone()),
            ),
        )
        .await
        .map_err(|_| {
            ApiError(
                axum::http::StatusCode::SERVICE_UNAVAILABLE,
                "DEPENDENCY_UNAVAILABLE",
                "copy timed out",
            )
        })?
        .map_err(crate::storage::error)?;
        s = lifecycle_session(app, admission.filesystem_id).await?;
        sqlx::query("UPDATE object_deletions SET open_writes=open_writes-1 WHERE object_key=$1 AND open_writes>0").bind(key).execute(&mut *s.tx).await?;
        let valid = async {
            deadline(&admission)?;
            active(&mut s,&admission).await?;
            let active: bool = sqlx::query_scalar("SELECT f.state='active' AND b.state='active' FROM filesystems f JOIN quota_buckets b ON b.id=f.bucket_id WHERE f.id=$1").bind(s.fs).fetch_one(&mut *s.tx).await?;
            if !active { return Err(ApiError::state("FILESYSTEM_DELETING")); }
            let attempted:bool=sqlx::query_scalar("SELECT attempts>0 FROM object_deletions WHERE object_key=$1").bind(key).fetch_one(&mut *s.tx).await?;
            if attempted {return Err(ApiError::state("COPY_CANDIDATE_CLOSED"));}
            let done = committed(&mut s,&admission,&item).await?;
            if !done { source(&mut s,&admission,&item,true).await?; }
            Ok(done)
        }.await;
        match valid {
            Ok(true) => {
                release_candidate(&mut s, key).await?;
                s.tx.commit().await?;
                return Ok(());
            }
            Ok(false) => {}
            Err(e) => {
                s.tx.commit().await?;
                return Err(e);
            }
        }
    }
    sqlx::query("SAVEPOINT copy_publication")
        .execute(&mut *s.tx)
        .await?;
    let published:Result<(),ApiError>=async {
    s.add_nodes(1).await?;
    s.usage(item.size).await?;
    sqlx::query("INSERT INTO nodes(id,filesystem_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,$4,$5,$6)")
        .bind(item.destination).bind(s.fs).bind(item.parent).bind(&item.name).bind(&item.kind).bind(item.size).execute(&mut *s.tx).await?;
    if item.kind == "file" {
        sqlx::query("INSERT INTO files(node_id,storage_kind,inline_bytes,object_key,media_type,title,description,semantic_type,context) SELECT $1,storage_kind,inline_bytes,$3,media_type,title,description,semantic_type,context FROM files WHERE node_id=$2")
            .bind(item.destination).bind(item.source).bind(&key).execute(&mut *s.tx).await?;
    }
    bump(&mut s.tx, &[item.parent]).await?;
        Ok(())
    }.await;
    if published.is_err() {
        sqlx::query("ROLLBACK TO SAVEPOINT copy_publication")
            .execute(&mut *s.tx)
            .await?;
    }

    if let Some(key) = &key {
        release_candidate(&mut s, key).await?;
    }
    s.tx.commit().await?;
    published
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Frame {
    pub item: Item,
    pub after: Uuid,
    pub revision: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Next {
    pub admission: Admission,
    pub frame: Frame,
}
async fn frame_nodes(
    s: &mut Session<'_>,
    admission: &Admission,
    frame: &Frame,
) -> Result<Node, ApiError> {
    source(s, admission, &frame.item, false).await?;
    let n = s
        .resolve(&scope(admission), &locator(frame.item.destination))
        .await?;
    if n.parent_id != Some(frame.item.parent)
        || n.name != frame.item.name
        || n.kind != frame.item.kind
        || n.revision != frame.revision
    {
        return Err(ApiError::state("DESTINATION_CHANGED"));
    }
    Ok(n)
}
pub async fn next(app: &App, input: Next) -> Result<Option<Item>, ApiError> {
    let Next { admission, frame } = input;
    deadline(&admission)?;
    let mut s = session(app, admission.filesystem_id, false).await?;
    let parent = frame_nodes(&mut s, &admission, &frame).await?;
    let child: Option<Uuid> = sqlx::query_scalar("SELECT id FROM nodes WHERE filesystem_id=$1 AND parent_id=$2 AND id>$3 AND id<=$4 ORDER BY id LIMIT 1")
        .bind(s.fs).bind(frame.item.source).bind(frame.after).bind(frame.item.upper).fetch_optional(&mut *s.tx).await?;
    let Some(child) = child else {
        return Ok(None);
    };
    if frame.item.depth >= 128 {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    let n = s.resolve(&scope(&admission), &locator(child)).await?;
    let name = n.name.clone();
    Ok(Some(
        select(
            &mut s,
            admission.id,
            n,
            &parent,
            name,
            frame.item.derived || frame.item.kind == "file",
            frame.item.depth + 1,
        )
        .await?,
    ))
}
pub async fn finish_file(app: &App, input: Next) -> Result<(), ApiError> {
    let Next { admission, frame } = input;
    if frame.item.kind != "file" || frame.item.derived {
        return Ok(());
    }
    let mut s = session(app, admission.filesystem_id, true).await?;
    let n = frame_nodes(&mut s, &admission, &frame).await?;
    let initialized: bool =
        sqlx::query_scalar("SELECT desired_generation>0 FROM files WHERE node_id=$1")
            .bind(n.id)
            .fetch_one(&mut *s.tx)
            .await?;
    if !initialized {
        let row = sqlx::query("SELECT object_key,inline_bytes FROM files WHERE node_id=$1")
            .bind(n.id)
            .fetch_one(&mut *s.tx)
            .await?;
        let object: Option<String> = row.get("object_key");
        let digest = row
            .get::<Option<Vec<u8>>, _>("inline_bytes")
            .map(|b| format!("{:x}", Sha256::digest(b)));
        if let Some(intent) = super::artifacts::record_intent(
            &mut s,
            &n,
            admission.actor_id,
            object.as_deref(),
            digest.as_deref(),
        )
        .await?
        {
            let children = sqlx::query(
                "SELECT id,name,kind FROM nodes WHERE parent_id=$1 ORDER BY id LIMIT 2",
            )
            .bind(n.id)
            .fetch_all(&mut *s.tx)
            .await?;
            if !children.is_empty() {
                if children.len() != 1
                    || children[0].get::<&str, _>("name") != "artifacts"
                    || children[0].get::<&str, _>("kind") != "directory"
                {
                    return Err(ApiError::state("INVALID_ARTIFACT_ROOT"));
                }
                sqlx::query("UPDATE files SET publication_status='parsed',artifact_root_id=$2 WHERE node_id=$1 AND desired_generation=$3").bind(n.id).bind(children[0].get::<Uuid,_>("id")).bind(intent.generation).execute(&mut *s.tx).await?;
            }
        }
    }
    s.tx.commit().await?;
    super::artifacts::dispatch_pending(app, n.id).await;
    Ok(())
}
pub async fn complete(app: &App, admission: &Admission) -> Result<(), ApiError> {
    let mut s = lifecycle_session(app, admission.filesystem_id).await?;
    sqlx::query("UPDATE idempotency_keys SET completed_at=now(),expires_at=now()+interval '24 hours' WHERE operation='copy-node' AND result->>'id'=$1 AND completed_at IS NULL")
        .bind(admission.id.to_string()).execute(&mut *s.tx).await?;
    s.tx.commit().await?;
    Ok(())
}
