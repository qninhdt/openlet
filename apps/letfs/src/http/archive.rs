use super::{ApiError, App};
use crate::fs::{archive, paths::Scope};
use axum::{
    Json, Router,
    body::Body,
    extract::{Path, State},
    response::{IntoResponse, Response},
    routing::post,
};
use serde::Deserialize;
use uuid::Uuid;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Access {
    scope: Scope,
}

pub fn router() -> Router<App> {
    Router::new().route(
        "/internal/v1/filesystems/{fs}/nodes/{node}/archive",
        post(download),
    )
}
async fn download(
    State(app): State<App>,
    Path((fs, node)): Path<(Uuid, Uuid)>,
    Json(body): Json<Access>,
) -> Result<Response, ApiError> {
    let permit = app.archive_slots.clone().try_acquire_owned().map_err(|_| {
        ApiError(
            axum::http::StatusCode::TOO_MANY_REQUESTS,
            "RESOURCE_LIMIT",
            "archive concurrency limit",
        )
    })?;
    let deadline = crate::storage::archive::deadline(&app);
    let archive =
        tokio::time::timeout_at(deadline, archive::preflight(&app, fs, node, &body.scope))
            .await
            .map_err(|_| ApiError::state("RESOURCE_LIMIT"))??;
    let name = url::form_urlencoded::byte_serialize(archive.name.as_bytes())
        .collect::<String>()
        .replace('+', "%20");
    let mut response = Body::from_stream(crate::storage::archive::stream(
        app, archive, permit, deadline,
    ))
    .into_response();
    for (key, value) in [
        ("content-type", "application/zip".into()),
        ("cache-control", "private, no-store".into()),
        ("x-content-type-options", "nosniff".into()),
        (
            "content-disposition",
            format!("attachment; filename=\"download.zip\"; filename*=UTF-8''{name}"),
        ),
    ] {
        response.headers_mut().insert(
            axum::http::HeaderName::from_bytes(key.as_bytes()).unwrap(),
            value.parse().unwrap(),
        );
    }
    Ok(response)
}
