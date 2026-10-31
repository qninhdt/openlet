use super::{ApiError, App, nodes};
use crate::fs::{self, nodes::Input, paths::Locator};
use axum::{
    Json, Router,
    extract::{Path, Query, State},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    routing::get,
};
use serde::Deserialize;
use serde_json::Value;
use uuid::Uuid;

pub fn router() -> Router<App> {
    Router::new()
        .route("/internal/v1/filesystems/{fs}/trash-entries", get(list))
        .route(
            "/internal/v1/filesystems/{fs}/trash-entries/{entry}",
            get(get_entry).delete(purge),
        )
        .route(
            "/internal/v1/filesystems/{fs}/trash-entries/{entry}/restore",
            axum::routing::post(restore),
        )
}
#[derive(Default, Deserialize)]
#[serde(deny_unknown_fields)]
struct Page {
    cursor: Option<String>,
    limit: Option<usize>,
}
async fn list(
    State(app): State<App>,
    Path(fs): Path<Uuid>,
    headers: HeaderMap,
    Query(page): Query<Page>,
) -> Result<Json<Value>, ApiError> {
    nodes::scope(fs, &headers)?;
    let mut s = fs::nodes::session(&app, fs, false).await?;
    Ok(Json(
        fs::trash::list(
            &mut s,
            &Input {
                cursor: page.cursor,
                limit: page.limit,
                ..Default::default()
            },
        )
        .await?,
    ))
}
async fn entry(app: &App, fs: Uuid, id: Uuid) -> Result<Option<Value>, ApiError> {
    let mut s = fs::nodes::session(app, fs, false).await?;
    fs::trash::entry(&mut s, id).await
}
async fn get_entry(
    State(app): State<App>,
    Path((fs, id)): Path<(Uuid, Uuid)>,
    headers: HeaderMap,
) -> Result<Json<Value>, ApiError> {
    nodes::scope(fs, &headers)?;
    Ok(Json(
        entry(&app, fs, id).await?.ok_or_else(ApiError::not_found)?,
    ))
}
pub(super) async fn trash(
    State(app): State<App>,
    Path((fs, node)): Path<(Uuid, Uuid)>,
    headers: HeaderMap,
) -> Result<Response, ApiError> {
    let r = fs::nodes::Request {
        scope: nodes::scope(fs, &headers)?,
        input: Input {
            locator: Some(Locator {
                node_id: Some(node),
                path: None,
                cwd_id: None,
                expected_node_id: None,
                expected_parent_id: None,
            }),
            revision: Some(nodes::revision(&headers)?),
            ..Default::default()
        },
    };
    let result = fs::trash::trash(&app, fs, r).await?;
    let id: Uuid = serde_json::from_value(result["id"].clone())
        .map_err(|_| ApiError::state("INVALID_TRASH_ENTRY"))?;
    Ok((
        StatusCode::CREATED,
        [(
            "location",
            format!("/internal/v1/filesystems/{fs}/trash-entries/{id}"),
        )],
        Json(result),
    )
        .into_response())
}
async fn restore(
    State(app): State<App>,
    Path((fs, id)): Path<(Uuid, Uuid)>,
    headers: HeaderMap,
) -> Result<Response, ApiError> {
    let r = fs::nodes::Request {
        scope: nodes::scope(fs, &headers)?,
        input: Input {
            entry_id: Some(id),
            ..Default::default()
        },
    };
    let node = fs::trash::restore(&app, fs, r).await?;
    Ok(([("etag", format!("\"{}\"", node.revision))], Json(node)).into_response())
}
async fn purge(
    State(app): State<App>,
    Path((fs, id)): Path<(Uuid, Uuid)>,
    headers: HeaderMap,
) -> Result<Response, ApiError> {
    let scope = nodes::scope(fs, &headers)?;
    if entry(&app, fs, id).await?.is_none() {
        return Ok(StatusCode::NO_CONTENT.into_response());
    }
    let input = fs::deletion::prepare(
        &app,
        fs::deletion::Start {
            filesystem_id: fs,
            actor_id: scope.actor_id,
            entry_id: Some(id),
            revision: None,
        },
    )
    .await?;
    let value = entry(&app, fs, id).await?;
    // The purging entry is durable admission; maintenance retries a dispatch outage.
    if crate::temporal::start_deletion(&app, input).await.is_err() {
        tracing::warn!("trash purge dispatch deferred");
    }
    Ok(match value {
        Some(value) => (
            StatusCode::ACCEPTED,
            [(
                "location",
                format!("/internal/v1/filesystems/{fs}/trash-entries/{id}"),
            )],
            Json(value),
        )
            .into_response(),
        None => StatusCode::NO_CONTENT.into_response(),
    })
}
