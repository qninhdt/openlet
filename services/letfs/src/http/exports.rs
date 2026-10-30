use super::{ApiError, App};
use crate::fs::{exports, paths::Scope};
use axum::{
    Json, Router,
    extract::{Path, State},
    response::{IntoResponse, Response},
    routing::post,
};
use serde::Deserialize;
use uuid::Uuid;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Create {
    scope: Scope,
    input: exports::Selection,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Access {
    scope: Scope,
}
pub fn router() -> Router<App> {
    Router::new()
        .route("/internal/v1/filesystems/{fs}/exports", post(create))
        .route(
            "/internal/v1/filesystems/{fs}/exports/{id}/{action}",
            post(access),
        )
}
async fn create(
    State(app): State<App>,
    Path(fs): Path<Uuid>,
    Json(body): Json<Create>,
) -> Result<Response, ApiError> {
    let (status, value) = crate::temporal::export_archive_workflow::start(
        &app,
        exports::Start {
            filesystem_id: fs,
            scope: body.scope,
            selection: body.input,
        },
    )
    .await?;
    Ok((status, Json(value)).into_response())
}
async fn access(
    State(app): State<App>,
    Path((fs, id, action)): Path<(Uuid, Uuid, String)>,
    Json(body): Json<Access>,
) -> Result<Json<serde_json::Value>, ApiError> {
    if !body.scope.mounts.iter().any(|m| m.filesystem_id == fs) {
        return Err(ApiError::not_found());
    }
    if !matches!(action.as_str(), "status" | "download") {
        return Err(ApiError::not_found());
    }
    Ok(Json(
        exports::status(&app, fs, body.scope.actor_id, id, action == "download").await?,
    ))
}
