use super::{ApiError, App};
use crate::fs::{nodes, uploads};
use axum::{
    Json, Router,
    extract::{Path, Query, State},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post, put},
};
use serde::Deserialize;
use uuid::Uuid;

pub fn router() -> Router<App> {
    Router::new()
        .route("/internal/v1/filesystems/{fs}/uploads", post(create))
        .route(
            "/internal/v1/filesystems/{fs}/uploads/{upload}",
            get(status).delete(abort),
        )
        .route(
            "/internal/v1/filesystems/{fs}/uploads/{upload}/parts",
            get(parts),
        )
        .route(
            "/internal/v1/filesystems/{fs}/uploads/{upload}/completion",
            put(complete),
        )
}
fn actor(headers: &HeaderMap) -> Result<Uuid, ApiError> {
    if headers.get_all("x-actor-id").iter().count() != 1 {
        return Err(ApiError::bad("trusted actor required"));
    }
    headers
        .get("x-actor-id")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| Uuid::parse_str(v).ok())
        .filter(|v| !v.is_nil())
        .ok_or_else(|| ApiError::bad("trusted actor required"))
}
fn json(status: StatusCode, value: serde_json::Value) -> Response {
    let mut response = (status, Json(value)).into_response();
    response
        .headers_mut()
        .insert("cache-control", "no-store".parse().unwrap());
    response
}
async fn create(
    State(app): State<App>,
    Path(fs): Path<Uuid>,
    Json(input): Json<nodes::Request>,
) -> Result<Response, ApiError> {
    let media_type = input
        .input
        .media_type
        .as_deref()
        .ok_or_else(|| ApiError::bad("media_type required"))?;
    nodes::media_type(media_type)?;
    if !matches!(input.input.storage, Some(uploads::StorageMode::Object)) {
        return Err(ApiError::bad("inline content uses nodes directly"));
    }
    let value = uploads::create(&app, fs, input).await?;
    let location = format!(
        "/internal/v1/filesystems/{fs}/uploads/{}",
        value["id"].as_str().unwrap()
    );
    let mut response = json(StatusCode::CREATED, value);
    response
        .headers_mut()
        .insert("location", location.parse().unwrap());
    Ok(response)
}
async fn status(
    State(app): State<App>,
    Path((fs, id)): Path<(Uuid, Uuid)>,
    headers: HeaderMap,
) -> Result<Response, ApiError> {
    Ok(json(
        StatusCode::OK,
        uploads::status(&app, fs, id, actor(&headers)?).await?,
    ))
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Parts {
    numbers: String,
}
async fn parts(
    State(app): State<App>,
    Path((fs, id)): Path<(Uuid, Uuid)>,
    headers: HeaderMap,
    Query(input): Query<Parts>,
) -> Result<Response, ApiError> {
    if input.numbers.len() > 384 {
        return Err(ApiError::bad("part signing batch exceeds limit"));
    }
    let numbers = input
        .numbers
        .split(',')
        .map(|v| {
            v.parse::<u32>()
                .ok()
                .filter(|n| n.to_string() == v)
                .ok_or_else(|| ApiError::bad("invalid part number"))
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(json(
        StatusCode::OK,
        uploads::part_urls(&app, fs, id, actor(&headers)?, numbers).await?,
    ))
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Completion {
    parts: Option<Vec<uploads::Receipt>>,
}
async fn complete(
    State(app): State<App>,
    Path((fs, id)): Path<(Uuid, Uuid)>,
    headers: HeaderMap,
    Json(input): Json<Completion>,
) -> Result<Response, ApiError> {
    Ok(json(
        StatusCode::OK,
        uploads::finalize(&app, fs, id, actor(&headers)?, input.parts).await?,
    ))
}
async fn abort(
    State(app): State<App>,
    Path((fs, id)): Path<(Uuid, Uuid)>,
    headers: HeaderMap,
) -> Result<StatusCode, ApiError> {
    uploads::abort(&app, fs, id, actor(&headers)?).await?;
    Ok(StatusCode::NO_CONTENT)
}
