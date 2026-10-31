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
    Enrichment(Uuid),
}
impl From<Uuid> for Access {
    fn from(actor: Uuid) -> Self {
        Self::User(actor)
    }
}

pub async fn capacity(s: &mut Session<'_>, app: &App) -> Result<(), ApiError> {
    let count: i64 = sqlx::query_scalar("SELECT (SELECT count(*) FROM uploads WHERE bucket_id=$1 AND processing_operation_id IS NULL AND state IN ('created','transferring','uploaded'))+(SELECT count(*) FROM operations o JOIN filesystems f ON f.id=o.filesystem_id WHERE f.bucket_id=$1 AND o.state IN ('running','discarding'))")
        .bind(s.bucket)
        .fetch_one(&mut *s.tx)
        .await?;
    let backlog: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM object_deletions WHERE bucket_id=$1 AND state!='deleted'",
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
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PartRequest {
    pub part_number: u32,
    pub content_md5: String,
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
    if !matches!(
        row.get::<&str, _>("state"),
        "created" | "transferring" | "uploaded"
    ) || row.get::<chrono::DateTime<chrono::Utc>, _>("expires_at") <= chrono::Utc::now()
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
    if let Access::Processor(attempt) = access {
        super::processing::validate(s, attempt).await?;
    }
    if let Access::Enrichment(op) = access {
        let operation = super::enrichment::validate(s, *op).await?;
        if operation.get::<&str, _>("enrichment_state") == "succeeded" {
            return Err(ApiError::state("ENRICHMENT_COMPLETE"));
        }
    }
    let row = sqlx::query("SELECT * FROM uploads WHERE id=$1 AND filesystem_id=$2 FOR UPDATE")
        .bind(id)
        .bind(s.fs)
        .fetch_optional(&mut *s.tx)
        .await?
        .ok_or_else(ApiError::not_found)?;
    let permitted = match access {
        Access::User(actor) => {
            row.get::<Uuid, _>("actor_id") == *actor
                && row
                    .get::<Option<Uuid>, _>("processing_operation_id")
                    .is_none()
        }
        Access::Processor(attempt) => {
            row.get::<Option<Uuid>, _>("processing_operation_id") == Some(attempt.operation_id)
                && row.get::<Option<i32>, _>("processing_generation") == Some(attempt.generation)
                && row.get::<Option<Uuid>, _>("processing_attempt_id") == Some(attempt.attempt_id)
        }
        Access::Enrichment(op) => {
            row.get::<Option<Uuid>, _>("processing_operation_id") == Some(*op)
                && row.get::<Option<&str>, _>("processing_stage") == Some("enrichment")
        }
    };
    if !permitted {
        return Err(ApiError::not_found());
    }
    Ok(row)
}
fn description(row: &sqlx::postgres::PgRow) -> Value {
    let mut value = json!({"id":row.get::<Uuid,_>("id"),"state":row.get::<&str,_>("state"),
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
    if r.input.text.is_some()
        || r.input.locators.is_some()
        || r.input.parts.is_some()
        || r.input.entry_id.is_some()
    {
        return Err(ApiError::bad("invalid upload metadata"));
    }
    let request_key = needed(r.input.request_key)?;
    if request_key.is_nil() {
        return Err(ApiError::bad("invalid upload request key"));
    }
    let mut s = session(app, fs, true).await?;
    let fingerprint = json!(r);
    let previous = sqlx::query(
        "SELECT id,input FROM uploads WHERE filesystem_id=$1 AND actor_id=$2 AND request_key=$3",
    )
    .bind(fs)
    .bind(r.scope.actor_id)
    .bind(request_key)
    .fetch_optional(&mut *s.tx)
    .await?;
    if let Some(previous) = previous {
        if previous.get::<Value, _>("input") != fingerprint {
            return Err(ApiError::state("IDEMPOTENCY_CONFLICT"));
        }
        let id = previous.get("id");
        s.tx.commit().await?;
        return prepare_transfer(app, fs, id, &Access::User(r.scope.actor_id)).await;
    }
    capacity(&mut s, app).await?;
    target(&mut s, &r.scope, &r.input).await?;
    let id = insert(
        &mut s,
        app,
        r.scope.actor_id,
        request_key,
        fingerprint,
        &r.input,
    )
    .await?;
    s.tx.commit().await?;
    prepare_transfer(app, fs, id, &Access::User(r.scope.actor_id)).await
}
pub(super) async fn insert(
    s: &mut Session<'_>,
    app: &App,
    actor: Uuid,
    request_key: Uuid,
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
                    "multipart checksums belong to individual parts",
                ));
            }
            "multipart"
        }
    };
    let id = Uuid::now_v7();
    let key = (transport != "inline").then(|| format!("objects/{}/{id}", s.bucket));
    let part_size = (transport == "multipart").then_some(app.config.storage.multipart_part_bytes);
    sqlx::query("INSERT INTO uploads(id,filesystem_id,bucket_id,actor_id,input,candidate_key,request_key,transport,expected_size,content_md5,part_size) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)")
        .bind(id).bind(s.fs).bind(s.bucket).bind(actor).bind(fingerprint).bind(key).bind(request_key)
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
    if row.get::<&str, _>("state") == "finalized" {
        return Ok(value);
    }
    active(&row)?;
    let transport = row.get::<&str, _>("transport");
    if transport == "single" {
        let signed = sign(app, &row, &row.get::<String, _>("content_md5"), None).await?;
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
    md5: &str,
    part: Option<u32>,
) -> Result<storage::transfers::SignedUpload, ApiError> {
    checksum_hex(md5)?;
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
    storage::transfers::upload_url(
        &app.config.storage,
        &row.get::<String, _>("candidate_key"),
        size as u64,
        md5,
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
    parts: Vec<PartRequest>,
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
        if !seen.insert(part.part_number) {
            return Err(ApiError::bad("duplicate part number"));
        }
        let signed = sign(app, &row, &part.content_md5, Some(part.part_number)).await?;
        latest_expiry = latest_expiry.max(signed.expires_at);
        values.push(json!({"part_number":part.part_number,"transfer":signed}));
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
    active(&row)?;
    if row.get::<&str, _>("transport") != "inline" {
        return Err(ApiError::state("DIRECT_UPLOAD_REQUIRED"));
    }
    if bytes.len() as i64 != row.get::<i64, _>("expected_size") {
        return Err(ApiError::bad("inline size differs from prepared size"));
    }
    let digest = format!("{:x}", Sha256::digest(&bytes));
    if row.get::<&str, _>("state") == "uploaded"
        && row.get::<Option<String>, _>("sha256").as_deref() != Some(&digest)
    {
        return Err(ApiError::state("IDEMPOTENCY_CONFLICT"));
    }
    sqlx::query("UPDATE uploads SET state='uploaded',size_bytes=$2,sha256=$3,inline_bytes=$4,updated_at=now() WHERE id=$1")
        .bind(id).bind(bytes.len() as i64).bind(digest).bind(bytes.as_ref()).execute(&mut *s.tx).await?;
    s.tx.commit().await?;
    Ok(json!({"id":id,"state":"uploaded","size_bytes":bytes.len().to_string()}))
}
fn multipart_evidence(parts: &[Receipt], expected_count: i64) -> Result<String, ApiError> {
    use md5::{Digest, Md5};
    if parts.len() as i64 != expected_count || parts.len() > 10000 {
        return Err(ApiError::bad("incomplete multipart receipts"));
    }
    let mut digest = Md5::new();
    for (index, part) in parts.iter().enumerate() {
        if part.part_number as usize != index + 1 {
            return Err(ApiError::bad(
                "multipart receipts must be ordered and contiguous",
            ));
        }
        let etag = part.etag.trim_matches('"');
        if etag.len() != 32
            || !etag
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err(ApiError::bad("invalid multipart ETag"));
        }
        let raw = (0..32)
            .step_by(2)
            .map(|i| u8::from_str_radix(&etag[i..i + 2], 16).unwrap())
            .collect::<Vec<_>>();
        digest.update(raw);
    }
    let checksum = digest
        .finalize()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    Ok(format!("\"{checksum}-{}\"", parts.len()))
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
    if row.get::<&str, _>("state") == "finalized" {
        return Ok(terminal_result(&row));
    }
    active(&row)?;
    let transport = row.get::<&str, _>("transport");
    let mut frozen = row.get::<Option<Value>, _>("completion_parts");
    let mut expected_etag = row.get::<Option<String>, _>("expected_etag");
    if transport == "multipart" {
        if let Some(parts) = parts {
            let count = (row.get::<i64, _>("expected_size") + row.get::<i64, _>("part_size") - 1)
                / row.get::<i64, _>("part_size");
            let etag = multipart_evidence(&parts, count)?;
            let intent = json!(parts);
            sqlx::query("UPDATE uploads SET completion_parts=$2,expected_etag=$3,state='transferring',updated_at=now() WHERE id=$1")
                .bind(id).bind(&intent).bind(&etag).execute(&mut *s.tx).await?;
            frozen = Some(intent);
            expected_etag = Some(etag);
        }
        if frozen.is_none() {
            return Err(ApiError::bad("multipart completion requires receipts"));
        }
    } else if parts.is_some() {
        return Err(ApiError::bad("only multipart accepts receipts"));
    }
    s.tx.commit().await?;
    if transport != "inline" {
        let key = Path::from(row.get::<String, _>("candidate_key"));
        let expected = if transport == "single" {
            format!(
                "\"{}\"",
                checksum_hex(&row.get::<String, _>("content_md5"))?
            )
        } else {
            needed(expected_etag)?
        };
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
        if head.size != row.get::<i64, _>("expected_size") as u64
            || head.e_tag.as_deref() != Some(&expected)
        {
            abort(app, fs, id, access.clone()).await?;
            return Err(ApiError::state("UPLOAD_EVIDENCE_MISMATCH"));
        }
    }
    let result = publish(app, fs, id, &access).await;
    if let Err(error) = &result
        && error.0.is_client_error()
    {
        // Rejecting publication must also retain cleanup evidence for its unpublished bytes.
        match abort(app, fs, id, access.clone()).await {
            Ok(()) => {}
            Err(e) if e.1 == "UPLOAD_FINALIZED" => {}
            Err(e) => return Err(e),
        }
    }
    result
}
fn terminal_result(row: &sqlx::postgres::PgRow) -> Value {
    row.get::<Option<Value>, _>("result").unwrap_or_else(
        || json!({"node_id":row.get::<Uuid,_>("result_node_id"),"state":"finalized"}),
    )
}
async fn publish(app: &App, fs: Uuid, id: Uuid, access: &Access) -> Result<Value, ApiError> {
    let mut s = session(app, fs, true).await?;
    let row = load(&mut s, id, access).await?;
    if row.get::<&str, _>("state") == "finalized" {
        return Ok(terminal_result(&row));
    }
    active(&row)?;
    if row.get::<&str, _>("transport") == "inline" && row.get::<&str, _>("state") != "uploaded" {
        return Err(ApiError::state("UPLOAD_NOT_READY"));
    }
    if matches!(access, Access::Processor(_) | Access::Enrichment(_)) {
        sqlx::query("UPDATE uploads SET state='uploaded',size_bytes=expected_size,updated_at=now() WHERE id=$1")
            .bind(id).execute(&mut *s.tx).await?;
        s.tx.commit().await?;
        return Ok(json!({"id":id,"state":"uploaded"}));
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
        super::artifacts::invalidate(&mut s, n.id, actor).await?;
        super::trash::queue_object(&mut s.tx, n.id, s.bucket).await?;
        sqlx::query("DELETE FROM file_data WHERE node_id=$1")
            .bind(n.id)
            .execute(&mut *s.tx)
            .await?;
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
    if row.get::<&str, _>("transport") == "inline" {
        sqlx::query(
            "INSERT INTO file_data(node_id,storage_kind,inline_bytes) VALUES($1,'inline',$2)",
        )
        .bind(node_id)
        .bind(row.get::<Vec<u8>, _>("inline_bytes"))
        .execute(&mut *s.tx)
        .await?;
    } else {
        sqlx::query(
            "INSERT INTO file_data(node_id,storage_kind,object_key) VALUES($1,'object',$2)",
        )
        .bind(node_id)
        .bind(needed(key.clone())?)
        .execute(&mut *s.tx)
        .await?;
    }
    let node = fetch(&mut s.tx, node_id).await?;
    let processing = super::artifacts::record_intent(
        &mut s,
        &node,
        actor,
        id,
        key.as_deref(),
        row.get::<Option<String>, _>("sha256").as_deref(),
    )
    .await?;
    let result = json!({"node_id":node_id,"state":"finalized","revision":node.revision});
    sqlx::query("UPDATE uploads SET state='finalized',result_node_id=$2,result=$3,size_bytes=expected_size,inline_bytes=NULL,updated_at=now() WHERE id=$1")
        .bind(id).bind(node_id).bind(&result).execute(&mut *s.tx).await?;
    s.tx.commit().await?;
    if let Some(op) = processing
        && crate::temporal::process_file_workflow::dispatch(app, op)
            .await
            .is_err()
    {
        tracing::warn!(operation_id=%op,"processing dispatch deferred to maintenance");
    }
    Ok(result)
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
    let changed=sqlx::query("UPDATE uploads SET state='expired',inline_bytes=NULL,updated_at=now() WHERE id=$1 AND filesystem_id=$2 AND state IN ('created','transferring','uploaded') AND expires_at<=now()")
        .bind(id).bind(fs).execute(&mut *s.tx).await?.rows_affected();
    if changed == 1 {
        queue_candidate(&mut s, id).await?;
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
    sqlx::query("UPDATE uploads SET multipart_id=NULL,updated_at=now() WHERE id=$1 AND multipart_id=$2 AND state IN ('aborted','expired')")
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
        assert_eq!(
            multipart_evidence(std::slice::from_ref(&part), 1).unwrap(),
            "\"62109206880d38a4010a98e11243924a-1\""
        );
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
                    etag: "bad".into(),
                    ..part
                }],
                1
            )
            .is_err()
        );
    }
}
