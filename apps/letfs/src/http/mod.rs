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
mod archive;
mod nodes;
mod processing;
mod trash;
mod uploads;
use subtle::ConstantTimeEq;
#[derive(Clone)]
pub struct App {
    pub pool: PgPool,
    pub config: Arc<Config>,
    pub storage: Arc<object_store::aws::AmazonS3>,
    pub signer: Arc<object_store::aws::AmazonS3>,
    pub temporal: temporalio_client::Client,
    pub archive_slots: Arc<tokio::sync::Semaphore>,
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
static HTTP_DURATION: std::sync::LazyLock<opentelemetry::metrics::Histogram<f64>> =
    std::sync::LazyLock::new(|| {
        opentelemetry::global::meter("letfs-http")
            .f64_histogram("http.server.request.duration")
            .with_unit("s")
            .build()
    });
static HTTP_REQUESTS: std::sync::LazyLock<opentelemetry::metrics::Counter<u64>> =
    std::sync::LazyLock::new(|| {
        opentelemetry::global::meter("letfs-http")
            .u64_counter("http.server.request.count")
            .build()
    });
async fn observe(mut req: Request, next: Next) -> Response {
    use opentelemetry::trace::FutureExt;
    use tracing::Instrument;
    use tracing_opentelemetry::OpenTelemetrySpanExt;
    let route = req
        .extensions()
        .get::<axum::extract::MatchedPath>()
        .map(|path| path.as_str())
        .unwrap_or("unmatched")
        .to_owned();
    let parent = opentelemetry::global::get_text_map_propagator(|propagator| {
        propagator.extract(&opentelemetry_http::HeaderExtractor(req.headers()))
    });
    let span = tracing::info_span!("HTTP request", otel.name = %format!("{} {}", req.method(), route), otel.kind = "server",
        http.request.method = %req.method(), http.route = %route, http.response.status_code = tracing::field::Empty,
        otel.status_code = tracing::field::Empty);
    let _ = span.set_parent(parent);
    let context = span.context();
    async move {
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
            [("content-type","application/problem+json"),("cache-control","no-store")],
            Json(json!({"type":"about:blank","title":status.canonical_reason().unwrap_or("Request failed"),"status":status.as_u16(),"detail":e.2,"code":e.1,"request_id":request_id})),
        ).into_response();
    }
    if status == StatusCode::SERVICE_UNAVAILABLE {
        response
            .headers_mut()
            .insert("retry-after", "1".parse().unwrap());
    }
    response
        .headers_mut()
        .insert("x-request-id", request_id.parse().expect("UUID header"));
    let attributes = [opentelemetry::KeyValue::new("http.request.method", method.to_string()),
        opentelemetry::KeyValue::new("http.route", route),
        opentelemetry::KeyValue::new("http.response.status_code", i64::from(status.as_u16()))];
    HTTP_DURATION.record(started.elapsed().as_secs_f64(), &attributes);
    HTTP_REQUESTS.add(1, &attributes);
    tracing::Span::current().record("http.response.status_code", status.as_u16());
    if status.is_server_error() { tracing::Span::current().record("otel.status_code", "ERROR"); }
    tracing::info!(%request_id,%method,status=status.as_u16(),elapsed_ms=started.elapsed().as_millis(),"HTTP request");
    response
    }.instrument(span).with_context(context).await
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
        .route("/internal/v1/quota-buckets/{id}", get(get_bucket))
        .route("/internal/v1/filesystems/{id}", get(get_fs))
        .route(
            "/internal/v1/filesystems/{fs}/files/{action}",
            post(file_action),
        )
        .merge(processing::router(&app))
        .merge(archive::router())
        .merge(nodes::router())
        .merge(uploads::router())
        .merge(trash::router())
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
    Json(value): Json<serde_json::Value>,
) -> Result<Response, ApiError> {
    if matches!(action.as_str(), "search" | "semantic-search") {
        let request =
            serde_json::from_value(value).map_err(|_| ApiError::bad("invalid search request"))?;
        let result = if action == "search" {
            fs::search::basic(&app, fs, request).await?
        } else {
            fs::search::semantic(&app, fs, request).await?
        };
        return Ok(Json(result).into_response());
    }
    let r: fs::nodes::Request =
        serde_json::from_value(value).map_err(|_| ApiError::bad("invalid file request"))?;
    use fs::nodes;
    let status = StatusCode::OK;
    let value = match action.as_str() {
        "batch-stat" => nodes::read(&app, fs, &action, r).await?,
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
        sqlx::query("SELECT storage_kind,inline_bytes,object_key FROM files WHERE node_id=$1")
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
        (
            "content-type",
            n.media_type
                .as_deref()
                .unwrap_or("application/octet-stream"),
        ),
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

#[cfg(test)]
mod telemetry_tests {
    use super::*;
    use opentelemetry::{global, trace::TracerProvider};
    use opentelemetry_sdk::{
        propagation::TraceContextPropagator,
        trace::{InMemorySpanExporter, SdkTracerProvider},
    };
    use std::io::Write;
    use std::sync::{Arc, Mutex};
    use tower::ServiceExt;
    use tracing::instrument::WithSubscriber;
    use tracing_subscriber::layer::SubscriberExt;

    struct LogWriter(Arc<Mutex<Vec<u8>>>);

    impl Write for LogWriter {
        fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
            self.0.lock().unwrap().extend_from_slice(bytes);
            Ok(bytes.len())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }

    #[tokio::test]
    async fn http_propagates_context_and_logs_without_signed_queries() {
        let exporter = InMemorySpanExporter::default();
        let provider = SdkTracerProvider::builder()
            .with_simple_exporter(exporter.clone())
            .build();
        global::set_text_map_propagator(TraceContextPropagator::new());
        let logs = Arc::new(Mutex::new(Vec::<u8>::new()));
        let output = logs.clone();
        let subscriber = tracing_subscriber::registry()
            .with(tracing_opentelemetry::layer().with_tracer(provider.tracer("letfs-test")))
            .with(
                tracing_subscriber::fmt::layer()
                    .event_format(crate::telemetry::CorrelatedJson)
                    .with_writer(move || LogWriter(output.clone())),
            );
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let upstream = Router::new().route(
            "/next",
            get(|headers: axum::http::HeaderMap| async move {
                assert!(
                    headers["traceparent"]
                        .to_str()
                        .unwrap()
                        .contains("1234567890abcdef1234567890abcdef")
                );
                assert!(!headers.contains_key("baggage"));
                StatusCode::NO_CONTENT
            }),
        );
        let server = tokio::spawn(async move { axum::serve(listener, upstream).await.unwrap() });
        let client = reqwest_middleware::ClientBuilder::new(reqwest::Client::new())
            .with(reqwest_tracing::TracingMiddleware::<
                crate::telemetry::HttpSpan,
            >::new())
            .build();
        let router = Router::new()
            .route(
                "/probe/{id}",
                get(move || {
                    let client = client.clone();
                    async move {
                        // Temporal's native plugin reads this same current OTel context.
                        use opentelemetry::trace::TraceContextExt;
                        assert_eq!(
                            opentelemetry::Context::current()
                                .span()
                                .span_context()
                                .trace_id()
                                .to_string(),
                            "1234567890abcdef1234567890abcdef"
                        );
                        let response = client
                            .get(format!(
                                "http://{address}/next?X-Amz-Signature=must-not-export"
                            ))
                            .send()
                            .await
                            .unwrap();
                        assert_eq!(response.status(), StatusCode::NO_CONTENT);
                        let closed = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
                        let closed_address = closed.local_addr().unwrap();
                        drop(closed);
                        assert!(
                            client
                                .get(format!(
                                    "http://{closed_address}/object?token=must-not-export"
                                ))
                                .send()
                                .await
                                .is_err()
                        );
                        StatusCode::NO_CONTENT
                    }
                }),
            )
            .layer(middleware::from_fn(observe));
        let response = router
            .oneshot(
                Request::builder()
                    .uri("/probe/123?token=must-not-export")
                    .header(
                        "traceparent",
                        "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01",
                    )
                    .header("baggage", "private=must-not-export")
                    .body(axum::body::Body::empty())
                    .unwrap(),
            )
            .with_subscriber(subscriber)
            .await
            .unwrap();
        server.abort();
        assert_eq!(response.status(), StatusCode::NO_CONTENT);
        let spans = exporter.get_finished_spans().unwrap();
        assert_eq!(spans.len(), 3);
        let inbound = spans
            .iter()
            .find(|span| span.span_kind == opentelemetry::trace::SpanKind::Server)
            .unwrap();
        let outbound = spans
            .iter()
            .find(|span| {
                span.span_kind == opentelemetry::trace::SpanKind::Client
                    && span.status == opentelemetry::trace::Status::Unset
            })
            .unwrap();
        assert_eq!(inbound.name, "GET /probe/{id}");
        assert_eq!(outbound.parent_span_id, inbound.span_context.span_id());
        assert!(
            spans
                .iter()
                .all(|span| span.span_context.trace_id().to_string()
                    == "1234567890abcdef1234567890abcdef")
        );
        assert!(!format!("{spans:?}").contains("must-not-export"));
        let logs = String::from_utf8(logs.lock().unwrap().clone()).unwrap();
        assert!(logs.contains("\"trace_id\":\"1234567890abcdef1234567890abcdef\""));
        assert!(logs.contains(&format!(
            "\"span_id\":\"{}\"",
            inbound.span_context.span_id()
        )));
        provider.shutdown().unwrap();
    }
}
