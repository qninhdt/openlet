use crate::{config::Config, fs};
use axum::{
    Json, Router,
    extract::{Request, State},
    http::StatusCode,
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{get, post},
};
use serde_json::json;
use sqlx::PgPool;
use std::sync::Arc;
mod exports;
mod processing;
use subtle::ConstantTimeEq;
#[derive(Clone)]
pub struct App {
    pub pool: PgPool,
    pub config: Arc<Config>,
    pub storage: Arc<object_store::aws::AmazonS3>,
    pub signer: Arc<object_store::aws::AmazonS3>,
    pub temporal: temporalio_client::Client,
}
#[derive(Clone, Debug)]
pub struct ApiError(pub StatusCode, pub &'static str, pub &'static str);
impl ApiError {
    pub fn state(code: &'static str) -> Self {
        Self(
            StatusCode::CONFLICT,
            code,
            "operation conflicts with current state",
        )
    }
    pub fn cross_filesystem() -> Self {
        Self::state("CROSS_FILESYSTEM_UNSUPPORTED")
    }
    pub fn precondition_required() -> Self {
        Self(
            StatusCode::PRECONDITION_REQUIRED,
            "PRECONDITION_REQUIRED",
            "precondition required",
        )
    }
    pub fn revision_mismatch() -> Self {
        Self(
            StatusCode::PRECONDITION_FAILED,
            "REVISION_MISMATCH",
            "revision mismatch",
        )
    }
    pub fn target_mismatch() -> Self {
        Self(
            StatusCode::PRECONDITION_FAILED,
            "TARGET_MISMATCH",
            "target mismatch",
        )
    }
    pub fn bad(message: &'static str) -> Self {
        Self(StatusCode::BAD_REQUEST, "VALIDATION", message)
    }
    pub fn conflict() -> Self {
        Self(
            StatusCode::CONFLICT,
            "SCOPE_CONFLICT",
            "resource scope or state conflicts",
        )
    }
    pub fn not_found() -> Self {
        Self(StatusCode::NOT_FOUND, "NOT_FOUND", "resource not found")
    }
}
impl From<sqlx::Error> for ApiError {
    fn from(e: sqlx::Error) -> Self {
        if let sqlx::Error::Database(ref d) = e
            && d.is_unique_violation()
        {
            return Self::state("NAME_CONFLICT");
        }
        tracing::error!(kind = "database", "database request failed");
        Self(
            StatusCode::SERVICE_UNAVAILABLE,
            "DEPENDENCY_UNAVAILABLE",
            "database unavailable",
        )
    }
}
impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let mut response = self.0.into_response();
        response.extensions_mut().insert(self);
        response
    }
}
async fn observe(mut req: Request, next: Next) -> Response {
    let request_id = uuid::Uuid::now_v7().to_string();
    req.headers_mut()
        .insert("x-request-id", request_id.parse().expect("UUID header"));
    let method = req.method().clone();
    let started = std::time::Instant::now();
    let mut response = next.run(req).await;
    let status = match response.status() {
        StatusCode::UNPROCESSABLE_ENTITY | StatusCode::UNSUPPORTED_MEDIA_TYPE => {
            StatusCode::BAD_REQUEST
        }
        value => value,
    };
    if status.is_client_error() || status.is_server_error() {
        let fallback = ApiError(
            status,
            if status == StatusCode::NOT_FOUND {
                "NOT_FOUND"
            } else {
                "VALIDATION"
            },
            "request rejected",
        );
        let e = response.extensions().get::<ApiError>().unwrap_or(&fallback);
        response = (
            status,
            Json(json!({"error":{"code":e.1,"message":e.2,"request_id":request_id}})),
        )
            .into_response();
    }
    if status == StatusCode::SERVICE_UNAVAILABLE {
        response
            .headers_mut()
            .insert("retry-after", "1".parse().unwrap());
    }
    response
        .headers_mut()
        .insert("x-request-id", request_id.parse().expect("UUID header"));
    tracing::info!(%request_id,%method,status=status.as_u16(),elapsed_ms=started.elapsed().as_millis(),"HTTP request");
    response
}
async fn authenticate(State(app): State<App>, req: Request, next: Next) -> Response {
    let supplied = req
        .headers()
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");
    let token = if req.uri().path().starts_with("/internal/v1/processing/") {
        &app.config.processor_token
    } else {
        &app.config.workspace_token
    };
    let expected = format!("Bearer {token}");
    if req.headers().get_all("authorization").iter().count() != 1
        || !bool::from(supplied.as_bytes().ct_eq(expected.as_bytes()))
    {
        return ApiError(
            StatusCode::UNAUTHORIZED,
            "UNAUTHENTICATED",
            "service authentication required",
        )
        .into_response();
    }
    next.run(req).await
}
pub fn router(app: App) -> Router {
    let private = Router::new()
        .route("/internal/v1/quota-buckets/ensure", post(ensure_bucket))
        .route("/internal/v1/filesystems/ensure", post(ensure_fs))
        .route("/internal/v1/quota-buckets/{id}", get(get_bucket))
        .route("/internal/v1/filesystems/{id}", get(get_fs))
        .route("/internal/v1/filesystems/{id}/delete", post(delete_fs))
        .route(
            "/internal/v1/quota-buckets/{id}/freeze",
            post(freeze_bucket),
        )
        .route(
            "/internal/v1/quota-buckets/{id}/complete-deletion",
            post(complete_bucket),
        )
        .route(
            "/internal/v1/quota-buckets/{id}/filesystems",
            get(bucket_filesystems),
        )
        .route(
            "/internal/v1/filesystems/{fs}/operations/{operation}",
            get(get_operation),
        )
        .route(
            "/internal/v1/filesystems/{fs}/files/{action}",
            post(file_action),
        )
        .route(
            "/internal/v1/filesystems/{fs}/uploads/{upload}/bytes",
            axum::routing::put(upload_bytes).layer(axum::extract::DefaultBodyLimit::max(
                app.config.inline_limit,
            )),
        )
        .route(
            "/internal/v1/filesystems/{fs}/uploads/{upload}/parts",
            post(upload_parts),
        )
        .merge(processing::router(&app))
        .merge(exports::router())
        .route_layer(middleware::from_fn_with_state(app.clone(), authenticate));
    Router::new()
        .merge(private)
        .route("/live", get(|| async { StatusCode::NO_CONTENT }))
        .route("/ready", get(ready))
        .layer(axum::extract::DefaultBodyLimit::max(8 * 1048576))
        .layer(middleware::from_fn(observe))
        .with_state(app)
}
async fn ready(State(app): State<App>) -> Response {
    if sqlx::query("SELECT 1").execute(&app.pool).await.is_err() {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    }
    match crate::temporal::check(&app).await {
        Ok(()) => StatusCode::NO_CONTENT.into_response(),
        Err(()) => StatusCode::SERVICE_UNAVAILABLE.into_response(),
    }
}
async fn ensure_bucket(
    State(app): State<App>,
    Json(input): Json<fs::EnsureBucket>,
) -> Result<Json<fs::Bucket>, ApiError> {
    Ok(Json(fs::ensure_bucket(&app.pool, input).await?))
}
async fn ensure_fs(
    State(app): State<App>,
    Json(input): Json<fs::EnsureFilesystem>,
) -> Result<Json<fs::Filesystem>, ApiError> {
    Ok(Json(
        fs::ensure_filesystem(&app.pool, input, app.config.max_nodes).await?,
    ))
}
async fn get_bucket(
    State(app): State<App>,
    axum::extract::Path(id): axum::extract::Path<uuid::Uuid>,
) -> Result<Json<serde_json::Value>, ApiError> {
    use sqlx::Row;
    let r = sqlx::query("SELECT id,limit_bytes,used_bytes,state FROM quota_buckets WHERE id=$1")
        .bind(id)
        .fetch_optional(&app.pool)
        .await?
        .ok_or_else(ApiError::not_found)?;
    Ok(Json(serde_json::json!({
        "id":id,"limit_bytes":r.get::<i64,_>("limit_bytes").to_string(),
        "used_bytes":r.get::<i64,_>("used_bytes").to_string(),"state":r.get::<String,_>("state"),
        "upload_limits":{"inline_limit_bytes":app.config.inline_limit.to_string(),"max_file_bytes":app.config.max_file_bytes.to_string(),
            "multipart_threshold_bytes":app.config.storage.multipart_threshold_bytes.to_string(),
            "multipart_part_bytes":app.config.storage.multipart_part_bytes.to_string()}
    })))
}
async fn get_fs(
    State(app): State<App>,
    axum::extract::Path(id): axum::extract::Path<uuid::Uuid>,
) -> Result<Json<fs::Filesystem>, ApiError> {
    use sqlx::Row;
    let r = sqlx::query("SELECT bucket_id,root_id,state FROM filesystems WHERE id=$1")
        .bind(id)
        .fetch_optional(&app.pool)
        .await?
        .ok_or_else(ApiError::not_found)?;
    Ok(Json(fs::Filesystem {
        id,
        bucket_id: r.get("bucket_id"),
        root_id: r.get("root_id"),
        state: r.get("state"),
    }))
}

async fn file_action(
    State(app): State<App>,
    axum::extract::Path((fs, action)): axum::extract::Path<(uuid::Uuid, String)>,
    headers: axum::http::HeaderMap,
    Json(r): Json<fs::nodes::Request>,
) -> Result<Response, ApiError> {
    use fs::nodes;
    let mut status = StatusCode::OK;
    let value = match action.as_str() {
        "uploads-create" => {
            status = StatusCode::CREATED;
            fs::uploads::create(&app, fs, r).await?
        }
        "uploads-finalize" => {
            fs::uploads::finalize(
                &app,
                fs,
                fs::nodes::needed(r.input.entry_id)?,
                r.scope.actor_id,
                r.input.parts,
            )
            .await?
        }
        "uploads-status" => {
            fs::uploads::status(
                &app,
                fs,
                fs::nodes::needed(r.input.entry_id)?,
                r.scope.actor_id,
            )
            .await?
        }
        "uploads-abort" => {
            fs::uploads::abort(
                &app,
                fs,
                fs::nodes::needed(r.input.entry_id)?,
                r.scope.actor_id,
            )
            .await?;
            return Ok(StatusCode::NO_CONTENT.into_response());
        }
        "artifact-status" => fs::artifacts::status(&app, fs, r).await?,
        "stat" | "list" | "batch-stat" | "trash-list" => nodes::read(&app, fs, &action, r).await?,
        "directories" | "text" => {
            status = StatusCode::CREATED;
            serde_json::to_value(nodes::create(&app, fs, &action, r).await?).unwrap()
        }
        "rename" | "move" | "replace-text" => {
            serde_json::to_value(nodes::modify(&app, fs, &action, r).await?).unwrap()
        }
        "trash" => fs::trash::trash(&app, fs, r).await?,
        "restore" => serde_json::to_value(fs::trash::restore(&app, fs, r).await?).unwrap(),
        "purge" => {
            if let Some(key) = r.input.request_key {
                let start = fs::deletion::Start {
                    filesystem_id: fs,
                    actor_id: r.scope.actor_id,
                    request_key: key,
                    entry_id: r.input.entry_id,
                    revision: r.input.revision.clone(),
                };
                if fs::deletion::existing(&app, &start).await?.is_some() {
                    let (code, value) = crate::temporal::start_deletion(&app, start).await?;
                    return Ok((code, Json(value)).into_response());
                }
            }
            match fs::trash::purge_file(&app, fs, r.clone()).await {
                Ok(()) => return Ok(StatusCode::NO_CONTENT.into_response()),
                Err(e)
                    if e.1 == "DURABLE_PURGE_REQUIRED"
                        || (e.1 == "TRASH_PURGING" && r.input.request_key.is_some()) =>
                {
                    let (code, value) = crate::temporal::start_deletion(
                        &app,
                        fs::deletion::Start {
                            filesystem_id: fs,
                            actor_id: r.scope.actor_id,
                            request_key: nodes::needed(r.input.request_key)?,
                            entry_id: r.input.entry_id,
                            revision: r.input.revision,
                        },
                    )
                    .await?;
                    status = code;
                    value
                }
                Err(e) => return Err(e),
            }
        }
        "copy" => match fs::copy::inline(&app, fs, r.clone()).await {
            Ok(v) => {
                status = StatusCode::CREATED;
                v
            }
            Err(e) if e.1 == "DURABLE_COPY_REQUIRED" => {
                let (code, value) = crate::temporal::start_copy(
                    &app,
                    fs::copy::Start {
                        filesystem_id: fs,
                        request: r,
                    },
                )
                .await?;
                status = code;
                value
            }
            Err(e) => return Err(e),
        },
        "content" => {
            return inline_content(&app, fs, r, &headers).await;
        }
        _ => return Err(ApiError::not_found()),
    };
    let etag = value
        .get("revision")
        .or_else(|| value.get("node").and_then(|n| n.get("revision")))
        .and_then(|v| v.as_str())
        .map(|revision| format!("\"{revision}\"").parse().unwrap());
    let mut response = (status, Json(value)).into_response();
    if let Some(etag) = etag {
        response.headers_mut().insert("etag", etag);
    }
    Ok(response)
}
async fn inline_content(
    app: &App,
    fs: uuid::Uuid,
    r: fs::nodes::Request,
    headers: &axum::http::HeaderMap,
) -> Result<Response, ApiError> {
    use sqlx::Row;
    let locator = fs::nodes::needed(r.input.locator)?;
    if locator
        .path
        .as_ref()
        .is_some_and(|path| path.ends_with('/') || path.ends_with("/."))
    {
        return Err(ApiError::bad("content requires a file payload path"));
    }
    let mut s = fs::nodes::session(app, fs, false).await?;
    let n = s.resolve(&r.scope, &locator).await?;
    if n.kind != "file" {
        return Err(ApiError::state("NOT_FILE"));
    }
    if r.input.revision.is_some() {
        n.revision(r.input.revision.as_deref())?;
    }
    let row =
        sqlx::query("SELECT storage_kind,inline_bytes,object_key FROM file_data WHERE node_id=$1")
            .bind(n.id)
            .fetch_one(&mut *s.tx)
            .await?;
    s.tx.commit().await?;
    if headers.get_all("range").iter().count() > 1 {
        return Err(ApiError(
            StatusCode::RANGE_NOT_SATISFIABLE,
            "INVALID_RANGE",
            "multiple ranges unsupported",
        ));
    }
    let size = n.size_bytes.parse::<u64>().unwrap();
    let range = fs::ranges::parse(
        headers
            .get("range")
            .map(|v| v.to_str())
            .transpose()
            .map_err(|_| ApiError::bad("invalid range header"))?,
        size,
    )?;
    let inline = row.get::<String, _>("storage_kind") == "inline";
    if !inline {
        let key: String = row.get("object_key");
        let url = crate::storage::download_url(app, &key, &n.name).await?;
        let mut response = StatusCode::TEMPORARY_REDIRECT.into_response();
        response.headers_mut().insert(
            "location",
            url.as_str()
                .parse()
                .map_err(|_| ApiError::bad("invalid download URL"))?,
        );
        response
            .headers_mut()
            .insert("cache-control", "private, no-store".parse().unwrap());
        response
            .headers_mut()
            .insert("etag", format!("\"{}\"", n.revision).parse().unwrap());
        return Ok(response);
    }
    let bytes: Vec<u8> = row.get("inline_bytes");
    let body = axum::body::Body::from(if let Some((a, b)) = range {
        bytes[a as usize..=b as usize].to_vec()
    } else {
        bytes
    });
    let mut response = body.into_response();
    if let Some((a, b)) = range {
        *response.status_mut() = StatusCode::PARTIAL_CONTENT;
        response.headers_mut().insert(
            "content-range",
            format!("bytes {a}-{b}/{size}").parse().unwrap(),
        );
    }
    let length = range.map(|(a, b)| b - a + 1).unwrap_or(size);
    for (k, v) in [
        ("content-type", "application/octet-stream"),
        ("content-length", &length.to_string()),
        ("content-disposition", "attachment"),
        ("cache-control", "private, no-store"),
        ("x-content-type-options", "nosniff"),
        ("accept-ranges", "bytes"),
        ("etag", &format!("\"{}\"", n.revision)),
    ] {
        response.headers_mut().insert(
            axum::http::HeaderName::from_bytes(k.as_bytes()).unwrap(),
            v.parse().unwrap(),
        );
    }
    Ok(response)
}

async fn upload_bytes(
    State(app): State<App>,
    axum::extract::Path((fs, id)): axum::extract::Path<(uuid::Uuid, uuid::Uuid)>,
    headers: axum::http::HeaderMap,
    body: axum::body::Body,
) -> Result<Json<serde_json::Value>, ApiError> {
    let actor = headers
        .get("x-actor-id")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| uuid::Uuid::parse_str(v).ok())
        .filter(|v| !v.is_nil())
        .ok_or_else(|| ApiError::bad("trusted actor required"))?;
    Ok(Json(
        fs::uploads::transfer(&app, fs, id, actor, body).await?,
    ))
}

async fn get_operation(
    State(app): State<App>,
    axum::extract::Path((fs, op)): axum::extract::Path<(uuid::Uuid, uuid::Uuid)>,
) -> Result<Json<serde_json::Value>, ApiError> {
    use sqlx::Row;
    let row = sqlx::query("SELECT o.*,g.pending,g.oldest FROM operations o JOIN filesystems f ON f.id=o.filesystem_id CROSS JOIN LATERAL (SELECT count(*) AS pending,min(updated_at) AS oldest FROM object_deletions d WHERE d.bucket_id=f.bucket_id AND d.state!='deleted') g WHERE o.id=$1 AND o.filesystem_id=$2")
        .bind(op)
        .bind(fs)
        .fetch_optional(&app.pool)
        .await?
        .ok_or_else(ApiError::not_found)?;
    let mut value = fs::copy::operation_value(&row);
    value["actor_id"] = serde_json::json!(row.get::<uuid::Uuid, _>("actor_id"));
    value["cleanup"] = json!({"bucket_pending_objects":row.get::<i64,_>("pending").to_string(),"oldest_pending_at":row.get::<Option<chrono::DateTime<chrono::Utc>>,_>("oldest")});
    Ok(Json(value))
}

async fn delete_fs(
    State(app): State<App>,
    axum::extract::Path(id): axum::extract::Path<uuid::Uuid>,
    Json(input): Json<fs::deletion::Start>,
) -> Result<Response, ApiError> {
    if input.filesystem_id != id || input.entry_id.is_some() || input.revision.is_some() {
        return Err(ApiError::bad("invalid deletion scope"));
    }
    let (status, value) = crate::temporal::start_deletion(&app, input).await?;
    Ok((status, Json(value)).into_response())
}
async fn freeze_bucket(
    State(app): State<App>,
    axum::extract::Path(id): axum::extract::Path<uuid::Uuid>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let changed=sqlx::query("UPDATE quota_buckets SET state=CASE WHEN state='active' THEN 'frozen' ELSE state END WHERE id=$1").bind(id).execute(&app.pool).await?.rows_affected();
    if changed != 1 {
        return Err(ApiError::not_found());
    }
    Ok(Json(json!({"id":id})))
}
#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct FilesystemPage {
    after: Option<uuid::Uuid>,
}
async fn bucket_filesystems(
    State(app): State<App>,
    axum::extract::Path(id): axum::extract::Path<uuid::Uuid>,
    axum::extract::Query(page): axum::extract::Query<FilesystemPage>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let state: Option<String> = sqlx::query_scalar("SELECT state FROM quota_buckets WHERE id=$1")
        .bind(id)
        .fetch_optional(&app.pool)
        .await?;
    if !matches!(state.as_deref(), Some("frozen" | "deleted")) {
        return Err(ApiError::state("BUCKET_NOT_FROZEN"));
    }
    let rows: Vec<uuid::Uuid> = sqlx::query_scalar(
        "SELECT id FROM filesystems WHERE bucket_id=$1 AND id>$2 ORDER BY id LIMIT 64",
    )
    .bind(id)
    .bind(page.after.unwrap_or(uuid::Uuid::nil()))
    .fetch_all(&app.pool)
    .await?;
    Ok(Json(json!({"items":rows})))
}
async fn complete_bucket(
    State(app): State<App>,
    axum::extract::Path(id): axum::extract::Path<uuid::Uuid>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let changed=sqlx::query("UPDATE quota_buckets b SET state='deleted' WHERE id=$1 AND state IN ('frozen','deleted') AND used_bytes=0 AND NOT EXISTS(SELECT 1 FROM filesystems WHERE bucket_id=b.id AND state!='deleted') AND NOT EXISTS(SELECT 1 FROM uploads WHERE bucket_id=b.id AND state IN ('created','transferring','uploaded'))").bind(id).execute(&app.pool).await?.rows_affected();
    if changed != 1 {
        return Err(ApiError::state("DELETION_INCOMPLETE"));
    }
    Ok(Json(json!({"id":id,"state":"deleted"})))
}

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct UploadParts {
    parts: Vec<fs::uploads::PartRequest>,
}
async fn upload_parts(
    State(app): State<App>,
    axum::extract::Path((fs, upload)): axum::extract::Path<(uuid::Uuid, uuid::Uuid)>,
    headers: axum::http::HeaderMap,
    Json(input): Json<UploadParts>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let actor = headers
        .get("x-actor-id")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.parse::<uuid::Uuid>().ok())
        .filter(|v| !v.is_nil())
        .ok_or_else(|| ApiError::bad("actor required"))?;
    Ok(Json(
        fs::uploads::part_urls(&app, fs, upload, actor, input.parts).await?,
    ))
}
