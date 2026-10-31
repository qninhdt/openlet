use super::{nodes::*, paths};
use crate::{
    http::{ApiError, App},
    storage,
};
use axum::{body::Body, http::StatusCode};
use base64::{Engine, prelude::BASE64_STANDARD};
use object_store::{
    ObjectStoreExt,
    multipart::{MultipartStore, PartId},
    path::Path,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::Row;
use std::time::Duration;
use uuid::Uuid;

#[derive(Clone)]
pub enum Access {
    User(Uuid),
    Processor(super::processing::Attempt),
    Enrichment(super::processing::Attempt),
}
impl From<Uuid> for Access {
    fn from(actor: Uuid) -> Self {
        Self::User(actor)
    }
}

pub async fn capacity(s: &mut Session<'_>, app: &App) -> Result<(), ApiError> {
    let count: i64 = sqlx::query_scalar("SELECT (SELECT count(*) FROM uploads WHERE bucket_id=$1 AND processing_file_id IS NULL AND state IN ('open','completing'))+(SELECT count(*) FROM idempotency_keys r JOIN filesystems f ON f.id=(r.result->>'filesystem_id')::uuid WHERE f.bucket_id=$1 AND r.operation='copy-node' AND r.completed_at IS NULL)")
        .bind(s.bucket)
        .fetch_one(&mut *s.tx)
        .await?;
    let backlog: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM object_deletions WHERE bucket_id=$1 AND (state!='deleted' OR ambiguous_write OR open_writes>0)",
    )
    .bind(s.bucket)
    .fetch_one(&mut *s.tx)
    .await?;
    if count >= app.config.max_outstanding || backlog >= app.config.max_cleanup_backlog {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    Ok(())
}
async fn target(
    s: &mut Session<'_>,
    scope: &paths::Scope,
    input: &Input,
) -> Result<(Option<Node>, Uuid, String), ApiError> {
    if let Some(l) = &input.locator {
        if input.parent.is_some() || input.name.is_some() {
            return Err(ApiError::bad("overwrite cannot select another destination"));
        }
        let n = s.resolve(scope, l).await?;
        paths::guard(l, n.id, false)?;
        n.writable()?;
        n.revision(input.revision.as_deref())?;
        if n.kind != "file" {
            return Err(ApiError::state("NOT_FILE"));
        }
        let parent = needed(n.parent_id)?;
        let name = n.name.clone();
        return Ok((Some(n), parent, name));
    }

    if input.revision.is_some() {
        return Err(ApiError::bad("create has no revision"));
    }
    let l = input
        .parent
        .as_ref()
        .ok_or_else(|| ApiError::bad("parent required"))?;
    let parent = s.resolve(scope, l).await?;
    paths::guard(l, parent.id, true)?;
    parent.writable()?;
    parent.directory()?;
    let name = needed(input.name.clone())?;
    s.name(parent.id, &name)?;
    let exists: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM nodes WHERE filesystem_id=$1 AND parent_id=$2 AND name=$3)",
    )
    .bind(s.fs)
    .bind(parent.id)
    .bind(&name)
    .fetch_one(&mut *s.tx)
    .await?;
    if exists {
        return Err(ApiError::state("NAME_CONFLICT"));
    }
    if depth(&mut s.tx, s.fs, parent.id).await? >= 128 {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    Ok((None, parent.id, name))
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum StorageMode {
    Inline,
    Object,
}
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Receipt {
    pub part_number: u32,
    pub etag: String,
}
pub(super) fn byte_count(value: &str) -> Result<i64, ApiError> {
    value
        .parse::<i64>()
        .ok()
        .filter(|v| *v >= 0 && v.to_string() == value)
        .ok_or_else(|| ApiError::bad("size_bytes must be a canonical nonnegative decimal"))
}
pub fn checksum_hex(value: &str) -> Result<String, ApiError> {
    let bytes = BASE64_STANDARD
        .decode(value)
        .map_err(|_| ApiError::bad("invalid Content-MD5"))?;
    if bytes.len() != 16 || BASE64_STANDARD.encode(&bytes) != value {
        return Err(ApiError::bad("invalid Content-MD5"));
    }
    Ok(bytes.iter().map(|v| format!("{v:02x}")).collect())
}
fn active(row: &sqlx::postgres::PgRow) -> Result<(), ApiError> {
    if !matches!(row.get::<&str, _>("state"), "open" | "completing")
        || row.get::<chrono::DateTime<chrono::Utc>, _>("expires_at") <= chrono::Utc::now()
    {
        return Err(ApiError::state("UPLOAD_NOT_ACTIVE"));
    }
    Ok(())
}
async fn load(
    s: &mut Session<'_>,
    id: Uuid,
    access: &Access,
) -> Result<sqlx::postgres::PgRow, ApiError> {
    let publication_complete = match access {
        Access::Processor(attempt) => {
            super::processing::validate(s, attempt)
                .await?
                .get::<&str, _>("publication_status")
                != "pending"
        }
        Access::Enrichment(attempt) => {
            super::enrichment::validate_attempt(s, attempt)
                .await?
                .get::<&str, _>("publication_status")
                == "ready"
        }
        Access::User(_) => false,
    };
    let row = sqlx::query("SELECT * FROM uploads WHERE id=$1 AND filesystem_id=$2 FOR UPDATE")
        .bind(id)
        .bind(s.fs)
        .fetch_optional(&mut *s.tx)
        .await?
        .ok_or_else(ApiError::not_found)?;
    let permitted = match access {
        Access::User(actor) => {
            row.get::<Uuid, _>("actor_id") == *actor
                && row.get::<Option<Uuid>, _>("processing_file_id").is_none()
        }
        Access::Processor(attempt) | Access::Enrichment(attempt) => {
            row.get::<Option<Uuid>, _>("processing_file_id") == Some(attempt.source.file_id)
                && row.get::<Option<i64>, _>("processing_generation")
                    == Some(attempt.source.generation)
                && row.get::<Option<i32>, _>("processing_attempt") == Some(attempt.number)
                && row.get::<Option<Uuid>, _>("processing_attempt_id") == Some(attempt.attempt_id)
                && row.get::<Option<&str>, _>("processing_stage")
                    == Some(if matches!(access, Access::Processor(_)) {
                        "parse"
                    } else {
                        "enrichment"
                    })
        }
    };
    if !permitted {
        return Err(ApiError::not_found());
    }
    if publication_complete && matches!(row.get::<&str, _>("state"), "open" | "completing") {
        return Err(ApiError::state("PROCESSING_NOT_ACTIVE"));
    }
    Ok(row)
}
fn description(row: &sqlx::postgres::PgRow) -> Value {
    let mut value = json!({"id":row.get::<Uuid,_>("id"),"status":row.get::<&str,_>("state"),
        "transport":row.get::<&str,_>("transport"),"expires_at":row.get::<chrono::DateTime<chrono::Utc>,_>("expires_at")});
    if let Some(size) = row
        .get::<Option<i64>, _>("expected_size")
        .or(row.get("size_bytes"))
    {
        value["size_bytes"] = json!(size.to_string());
    }
    if let Some(result) = row.get::<Option<Value>, _>("result") {
        value["result"] = result;
    }
    if let Some(size) = row.get::<Option<i64>, _>("part_size") {
        value["part_size_bytes"] = json!(size.to_string());
        value["part_count"] = json!(
            row.get::<i64, _>("expected_size")
                .checked_add(size - 1)
                .unwrap()
                / size
        );
    }
    value
}
pub async fn create(app: &App, fs: Uuid, r: Request) -> Result<Value, ApiError> {
    if r.input.content.is_some() || r.input.locators.is_some() || r.input.entry_id.is_some() {
        return Err(ApiError::bad("invalid upload metadata"));
    }
    let request_key = needed(r.input.request_key)?;
    if request_key.is_nil() {
        return Err(ApiError::bad("invalid upload request key"));
    }
    let mut s = session(app, fs, true).await?;
    paths::validate_scope(fs, &r.scope)?;
    let fingerprint = json!(r);
    let hash = format!(
        "{:x}",
        Sha256::digest(
            serde_json::to_vec(&fingerprint)
                .map_err(|_| ApiError::bad("invalid upload metadata"))?
        )
    );
    let scope = format!("filesystem/{fs}/actor/{}", r.scope.actor_id);
    let previous = sqlx::query("SELECT request_hash,result FROM idempotency_keys WHERE scope=$1 AND operation='create-upload' AND request_key=$2 AND (expires_at IS NULL OR expires_at>now())")
        .bind(&scope).bind(request_key.to_string()).fetch_optional(&mut *s.tx).await?;
    if let Some(previous) = previous {
        if previous.get::<String, _>("request_hash") != hash {
            return Err(ApiError::state("IDEMPOTENCY_CONFLICT"));
        }
        let id = serde_json::from_value(previous.get::<Value, _>("result")["id"].clone())
            .map_err(|_| ApiError::state("INVALID_RECEIPT"))?;
        s.tx.commit().await?;
        return prepare_transfer(app, fs, id, &Access::User(r.scope.actor_id)).await;
    }
    capacity(&mut s, app).await?;
    target(&mut s, &r.scope, &r.input).await?;
    let id = insert(&mut s, app, r.scope.actor_id, fingerprint, &r.input).await?;
    sqlx::query("INSERT INTO idempotency_keys(scope,operation,request_key,request_hash,result) VALUES($1,'create-upload',$2,$3,$4) ON CONFLICT(scope,operation,request_key) DO UPDATE SET request_hash=excluded.request_hash,result=excluded.result,completed_at=NULL,expires_at=NULL WHERE idempotency_keys.expires_at<=now()")
        .bind(scope).bind(request_key.to_string()).bind(hash).bind(json!({"id":id})).execute(&mut *s.tx).await?;
    s.tx.commit().await?;
    prepare_transfer(app, fs, id, &Access::User(r.scope.actor_id)).await
}
pub(super) async fn insert(
    s: &mut Session<'_>,
    app: &App,
    actor: Uuid,
    fingerprint: Value,
    input: &Input,
) -> Result<Uuid, ApiError> {
    let size = byte_count(&needed(input.size_bytes.clone())?)?;
    if size > app.config.max_file_bytes {
        return Err(ApiError(
            StatusCode::PAYLOAD_TOO_LARGE,
            "REQUEST_LIMIT",
            "file exceeds maximum",
        ));
    }
    let transport = match needed(input.storage.clone())? {
        StorageMode::Inline => {
            if size > app.config.inline_limit as i64 {
                return Err(ApiError(
                    StatusCode::PAYLOAD_TOO_LARGE,
                    "REQUEST_LIMIT",
                    "inline bytes exceed limit",
                ));
            }
            if input.content_md5.is_some() {
                return Err(ApiError::bad("inline upload has no Content-MD5"));
            }
            "inline"
        }
        StorageMode::Object if size < app.config.storage.multipart_threshold_bytes => {
            checksum_hex(&needed(input.content_md5.clone())?)?;
            "single"
        }
        StorageMode::Object => {
            if input.content_md5.is_some() {
                return Err(ApiError::bad(
                    "whole-object Content-MD5 is unsupported for multipart uploads",
                ));
            }
            "multipart"
        }
    };
    let id = Uuid::now_v7();
    let key = (transport != "inline").then(|| format!("objects/{}/{id}", s.bucket));
    let part_size = (transport == "multipart").then_some(app.config.storage.multipart_part_bytes);
    sqlx::query("INSERT INTO uploads(id,filesystem_id,bucket_id,actor_id,input,candidate_key,transport,expected_size,content_md5,part_size) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)")
        .bind(id).bind(s.fs).bind(s.bucket).bind(actor).bind(fingerprint).bind(key)
        .bind(transport).bind(size).bind(input.content_md5.clone()).bind(part_size).execute(&mut *s.tx).await?;
    Ok(id)
}
pub(super) async fn prepare_transfer(
    app: &App,
    fs: Uuid,
    id: Uuid,
    access: &Access,
) -> Result<Value, ApiError> {
    let mut s = session(app, fs, true).await?;
    let row = load(&mut s, id, access).await?;
    let mut value = description(&row);
    if matches!(row.get::<&str, _>("state"), "finalized" | "aborted")
        || row.get::<chrono::DateTime<chrono::Utc>, _>("expires_at") <= chrono::Utc::now()
    {
        return Ok(value);
    }
    active(&row)?;
    let transport = row.get::<&str, _>("transport");
    if row.get::<&str, _>("state") == "completing" {
        return Ok(value);
    }
    if transport == "single" {
        let signed = sign(app, &row, access, None).await?;
        record_capability(&mut s, id, signed.expires_at, app).await?;
        value["transfer"] = json!(signed);
    }
    if transport == "multipart" && row.get::<Option<String>, _>("multipart_id").is_none() {
        let key = row.get::<String, _>("candidate_key");
        s.tx.commit().await?;
        let path = Path::from(key);
        let remote = app
            .storage
            .create_multipart(&path)
            .await
            .map_err(storage::error)?;
        // Competing prepares may create remote uploads; only the persisted winner issues URLs.
        let save = async {
            let mut s = session(app, fs, true).await?;
            let row = load(&mut s, id, access).await?;
            active(&row)?;
            let winner = if let Some(winner) = row.get::<Option<String>, _>("multipart_id") {
                winner
            } else {
                sqlx::query("UPDATE uploads SET multipart_id=$2,updated_at=now() WHERE id=$1")
                    .bind(id)
                    .bind(&remote)
                    .execute(&mut *s.tx)
                    .await?;
                remote.clone()
            };
            s.tx.commit().await?;
            Ok::<_, ApiError>(winner)
        }
        .await;
        // A failed commit acknowledgement may have persisted this remote as the winner.
        let winner = save?;
        if winner != remote {
            app.storage
                .abort_multipart(&path, &remote)
                .await
                .map_err(storage::error)?;
        }
        return Ok(value);
    }
    s.tx.commit().await?;
    Ok(value)
}
async fn sign(
    app: &App,
    row: &sqlx::postgres::PgRow,
    access: &Access,
    part: Option<u32>,
) -> Result<storage::transfers::SignedUpload, ApiError> {
    let remaining = (row.get::<chrono::DateTime<chrono::Utc>, _>("expires_at")
        - chrono::Utc::now())
    .num_seconds();
    if remaining < 1 {
        return Err(ApiError::state("UPLOAD_NOT_ACTIVE"));
    }
    let total = row.get::<i64, _>("expected_size");
    let size = if let Some(number) = part {
        let part_size = row.get::<i64, _>("part_size");
        if number == 0 || i64::from(number) > (total + part_size - 1) / part_size {
            return Err(ApiError::bad("invalid part number"));
        }
        part_size.min(total - (i64::from(number) - 1) * part_size)
    } else {
        total
    };
    let remote = row.get::<Option<String>, _>("multipart_id");
    let part = match part {
        Some(number) => Some((
            remote
                .as_deref()
                .ok_or_else(|| ApiError::state("UPLOAD_NOT_READY"))?,
            number,
        )),
        None => None,
    };
    let mut config = app.config.storage.clone();
    if !matches!(access, Access::User(_)) {
        config.signing_endpoint = config.endpoint.clone();
    }
    storage::transfers::upload_url(
        &config,
        &row.get::<String, _>("candidate_key"),
        size as u64,
        row.get::<Option<String>, _>("content_md5").as_deref(),
        Duration::from_secs(
            app.config
                .storage
                .upload_url_ttl_seconds
                .min(remaining as u64),
        ),
        part,
    )
    .await
}
async fn record_capability(
    s: &mut Session<'_>,
    id: Uuid,
    expires: chrono::DateTime<chrono::Utc>,
    app: &App,
) -> Result<(), ApiError> {
    sqlx::query("UPDATE uploads SET write_expires_at=greatest(write_expires_at,$2),transfer_deadline=greatest(transfer_deadline,$2+make_interval(secs=>$3)),updated_at=now() WHERE id=$1")
        .bind(id).bind(expires).bind(app.config.storage.upload_transfer_grace_seconds as f64).execute(&mut *s.tx).await?;
    Ok(())
}
pub async fn status(
    app: &App,
    fs: Uuid,
    id: Uuid,
    access: impl Into<Access>,
) -> Result<Value, ApiError> {
    let access = access.into();
    let mut s = session(app, fs, true).await?;
    Ok(description(&load(&mut s, id, &access).await?))
}
pub async fn part_urls(
    app: &App,
    fs: Uuid,
    id: Uuid,
    access: impl Into<Access>,
    parts: Vec<u32>,
) -> Result<Value, ApiError> {
    let access = access.into();
    if parts.is_empty() || parts.len() > 64 {
        return Err(ApiError::bad("part signing batch must contain 1..64 items"));
    }
    let mut s = session(app, fs, true).await?;
    let row = load(&mut s, id, &access).await?;
    active(&row)?;
    if row.get::<&str, _>("transport") != "multipart"
        || row.get::<Option<Value>, _>("completion_parts").is_some()
    {
        return Err(ApiError::state("UPLOAD_NOT_TRANSFERABLE"));
    }
    let mut seen = std::collections::HashSet::new();
    let mut values = Vec::with_capacity(parts.len());
    let mut latest_expiry = chrono::Utc::now();
    for part in parts {
        if !seen.insert(part) {
            return Err(ApiError::bad("duplicate part number"));
        }
        let signed = sign(app, &row, &access, Some(part)).await?;
        latest_expiry = latest_expiry.max(signed.expires_at);
        values.push(json!({"part_number":part,"transfer":signed}));
    }
    record_capability(&mut s, id, latest_expiry, app).await?;
    s.tx.commit().await?;
    Ok(json!({"items":values}))
}
pub async fn transfer(
    app: &App,
    fs: Uuid,
    id: Uuid,
    access: impl Into<Access>,
    body: Body,
) -> Result<Value, ApiError> {
    let access = access.into();
    // This receiver only accepts bounded inline bytes; object bytes go directly to storage.
    let bytes = axum::body::to_bytes(body, app.config.inline_limit)
        .await
        .map_err(|_| {
            ApiError(
                StatusCode::PAYLOAD_TOO_LARGE,
                "REQUEST_LIMIT",
                "invalid or oversized inline body",
            )
        })?;
    let mut s = session(app, fs, true).await?;
    let row = load(&mut s, id, &access).await?;
    if row.get::<&str, _>("transport") != "inline" {
        return Err(ApiError::state("DIRECT_UPLOAD_REQUIRED"));
    }
    let size = bytes.len() as i64;
    if size != row.get::<i64, _>("expected_size") {
        return Err(ApiError::bad("inline size differs from prepared size"));
    }
    let digest = format!("{:x}", Sha256::digest(&bytes));
    if row
        .get::<Option<String>, _>("sha256")
        .is_some_and(|saved| saved != digest)
    {
        return Err(ApiError::state("IDEMPOTENCY_CONFLICT"));
    }
    if row.get::<&str, _>("state") == "finalized" {
        return Ok(terminal_result(&row));
    }
    active(&row)?;
    sqlx::query(
        "UPDATE uploads SET size_bytes=$2,sha256=$3,inline_bytes=$4,updated_at=now() WHERE id=$1",
    )
    .bind(id)
    .bind(size)
    .bind(digest)
    .bind(bytes.as_ref())
    .execute(&mut *s.tx)
    .await?;
    s.tx.commit().await?;
    Ok(json!({"id":id,"status":row.get::<&str,_>("state"),"size_bytes":size.to_string()}))
}
fn multipart_evidence(parts: &[Receipt], expected_count: i64) -> Result<(), ApiError> {
    if parts.len() as i64 != expected_count || parts.is_empty() || parts.len() > 10000 {
        return Err(ApiError::bad("incomplete multipart receipts"));
    }
    for (index, part) in parts.iter().enumerate() {
        if part.part_number as usize != index + 1 {
            return Err(ApiError::bad(
                "multipart receipts must be ordered and contiguous",
            ));
        }
        // Provider validators are opaque, including when encryption changes their format.
        if part.etag.is_empty() || part.etag.len() > 1024 || part.etag.chars().any(char::is_control)
        {
            return Err(ApiError::bad("invalid multipart ETag"));
        }
    }
    Ok(())
}
pub async fn finalize(
    app: &App,
    fs: Uuid,
    id: Uuid,
    access: impl Into<Access>,
    parts: Option<Vec<Receipt>>,
) -> Result<Value, ApiError> {
    let access = access.into();
    let mut s = session(app, fs, true).await?;
    let row = load(&mut s, id, &access).await?;
    if let Some(ref parts) = parts
        && row
            .get::<Option<Value>, _>("completion_parts")
            .as_ref()
            .is_some_and(|intent| intent != &json!(parts))
    {
        return Err(ApiError::state("IDEMPOTENCY_CONFLICT"));
    }
    let transport = row.get::<&str, _>("transport");
    if transport != "multipart" && parts.is_some() {
        return Err(ApiError::bad("only multipart accepts receipts"));
    }
    if row.get::<&str, _>("state") == "finalized" {
        return Ok(terminal_result(&row));
    }
    active(&row)?;
    if transport == "inline" && row.get::<Option<Vec<u8>>, _>("inline_bytes").is_none() {
        return Err(ApiError::state("UPLOAD_NOT_READY"));
    }
    let mut frozen = row.get::<Option<Value>, _>("completion_parts");
    if transport == "multipart" {
        if let Some(parts) = parts {
            let part_size = row.get::<i64, _>("part_size");
            let count = (row.get::<i64, _>("expected_size") + part_size - 1) / part_size;
            multipart_evidence(&parts, count)?;
            let intent = json!(parts);
            sqlx::query("UPDATE uploads SET completion_parts=$2,updated_at=now() WHERE id=$1")
                .bind(id)
                .bind(&intent)
                .execute(&mut *s.tx)
                .await?;
            frozen = Some(intent);
        }
        if frozen.is_none() {
            return Err(ApiError::bad("multipart completion requires receipts"));
        }
    }
    sqlx::query("UPDATE uploads SET state='completing',updated_at=now() WHERE id=$1")
        .bind(id)
        .execute(&mut *s.tx)
        .await?;
    s.tx.commit().await?;
    if transport != "inline" {
        let key = Path::from(row.get::<String, _>("candidate_key"));
        let mut head = app.storage.head(&key).await;
        if matches!(head, Err(object_store::Error::NotFound { .. })) && transport == "multipart" {
            let receipts: Vec<Receipt> = serde_json::from_value(needed(frozen)?)
                .map_err(|_| ApiError::state("INVALID_UPLOAD_STATE"))?;
            let remote = needed(row.get::<Option<String>, _>("multipart_id"))?;
            let complete = app
                .storage
                .complete_multipart(
                    &key,
                    &remote,
                    receipts
                        .into_iter()
                        .map(|p| PartId { content_id: p.etag })
                        .collect(),
                )
                .await;
            // A timeout/NoSuchUpload can follow a successful remote completion: HEAD the unique key.
            head = app.storage.head(&key).await;
            if head.is_err() {
                complete.map_err(storage::error)?;
            }
        }
        let head = match head {
            Err(object_store::Error::NotFound { .. }) => {
                return Err(ApiError::state("UPLOAD_NOT_READY"));
            }
            other => other.map_err(storage::error)?,
        };
        // A unique conditional PUT, or the one MPU's frozen receipts, owns this immutable key.
        // Content-MD5 is enforced by the provider for single PUT; ETag is not a checksum.
        if head.size != row.get::<i64, _>("expected_size") as u64 {
            abort(app, fs, id, access.clone()).await?;
            return Err(ApiError::state("UPLOAD_EVIDENCE_MISMATCH"));
        }
    }
    let result = publish(app, fs, id, &access).await;
    if let Err(error) = &result
        && error.0.is_client_error()
    {
        // Rejecting publication must also retain cleanup evidence for its unpublished bytes.
        if let Err(cleanup_error) = abort(app, fs, id, access.clone()).await
            && cleanup_error.1 != "UPLOAD_FINALIZED"
        {
            return Err(cleanup_error);
        }
    }
    result
}
fn terminal_result(row: &sqlx::postgres::PgRow) -> Value {
    row.get::<Value, _>("result")
}
async fn publish(app: &App, fs: Uuid, id: Uuid, access: &Access) -> Result<Value, ApiError> {
    let mut s = session(app, fs, true).await?;
    let row = load(&mut s, id, access).await?;
    if row.get::<&str, _>("state") == "finalized" {
        return Ok(terminal_result(&row));
    }
    active(&row)?;
    let transport = row.get::<&str, _>("transport");
    if transport == "inline" && row.get::<Option<Vec<u8>>, _>("inline_bytes").is_none() {
        return Err(ApiError::state("UPLOAD_NOT_READY"));
    }
    if matches!(access, Access::Processor(_) | Access::Enrichment(_)) {
        let result = json!({"id":id,"status":"finalized","size_bytes":row.get::<i64,_>("expected_size").to_string()});
        sqlx::query("UPDATE uploads SET state='finalized',size_bytes=expected_size,result=$2,updated_at=now() WHERE id=$1")
            .bind(id).bind(&result).execute(&mut *s.tx).await?;
        s.tx.commit().await?;
        return Ok(result);
    }
    let actor = row.get::<Uuid, _>("actor_id");
    let saved: Request = serde_json::from_value(row.get("input"))
        .map_err(|_| ApiError::state("INVALID_UPLOAD_STATE"))?;
    let (old, parent, name) = target(&mut s, &saved.scope, &saved.input).await?;
    let size = row.get::<i64, _>("expected_size");
    let old_size = old
        .as_ref()
        .map(|n| n.size_bytes.parse::<i64>().unwrap())
        .unwrap_or(0);
    s.usage(size - old_size).await?;
    let node_id = if let Some(n) = old {
        super::artifacts::invalidate(&mut s, n.id).await?;
        super::trash::queue_object(&mut s.tx, n.id, s.bucket).await?;
        sqlx::query(
            "UPDATE nodes SET size_bytes=$2,revision=revision+1,updated_at=now() WHERE id=$1",
        )
        .bind(n.id)
        .bind(size)
        .execute(&mut *s.tx)
        .await?;
        n.id
    } else {
        s.add_nodes(1).await?;
        let id = Uuid::now_v7();
        sqlx::query("INSERT INTO nodes(id,filesystem_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,$4,'file',$5)")
            .bind(id).bind(fs).bind(parent).bind(name).bind(size).execute(&mut *s.tx).await?;
        bump(&mut s.tx, &[parent]).await?;
        id
    };
    let key = row.get::<Option<String>, _>("candidate_key");
    if transport == "inline" {
        sqlx::query("INSERT INTO files(node_id,storage_kind,inline_bytes,media_type) VALUES($1,'inline',$2,$3) ON CONFLICT(node_id) DO UPDATE SET storage_kind='inline',inline_bytes=excluded.inline_bytes,object_key=NULL,media_type=excluded.media_type")
            .bind(node_id)
            .bind(row.get::<Vec<u8>, _>("inline_bytes"))
            .bind(saved.input.media_type.as_deref().unwrap_or("application/octet-stream"))
            .execute(&mut *s.tx)
            .await?;
    } else {
        sqlx::query("INSERT INTO files(node_id,storage_kind,object_key,media_type) VALUES($1,'object',$2,$3) ON CONFLICT(node_id) DO UPDATE SET storage_kind='object',inline_bytes=NULL,object_key=excluded.object_key,media_type=excluded.media_type")
            .bind(node_id)
            .bind(needed(key.clone())?)
            .bind(saved.input.media_type.as_deref().unwrap_or("application/octet-stream"))
            .execute(&mut *s.tx)
            .await?;
    }
    let node = fetch(&mut s.tx, node_id).await?;
    let processing = super::artifacts::record_intent(
        &mut s,
        &node,
        actor,
        key.as_deref(),
        row.get::<Option<String>, _>("sha256").as_deref(),
    )
    .await?;
    let result = json!({"node_id":node_id,"status":"finalized","revision":node.revision});
    complete_receipt(&mut s, id).await?;
    sqlx::query("UPDATE uploads SET state='finalized',result_node_id=$2,result=$3,size_bytes=expected_size,inline_bytes=NULL,updated_at=now() WHERE id=$1")
        .bind(id).bind(node_id).bind(&result).execute(&mut *s.tx).await?;
    s.tx.commit().await?;
    if let Some(op) = processing
        && crate::temporal::process_file_workflow::dispatch(app, op)
            .await
            .is_err()
    {
        tracing::warn!(file_id=%op.file_id,generation=op.generation,"processing dispatch deferred to maintenance");
    }
    Ok(result)
}
async fn complete_receipt(s: &mut Session<'_>, id: Uuid) -> Result<(), ApiError> {
    sqlx::query("UPDATE idempotency_keys SET completed_at=now(),expires_at=now()+interval '24 hours' WHERE operation='create-upload' AND result->>'id'=$1 AND completed_at IS NULL")
        .bind(id.to_string()).execute(&mut *s.tx).await?;
    Ok(())
}
async fn queue_candidate(s: &mut Session<'_>, id: Uuid) -> Result<(), ApiError> {
    sqlx::query("INSERT INTO object_deletions(object_key,bucket_id,ambiguous_write,eligible_at) SELECT candidate_key,bucket_id,write_expires_at IS NOT NULL,greatest(now()+interval '15 minutes',transfer_deadline) FROM uploads WHERE id=$1 AND candidate_key IS NOT NULL ON CONFLICT(object_key) DO UPDATE SET state='pending',ambiguous_write=object_deletions.ambiguous_write OR excluded.ambiguous_write,eligible_at=greatest(object_deletions.eligible_at,excluded.eligible_at)")
        .bind(id).execute(&mut *s.tx).await?;
    Ok(())
}
pub async fn abort(
    app: &App,
    fs: Uuid,
    id: Uuid,
    access: impl Into<Access>,
) -> Result<(), ApiError> {
    let access = access.into();
    let mut s = lifecycle_session(app, fs).await?;
    let row = load(&mut s, id, &access).await?;
    if row.get::<&str, _>("state") == "finalized" {
        return Err(ApiError::state("UPLOAD_FINALIZED"));
    }
    sqlx::query(
        "UPDATE uploads SET state='aborted',inline_bytes=NULL,updated_at=now() WHERE id=$1",
    )
    .bind(id)
    .execute(&mut *s.tx)
    .await?;
    queue_candidate(&mut s, id).await?;
    complete_receipt(&mut s, id).await?;
    s.tx.commit().await?;
    if let Some(remote) = row.get::<Option<String>, _>("multipart_id") {
        abort_multipart(
            app,
            id,
            &needed(row.get::<Option<String>, _>("candidate_key"))?,
            &remote,
        )
        .await?;
    }
    Ok(())
}
pub async fn expire(app: &App, fs: Uuid, id: Uuid) -> Result<(), ApiError> {
    let mut s = lifecycle_session(app, fs).await?;
    let changed=sqlx::query("UPDATE uploads SET state='aborted',inline_bytes=NULL,updated_at=now() WHERE id=$1 AND filesystem_id=$2 AND state IN ('open','completing') AND expires_at<=now()")
        .bind(id).bind(fs).execute(&mut *s.tx).await?.rows_affected();
    if changed == 1 {
        queue_candidate(&mut s, id).await?;
        complete_receipt(&mut s, id).await?;
    }
    s.tx.commit().await?;
    Ok(())
}
pub async fn abort_multipart(app: &App, id: Uuid, key: &str, remote: &str) -> Result<(), ApiError> {
    match app
        .storage
        .abort_multipart(&Path::from(key), &remote.to_owned())
        .await
    {
        Ok(()) | Err(object_store::Error::NotFound { .. }) => {}
        Err(error) => return Err(storage::error(error)),
    }
    sqlx::query("UPDATE uploads SET multipart_id=NULL,updated_at=now() WHERE id=$1 AND multipart_id=$2 AND state='aborted'")
        .bind(id).bind(remote).execute(&app.pool).await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn checksums_and_receipts_have_canonical_protocol_shapes() {
        assert_eq!(
            checksum_hex("XUFAKrxLKna5cZ2REBfFkg==").unwrap(),
            "5d41402abc4b2a76b9719d911017c592"
        );
        for value in [
            "",
            "5d41402abc4b2a76b9719d911017c592",
            "XUFAKrxLKna5cZ2REBfFkg",
            "XUFAKrxLKna5cZ2REBfFkg==\r\n",
        ] {
            assert!(checksum_hex(value).is_err());
        }
        assert_eq!(byte_count("0").unwrap(), 0);
        for value in ["01", "-1", "+1", " 1", "9223372036854775808"] {
            assert!(byte_count(value).is_err());
        }
        let part = Receipt {
            part_number: 1,
            etag: "\"5d41402abc4b2a76b9719d911017c592\"".into(),
        };
        multipart_evidence(std::slice::from_ref(&part), 1).unwrap();
        multipart_evidence(
            &[Receipt {
                etag: "opaque-provider-validator".into(),
                ..part.clone()
            }],
            1,
        )
        .unwrap();
        assert!(multipart_evidence(std::slice::from_ref(&part), 2).is_err());
        assert!(
            multipart_evidence(
                &[Receipt {
                    part_number: 2,
                    ..part.clone()
                }],
                1
            )
            .is_err()
        );
        assert!(
            multipart_evidence(
                &[Receipt {
                    etag: "bad\r\nheader".into(),
                    ..part
                }],
                1
            )
            .is_err()
        );
    }
}
