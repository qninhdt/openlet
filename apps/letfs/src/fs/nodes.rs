use super::paths::{self, Locator, Scope};
use crate::{
    fs::validate_name,
    http::{ApiError, App},
};
use axum::http::StatusCode;
use base64::{Engine, prelude::BASE64_STANDARD};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{PgConnection, Postgres, Row, Transaction, postgres::PgRow};
use uuid::Uuid;

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Node {
    pub id: Uuid,
    pub filesystem_id: Uuid,
    pub parent_id: Option<Uuid>,
    pub name: String,
    pub kind: String,
    pub size_bytes: String,
    pub revision: String,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub updated_at: chrono::DateTime<chrono::Utc>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub media_type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub semantic_type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub context: Option<String>,
    #[serde(skip)]
    pub readonly: bool,
}
impl Node {
    pub fn from_row(r: &PgRow) -> Self {
        Self {
            id: r.get("id"),
            filesystem_id: r.get("filesystem_id"),
            parent_id: r.get("parent_id"),
            name: r.get("name"),
            kind: r.get("kind"),
            size_bytes: r.get::<i64, _>("size_bytes").to_string(),
            revision: r.get::<i64, _>("revision").to_string(),
            created_at: r.get("created_at"),
            updated_at: r.get("updated_at"),
            media_type: r.get("media_type"),
            title: r.get("title"),
            description: r.get("description"),
            semantic_type: r.get("semantic_type"),
            context: r.get("context"),
            readonly: match r.try_get("artifact_readonly") {
                Ok(value) => value,
                Err(sqlx::Error::ColumnNotFound(_)) => false,
                Err(error) => panic!("invalid artifact provenance: {error}"),
            },
        }
    }
    pub fn writable(&self) -> Result<(), ApiError> {
        if self.readonly {
            return Err(ApiError(
                StatusCode::FORBIDDEN,
                "ARTIFACT_READ_ONLY",
                "generated artifacts are read only",
            ));
        }
        Ok(())
    }
    pub fn directory(&self) -> Result<(), ApiError> {
        if self.kind != "directory" {
            return Err(ApiError::state("NOT_DIRECTORY"));
        }
        Ok(())
    }
    pub fn revision(&self, expected: Option<&str>) -> Result<(), ApiError> {
        match expected {
            None => Err(ApiError::precondition_required()),
            Some(v) if v != self.revision => Err(ApiError::revision_mismatch()),
            _ => Ok(()),
        }
    }
}
#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Input {
    pub locator: Option<Locator>,
    pub parent: Option<Locator>,
    pub name: Option<String>,
    #[serde(skip)]
    pub content: Option<Vec<u8>>,
    pub media_type: Option<String>,
    pub revision: Option<String>,
    pub request_key: Option<Uuid>,
    pub entry_id: Option<Uuid>,
    pub cursor: Option<String>,
    pub limit: Option<usize>,
    pub locators: Option<Vec<Locator>>,
    pub storage: Option<super::uploads::StorageMode>,
    pub size_bytes: Option<String>,
    pub content_md5: Option<String>,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub scope: Scope,
    pub input: Input,
}
pub struct Session<'a> {
    pub tx: Transaction<'a, Postgres>,
    pub fs: Uuid,
    pub bucket: Uuid,
    pub root: Uuid,
}
impl Session<'_> {
    pub fn name(&self, parent: Uuid, name: &str) -> Result<(), ApiError> {
        validate_name(name)?;
        if parent == self.root && paths::node_alias(name).is_some() {
            return Err(ApiError::bad("root UUID alias names are reserved"));
        }
        Ok(())
    }
    pub async fn resolve(&mut self, s: &Scope, l: &Locator) -> Result<Node, ApiError> {
        Ok(
            paths::resolve(&mut self.tx, self.fs, self.root, s, std::slice::from_ref(l))
                .await?
                .remove(0),
        )
    }
    pub async fn add_nodes(&mut self, count: i64) -> Result<(), ApiError> {
        let changed=sqlx::query("UPDATE filesystems SET node_count=node_count+$2 WHERE id=$1 AND node_count+$2 BETWEEN CASE WHEN state='deleting' THEN 0 ELSE 1 END AND max_nodes").bind(self.fs).bind(count).execute(&mut *self.tx).await?.rows_affected();
        if changed != 1 {
            return Err(ApiError::state("RESOURCE_LIMIT"));
        }
        Ok(())
    }
    pub async fn usage(&mut self, delta: i64) -> Result<(), ApiError> {
        let changed=sqlx::query("UPDATE quota_buckets SET used_bytes=used_bytes+$2 WHERE id=$1 AND used_bytes+$2>=0 AND ($2<=0 OR used_bytes<=(limit_bytes-$2)) AND (state='active' OR ($2<=0 AND state='frozen'))")
            .bind(self.bucket).bind(delta).execute(&mut *self.tx).await?.rows_affected();
        if changed != 1 {
            return Err(ApiError::state("QUOTA_EXCEEDED"));
        }
        Ok(())
    }
}
pub async fn session(app: &App, fs: Uuid, write: bool) -> Result<Session<'_>, ApiError> {
    open_session(app, fs, write, false).await
}
pub async fn lifecycle_session(app: &App, fs: Uuid) -> Result<Session<'_>, ApiError> {
    open_session(app, fs, true, true).await
}
async fn open_session(
    app: &App,
    fs: Uuid,
    write: bool,
    allow_inactive: bool,
) -> Result<Session<'_>, ApiError> {
    let mut tx = app.pool.begin().await?;
    if !write {
        sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            .execute(&mut *tx)
            .await?;
    }
    let bucket: Uuid = sqlx::query_scalar("SELECT bucket_id FROM filesystems WHERE id=$1")
        .bind(fs)
        .fetch_optional(&mut *tx)
        .await?
        .ok_or_else(ApiError::not_found)?;
    let state: String = sqlx::query_scalar(if write {
        "SELECT state FROM quota_buckets WHERE id=$1 FOR UPDATE"
    } else {
        "SELECT state FROM quota_buckets WHERE id=$1"
    })
    .bind(bucket)
    .fetch_one(&mut *tx)
    .await?;
    if !allow_inactive && state != "active" {
        return Err(ApiError::state("BUCKET_FROZEN"));
    }
    let r = sqlx::query(if write {
        "SELECT root_id,state FROM filesystems WHERE id=$1 FOR UPDATE"
    } else {
        "SELECT root_id,state FROM filesystems WHERE id=$1"
    })
    .bind(fs)
    .fetch_one(&mut *tx)
    .await?;
    if !allow_inactive && r.get::<String, _>("state") != "active" {
        return Err(ApiError::not_found());
    }
    Ok(Session {
        tx,
        fs,
        bucket,
        root: r.get::<Option<Uuid>, _>("root_id").unwrap_or(Uuid::nil()),
    })
}
pub fn needed<T>(v: Option<T>) -> Result<T, ApiError> {
    v.ok_or_else(|| ApiError::bad("missing required field"))
}
pub async fn bump(conn: &mut PgConnection, ids: &[Uuid]) -> Result<(), ApiError> {
    sqlx::query("UPDATE nodes SET revision=revision+1,updated_at=now() WHERE id=ANY($1)")
        .bind(ids)
        .execute(conn)
        .await?;
    Ok(())
}
pub async fn fetch(conn: &mut PgConnection, id: Uuid) -> Result<Node, ApiError> {
    Ok(Node::from_row(
        &sqlx::query("SELECT n.*,f.media_type,f.title,f.description,f.semantic_type,f.context FROM nodes n LEFT JOIN files f ON f.node_id=n.id WHERE n.id=$1")
            .bind(id)
            .fetch_one(conn)
            .await?,
    ))
}
pub async fn depth(conn: &mut PgConnection, fs: Uuid, id: Uuid) -> Result<i64, ApiError> {
    Ok(sqlx::query_scalar("WITH RECURSIVE a AS (SELECT id,parent_id,0 AS depth FROM nodes WHERE id=$1 AND filesystem_id=$2 UNION ALL SELECT n.id,n.parent_id,a.depth+1 FROM a JOIN nodes n ON n.id=a.parent_id AND n.filesystem_id=$2 WHERE a.depth<128) SELECT max(depth)::bigint FROM a").bind(id).bind(fs).fetch_one(conn).await?)
}
pub async fn subtree_height(conn: &mut PgConnection, fs: Uuid, id: Uuid) -> Result<i64, ApiError> {
    Ok(sqlx::query_scalar("WITH RECURSIVE a AS (SELECT id,0 AS depth FROM nodes WHERE id=$1 AND filesystem_id=$2 UNION ALL SELECT n.id,a.depth+1 FROM a JOIN nodes n ON n.parent_id=a.id AND n.filesystem_id=$2 WHERE a.depth<128) SELECT max(depth)::bigint FROM a").bind(id).bind(fs).fetch_one(conn).await?)
}
pub async fn cycle(
    conn: &mut PgConnection,
    fs: Uuid,
    source: Uuid,
    parent: Uuid,
) -> Result<(), ApiError> {
    let exists:bool=sqlx::query_scalar("WITH RECURSIVE a AS (SELECT id,parent_id,0 AS depth FROM nodes WHERE id=$1 AND filesystem_id=$2 UNION ALL SELECT n.id,n.parent_id,a.depth+1 FROM a JOIN nodes n ON n.id=a.parent_id AND n.filesystem_id=$2 WHERE a.depth<128) SELECT EXISTS(SELECT 1 FROM a WHERE id=$3)").bind(parent).bind(fs).bind(source).fetch_one(conn).await?;
    if exists {
        return Err(ApiError::state("CYCLE"));
    }
    Ok(())
}
pub fn page(input: &Input, scope: &str) -> Result<(Uuid, usize), ApiError> {
    let limit = input.limit.unwrap_or(50);
    if limit == 0 || limit > 100 {
        return Err(ApiError::bad("invalid limit"));
    }
    let id = match &input.cursor {
        None => Uuid::nil(),
        Some(v) => {
            let (prefix, last) = v
                .rsplit_once('|')
                .ok_or_else(|| ApiError::bad("invalid cursor"))?;
            if prefix != scope {
                return Err(ApiError::bad("cursor scope mismatch"));
            }
            Uuid::parse_str(last).map_err(|_| ApiError::bad("invalid cursor"))?
        }
    };
    Ok((id, limit))
}
pub fn paged<T: Serialize>(mut values: Vec<(Uuid, T)>, limit: usize, scope: &str) -> Value {
    let next = if values.len() > limit {
        values.truncate(limit);
        Some(format!("{}|{}", scope, values.last().unwrap().0))
    } else {
        None
    };
    json!({"items":values.into_iter().map(|(_,v)|v).collect::<Vec<_>>(),"next_cursor":next})
}
pub async fn read(app: &App, fs: Uuid, action: &str, r: Request) -> Result<Value, ApiError> {
    let mut s = session(app, fs, false).await?;
    if action == "batch-stat" {
        let locators = needed(r.input.locators)?;
        let out = paths::resolve(&mut s.tx, fs, s.root, &r.scope, &locators).await?;
        return Ok(json!({"items":out}));
    }
    let l = needed(r.input.locator.as_ref())?;
    let n = s.resolve(&r.scope, l).await?;
    if l.expected_node_id.is_some_and(|id| id != n.id) {
        return Err(ApiError::state("TARGET_MISMATCH"));
    }
    if action == "stat" {
        return Ok(json!(n));
    }
    if action != "list" {
        return Err(ApiError::not_found());
    }
    let scope = format!("list/{fs}/{}", n.id);
    let (after, limit) = page(&r.input, &scope)?;
    let rows=sqlx::query("SELECT n.*,f.media_type,f.title,f.description,f.semantic_type,f.context FROM nodes n LEFT JOIN files f ON f.node_id=n.id WHERE n.filesystem_id=$1 AND n.parent_id=$2 AND n.id>$3 ORDER BY n.id LIMIT $4").bind(fs).bind(n.id).bind(after).bind((limit+1)as i64).fetch_all(&mut *s.tx).await?;
    Ok(paged(
        rows.iter()
            .map(|r| {
                let n = Node::from_row(r);
                let id = n.id;
                (id, Node { context: None, ..n })
            })
            .collect(),
        limit,
        &scope,
    ))
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum CreateInput {
    Directory {
        parent: Locator,
        name: String,
        request_key: Uuid,
    },
    File {
        parent: Locator,
        name: String,
        request_key: Uuid,
        content_base64: String,
        media_type: String,
    },
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Create {
    pub scope: Scope,
    pub input: CreateInput,
}
pub fn media_type(value: &str) -> Result<(), ApiError> {
    let valid = value
        .split(';')
        .next()
        .and_then(|v| v.trim().split_once('/'))
        .is_some_and(|(a, b)| {
            [a, b].into_iter().all(|s| {
                !s.is_empty()
                    && s.bytes()
                        .all(|c| c.is_ascii_alphanumeric() || b"!#$&^_.+-".contains(&c))
            })
        });
    if value.len() > 200 || !valid || axum::http::HeaderValue::from_str(value).is_err() {
        return Err(ApiError::bad("invalid media_type"));
    }
    Ok(())
}
pub async fn create(app: &App, fs: Uuid, r: Create) -> Result<Node, ApiError> {
    paths::validate_scope(fs, &r.scope)?;
    let (parent, name, key, bytes, mime) = match &r.input {
        CreateInput::Directory {
            parent,
            name,
            request_key,
        } => (parent, name, *request_key, Vec::new(), None),
        CreateInput::File {
            parent,
            name,
            request_key,
            content_base64,
            media_type: mime,
        } => {
            media_type(mime)?;
            let limit = app
                .config
                .inline_limit
                .min(app.config.max_file_bytes as usize);
            if content_base64.len() > limit.div_ceil(3) * 4 {
                return Err(ApiError(
                    StatusCode::PAYLOAD_TOO_LARGE,
                    "REQUEST_LIMIT",
                    "inline content exceeds limit",
                ));
            }
            let bytes = BASE64_STANDARD
                .decode(content_base64)
                .map_err(|_| ApiError::bad("invalid content_base64"))?;
            if bytes.len() > limit {
                return Err(ApiError(
                    StatusCode::PAYLOAD_TOO_LARGE,
                    "REQUEST_LIMIT",
                    "inline content exceeds limit",
                ));
            }
            if BASE64_STANDARD.encode(&bytes) != *content_base64 {
                return Err(ApiError::bad("content_base64 must be canonical"));
            }
            (parent, name, *request_key, bytes, Some(mime.as_str()))
        }
    };
    if key.is_nil() {
        return Err(ApiError::bad("request key required"));
    }
    validate_name(name)?;
    let hash = format!(
        "{:x}",
        Sha256::digest(
            serde_json::to_vec(&r.input).map_err(|_| ApiError::bad("invalid create input"))?
        )
    );
    let scope = format!("filesystem/{fs}/actor/{}", r.scope.actor_id);
    let mut s = session(app, fs, true).await?;
    let prior=sqlx::query("SELECT request_hash,result FROM idempotency_keys WHERE scope=$1 AND operation='create-node' AND request_key=$2 AND (expires_at IS NULL OR expires_at>now())")
        .bind(&scope).bind(key.to_string()).fetch_optional(&mut *s.tx).await?;
    if let Some(prior) = prior {
        if prior.get::<String, _>("request_hash") != hash {
            return Err(ApiError::state("IDEMPOTENCY_CONFLICT"));
        }
        return serde_json::from_value(prior.get("result"))
            .map_err(|_| ApiError::state("INVALID_RECEIPT"));
    }
    let target = s.resolve(&r.scope, parent).await?;
    paths::guard(parent, target.id, true)?;
    target.writable()?;
    target.directory()?;
    s.name(target.id, name)?;
    if depth(&mut s.tx, fs, target.id).await? >= 128 {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    s.add_nodes(1).await?;
    s.usage(bytes.len() as i64).await?;
    let id = Uuid::now_v7();
    let kind = if mime.is_some() { "file" } else { "directory" };
    sqlx::query("INSERT INTO nodes(id,filesystem_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,$4,$5,$6)")
        .bind(id).bind(fs).bind(target.id).bind(name).bind(kind).bind(bytes.len() as i64).execute(&mut *s.tx).await?;
    if let Some(mime) = mime {
        sqlx::query("INSERT INTO files(node_id,storage_kind,inline_bytes,media_type) VALUES($1,'inline',$2,$3)")
            .bind(id).bind(&bytes).bind(mime).execute(&mut *s.tx).await?;
    }
    bump(&mut s.tx, &[target.id]).await?;
    let n = fetch(&mut s.tx, id).await?;
    if kind == "file" {
        let digest = format!("{:x}", Sha256::digest(&bytes));
        super::artifacts::record_intent(&mut s, &n, r.scope.actor_id, None, Some(&digest)).await?;
    }
    sqlx::query("INSERT INTO idempotency_keys(scope,operation,request_key,request_hash,result,completed_at,expires_at) VALUES($1,'create-node',$2,$3,$4,now(),now()+interval '24 hours') ON CONFLICT(scope,operation,request_key) DO UPDATE SET request_hash=excluded.request_hash,result=excluded.result,completed_at=excluded.completed_at,expires_at=excluded.expires_at WHERE idempotency_keys.expires_at<=now()")
        .bind(scope).bind(key.to_string()).bind(hash).bind(json!(n)).execute(&mut *s.tx).await?;
    s.tx.commit().await?;
    if kind == "file" {
        super::artifacts::dispatch_pending(app, id).await;
    }
    Ok(n)
}
pub async fn modify(app: &App, fs: Uuid, action: &str, r: Request) -> Result<Node, ApiError> {
    let mut s = session(app, fs, true).await?;
    let l = needed(r.input.locator.as_ref())?;
    let n = s.resolve(&r.scope, l).await?;
    paths::guard(l, n.id, false)?;
    n.writable()?;
    n.revision(r.input.revision.as_deref())?;
    if n.id == s.root {
        return Err(ApiError::state("ROOT_IMMUTABLE"));
    }
    if action == "replace-content" {
        if n.kind != "file" {
            return Err(ApiError::state("NOT_FILE"));
        }
        let bytes = needed(r.input.content.as_deref())?;
        if bytes.len()
            > app
                .config
                .inline_limit
                .min(app.config.max_file_bytes as usize)
        {
            return Err(ApiError(
                StatusCode::PAYLOAD_TOO_LARGE,
                "REQUEST_LIMIT",
                "inline content exceeds limit",
            ));
        }
        let mime = r
            .input
            .media_type
            .as_deref()
            .or(n.media_type.as_deref())
            .unwrap_or("application/octet-stream");
        media_type(mime)?;
        s.usage(bytes.len() as i64 - n.size_bytes.parse::<i64>().unwrap())
            .await?;
        super::artifacts::invalidate(&mut s, n.id).await?;
        super::trash::queue_object(&mut s.tx, n.id, s.bucket).await?;
        sqlx::query("UPDATE files SET storage_kind='inline',inline_bytes=$2,object_key=NULL,media_type=$3 WHERE node_id=$1").bind(n.id).bind(bytes).bind(mime).execute(&mut *s.tx).await?;
        sqlx::query("UPDATE nodes SET size_bytes=$2 WHERE id=$1")
            .bind(n.id)
            .bind(bytes.len() as i64)
            .execute(&mut *s.tx)
            .await?;
    } else {
        let name = r.input.name.unwrap_or(n.name.clone());
        validate_name(&name)?;
        let parent = if action == "move" {
            let l = needed(r.input.parent)?;
            let p = s.resolve(&r.scope, &l).await?;
            paths::guard(&l, p.id, true)?;
            p.writable()?;
            p.directory()?;
            p.id
        } else {
            needed(n.parent_id)?
        };
        s.name(parent, &name)?;
        cycle(&mut s.tx, fs, n.id, parent).await?;
        if depth(&mut s.tx, fs, parent).await? + 1 + subtree_height(&mut s.tx, fs, n.id).await?
            > 128
        {
            return Err(ApiError::state("RESOURCE_LIMIT"));
        }
        sqlx::query("UPDATE nodes SET name=$2,parent_id=$3 WHERE id=$1")
            .bind(n.id)
            .bind(name)
            .bind(parent)
            .execute(&mut *s.tx)
            .await?;
        let mut parents = vec![parent];
        if let Some(old) = n.parent_id
            && old != parent
        {
            parents.push(old);
        }
        bump(&mut s.tx, &parents).await?;
    }
    bump(&mut s.tx, &[n.id]).await?;
    let out = fetch(&mut s.tx, n.id).await?;
    if action == "replace-content" {
        let digest = format!("{:x}", Sha256::digest(needed(r.input.content.as_deref())?));
        super::artifacts::record_intent(&mut s, &out, r.scope.actor_id, None, Some(&digest))
            .await?;
    }
    s.tx.commit().await?;
    if action == "replace-content" {
        super::artifacts::dispatch_pending(app, n.id).await;
    }
    Ok(out)
}
