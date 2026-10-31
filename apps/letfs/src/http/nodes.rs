use super::{ApiError, App};
use crate::fs::{
    nodes,
    paths::{Locator, Mount, Scope},
};
use axum::{
    Json, Router,
    extract::{Path, Query, State},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post},
};
use serde::Deserialize;
use uuid::Uuid;

#[derive(Default, Deserialize)]
#[serde(deny_unknown_fields)]
struct Read {
    parent_id: Option<Uuid>,
    node_id: Option<Uuid>,
    path: Option<String>,
    cwd_id: Option<Uuid>,
    expected_node_id: Option<Uuid>,
    expected_parent_id: Option<Uuid>,
    limit: Option<usize>,
    cursor: Option<String>,
    revision: Option<String>,
}
pub(super) fn scope(fs: Uuid, headers: &HeaderMap) -> Result<Scope, ApiError> {
    let actor = headers
        .get("x-actor-id")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| Uuid::parse_str(v).ok())
        .filter(|v| !v.is_nil())
        .ok_or_else(|| ApiError::bad("trusted actor required"))?;
    if headers.get_all("x-actor-id").iter().count() != 1 {
        return Err(ApiError::bad("trusted actor required"));
    }
    Ok(Scope {
        actor_id: actor,
        mounts: vec![Mount {
            path: "/drive".into(),
            filesystem_id: fs,
        }],
    })
}
fn request(
    fs: Uuid,
    headers: &HeaderMap,
    query: Read,
    node: Option<Uuid>,
    list: bool,
) -> Result<nodes::Request, ApiError> {
    if query.parent_id.is_some()
        && (!list || query.node_id.is_some() || query.path.is_some() || query.cwd_id.is_some())
    {
        return Err(ApiError::bad("invalid parent locator"));
    }
    if node.is_some()
        && (query.parent_id.is_some()
            || query.node_id.is_some()
            || query.path.is_some()
            || query.cwd_id.is_some())
    {
        return Err(ApiError::bad("route identity cannot be overridden"));
    }
    let node_id = node.or(query.parent_id).or(query.node_id);
    let locator = Locator {
        node_id,
        path: query
            .path
            .or_else(|| (list && node_id.is_none()).then(|| "/drive".into())),
        cwd_id: query.cwd_id,
        expected_node_id: query.expected_node_id,
        expected_parent_id: query.expected_parent_id,
    };
    let input = nodes::Input {
        locator: Some(locator),
        limit: query.limit,
        cursor: query.cursor,
        revision: query.revision,
        ..Default::default()
    };
    Ok(nodes::Request {
        scope: scope(fs, headers)?,
        input,
    })
}
fn response(status: StatusCode, node: nodes::Node) -> Response {
    let etag = format!("\"{}\"", node.revision);
    let mut response = (status, Json(node)).into_response();
    response.headers_mut().insert("etag", etag.parse().unwrap());
    response
}
pub fn router() -> Router<App> {
    Router::new()
        .route(
            "/internal/v1/filesystems/{fs}/nodes",
            post(create).get(list),
        )
        .route(
            "/internal/v1/filesystems/{fs}/copies/{copy}",
            get(copy_status),
        )
        .route("/internal/v1/filesystems/{fs}/nodes/resolve", get(resolve))
        .route(
            "/internal/v1/filesystems/{fs}/nodes/{node}",
            get(stat).patch(patch).delete(super::trash::trash),
        )
        .route(
            "/internal/v1/filesystems/{fs}/nodes/{node}/processing",
            get(processing_status),
        )
        .route(
            "/internal/v1/filesystems/{fs}/nodes/{node}/processing-runs",
            post(reprocess),
        )
        .route(
            "/internal/v1/filesystems/{fs}/nodes/{node}/content",
            get(content).put(replace),
        )
}
#[derive(Deserialize)]
#[serde(untagged)]
enum Creation {
    Node(nodes::Create),
    Copy(crate::fs::copy::Request),
}
async fn copy_status(
    State(app): State<App>,
    Path((fs, id)): Path<(Uuid, Uuid)>,
    headers: HeaderMap,
) -> Result<Json<serde_json::Value>, ApiError> {
    let scope = scope(fs, &headers)?;
    let owner = headers
        .get("x-workspace-role")
        .is_some_and(|v| v == "owner");
    let value = tokio::time::timeout(
        std::time::Duration::from_secs(5),
        crate::temporal::copy_workflow::monitor(&app, fs, id, scope.actor_id, owner),
    )
    .await
    .map_err(|_| {
        ApiError(
            StatusCode::SERVICE_UNAVAILABLE,
            "DEPENDENCY_UNAVAILABLE",
            "Temporal unavailable",
        )
    })??;
    Ok(Json(value))
}
async fn create(
    State(app): State<App>,
    Path(fs): Path<Uuid>,
    Json(body): Json<Creation>,
) -> Result<Response, ApiError> {
    let body = match body {
        Creation::Node(body) => body,
        Creation::Copy(body) => {
            let admission = crate::fs::copy::admit(&app, fs, body).await?;
            if let Err(e) = crate::temporal::start_copy(&app, admission.clone()).await {
                tracing::warn!(code = e.1, "copy dispatch deferred");
            }
            let mut out = (StatusCode::ACCEPTED, Json(admission.value())).into_response();
            out.headers_mut().insert(
                "location",
                format!("/internal/v1/filesystems/{fs}/copies/{}", admission.id)
                    .parse()
                    .unwrap(),
            );
            return Ok(out);
        }
    };
    let node = nodes::create(&app, fs, body).await?;
    let location = format!("/internal/v1/filesystems/{fs}/nodes/{}", node.id);
    let mut out = response(StatusCode::CREATED, node);
    out.headers_mut()
        .insert("location", location.parse().unwrap());
    Ok(out)
}
async fn list(
    State(app): State<App>,
    Path(fs): Path<Uuid>,
    headers: HeaderMap,
    Query(query): Query<Read>,
) -> Result<Json<serde_json::Value>, ApiError> {
    Ok(Json(
        nodes::read(&app, fs, "list", request(fs, &headers, query, None, true)?).await?,
    ))
}
async fn resolve(
    State(app): State<App>,
    Path(fs): Path<Uuid>,
    headers: HeaderMap,
    Query(query): Query<Read>,
) -> Result<Response, ApiError> {
    let value = nodes::read(&app, fs, "stat", request(fs, &headers, query, None, false)?).await?;
    Ok(response(
        StatusCode::OK,
        serde_json::from_value(value).map_err(|_| ApiError::state("INVALID_NODE"))?,
    ))
}
async fn stat(
    State(app): State<App>,
    Path((fs, node)): Path<(Uuid, Uuid)>,
    headers: HeaderMap,
    Query(query): Query<Read>,
) -> Result<Response, ApiError> {
    let value = nodes::read(
        &app,
        fs,
        "stat",
        request(fs, &headers, query, Some(node), false)?,
    )
    .await?;
    Ok(response(
        StatusCode::OK,
        serde_json::from_value(value).map_err(|_| ApiError::state("INVALID_NODE"))?,
    ))
}
async fn content(
    State(app): State<App>,
    Path((fs, node)): Path<(Uuid, Uuid)>,
    headers: HeaderMap,
    Query(query): Query<Read>,
) -> Result<Response, ApiError> {
    if headers.contains_key("if-match") {
        return Err(ApiError::bad("use revision query for content reads"));
    }
    super::inline_content(
        &app,
        fs,
        request(fs, &headers, query, Some(node), false)?,
        &headers,
    )
    .await
}

pub(super) fn revision(headers: &HeaderMap) -> Result<String, ApiError> {
    let value = headers
        .get("if-match")
        .ok_or_else(ApiError::precondition_required)?
        .to_str()
        .map_err(|_| ApiError::bad("invalid If-Match"))?;
    let digits = value
        .strip_prefix('"')
        .and_then(|v| v.strip_suffix('"'))
        .ok_or_else(|| ApiError::bad("invalid If-Match"))?;
    if headers.get_all("if-match").iter().count() != 1
        || digits
            .parse::<i64>()
            .ok()
            .is_none_or(|n| n <= 0 || n.to_string() != digits)
    {
        return Err(ApiError::bad("invalid If-Match"));
    }
    Ok(digits.into())
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Patch {
    name: Option<String>,
    parent_id: Option<Uuid>,
}
async fn patch(
    State(app): State<App>,
    Path((fs, node)): Path<(Uuid, Uuid)>,
    headers: HeaderMap,
    Json(body): Json<Patch>,
) -> Result<Response, ApiError> {
    if body.name.is_none() && body.parent_id.is_none() {
        return Err(ApiError::bad("node patch is empty"));
    }
    let mut r = request(fs, &headers, Read::default(), Some(node), false)?;
    r.input.revision = Some(revision(&headers)?);
    r.input.name = body.name;
    r.input.parent = body.parent_id.map(|id| Locator {
        node_id: Some(id),
        path: None,
        cwd_id: None,
        expected_node_id: None,
        expected_parent_id: None,
    });
    let action = if r.input.parent.is_some() {
        "move"
    } else {
        "rename"
    };
    Ok(response(
        StatusCode::OK,
        nodes::modify(&app, fs, action, r).await?,
    ))
}
async fn replace(
    State(app): State<App>,
    Path((fs, node)): Path<(Uuid, Uuid)>,
    headers: HeaderMap,
    body: axum::body::Body,
) -> Result<Response, ApiError> {
    let mut r = request(fs, &headers, Read::default(), Some(node), false)?;
    r.input.revision = Some(revision(&headers)?);
    r.input.media_type = Some(
        headers
            .get("content-type")
            .map(|v| v.to_str())
            .transpose()
            .map_err(|_| ApiError::bad("invalid media_type"))?
            .unwrap_or("application/octet-stream")
            .into(),
    );
    use futures::TryStreamExt;
    let limit = app
        .config
        .inline_limit
        .min(app.config.max_file_bytes as usize);
    let mut input = body.into_data_stream();
    let mut bytes = Vec::new();
    while let Some(chunk) = input
        .try_next()
        .await
        .map_err(|_| ApiError::bad("incomplete request body"))?
    {
        if chunk.len() > limit - bytes.len() {
            return Err(ApiError(
                StatusCode::PAYLOAD_TOO_LARGE,
                "REQUEST_LIMIT",
                "inline content exceeds limit",
            ));
        }
        bytes.extend_from_slice(&chunk);
    }
    r.input.content = Some(bytes);
    Ok(response(
        StatusCode::OK,
        nodes::modify(&app, fs, "replace-content", r).await?,
    ))
}

async fn processing_status(
    State(app): State<App>,
    Path((fs, node)): Path<(Uuid, Uuid)>,
    headers: HeaderMap,
    Query(query): Query<Read>,
) -> Result<Json<serde_json::Value>, ApiError> {
    Ok(Json(
        crate::fs::artifacts::status(&app, fs, request(fs, &headers, query, Some(node), false)?)
            .await?,
    ))
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Empty {}
async fn reprocess(
    State(app): State<App>,
    Path((fs, node)): Path<(Uuid, Uuid)>,
    headers: HeaderMap,
    Json(_): Json<Empty>,
) -> Result<Response, ApiError> {
    let key = headers
        .get("idempotency-key")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| Uuid::parse_str(v).ok())
        .filter(|v| !v.is_nil())
        .ok_or_else(|| ApiError::bad("idempotency key required"))?;
    if headers.get_all("idempotency-key").iter().count() != 1 {
        return Err(ApiError::bad("one idempotency key required"));
    }
    let mut r = request(fs, &headers, Read::default(), Some(node), false)?;
    r.input.request_key = Some(key);
    Ok((
        StatusCode::ACCEPTED,
        Json(crate::fs::artifacts::reprocess(&app, fs, r).await?),
    )
        .into_response())
}
