use super::{ApiError, App};
use crate::fs::{enrichment, processing, uploads};
use axum::{
    Json, Router,
    body::Body,
    extract::{Path, State},
    routing::{post, put},
};
use serde::Deserialize;
use serde_json::Value;
use uuid::Uuid;

pub fn router(app: &App) -> Router<App> {
    Router::new()
        .route(
            "/internal/v1/processing/{operation}/index/{action}",
            post(index_action),
        )
        .route(
            "/internal/v1/processing/{operation}/enrichment/{action}",
            post(enrichment_action),
        )
        .route(
            "/internal/v1/processing/{operation}/enrichment/uploads/{upload}/{action}",
            post(enrichment_upload),
        )
        .route(
            "/internal/v1/processing/{operation}/enrichment/uploads/{upload}/bytes",
            put(enrichment_bytes).layer(axum::extract::DefaultBodyLimit::max(
                app.config.inline_limit,
            )),
        )
        .route(
            "/internal/v1/processing/{operation}/{generation}/{attempt}/{action}",
            post(action),
        )
        .route(
            "/internal/v1/processing/{operation}/{generation}/{attempt}/uploads/{upload}/{action}",
            post(upload_action),
        )
        .route(
            "/internal/v1/processing/{operation}/{generation}/{attempt}/uploads/{upload}/bytes",
            put(bytes).layer(axum::extract::DefaultBodyLimit::max(
                app.config.inline_limit,
            )),
        )
}
async fn index_action(
    State(app): State<App>,
    Path((op, action)): Path<(Uuid, String)>,
    Json(value): Json<Value>,
) -> Result<Json<Value>, ApiError> {
    use crate::fs::indexing;
    Ok(Json(match action.as_str() {
        "prepare" => {
            parse::<Empty>(value)?;
            indexing::prepare(&app, op).await?
        }
        "complete" => {
            parse::<Empty>(value)?;
            indexing::complete(&app, op).await?
        }
        "fail" => {
            let input: Abort = parse(value)?;
            indexing::fail(&app, op, &input.code).await?;
            serde_json::json!({"state":"failed"})
        }
        _ => return Err(ApiError::not_found()),
    }))
}
async fn enrichment_action(
    State(app): State<App>,
    Path((op, action)): Path<(Uuid, String)>,
    Json(value): Json<Value>,
) -> Result<Json<Value>, ApiError> {
    Ok(Json(match action.as_str() {
        "prepare" => {
            parse::<Empty>(value)?;
            enrichment::prepare(&app, op).await?
        }
        "outputs" => enrichment::prepare_output(&app, op, parse(value)?).await?,
        "complete" => enrichment::complete(&app, op, parse(value)?).await?,
        "fail" => {
            let input: Abort = parse(value)?;
            enrichment::fail(&app, op, &input.code).await?;
            serde_json::json!({"state":"failed"})
        }
        _ => return Err(ApiError::not_found()),
    }))
}
async fn enrichment_upload(
    State(app): State<App>,
    Path((op, upload, action)): Path<(Uuid, Uuid, String)>,
    Json(value): Json<Value>,
) -> Result<Json<Value>, ApiError> {
    let s = processing::open(&app, op, false).await?;
    let fs = s.fs;
    drop(s);
    let access = uploads::Access::Enrichment(op);
    Ok(Json(match action.as_str() {
        "status" => {
            parse::<Empty>(value)?;
            uploads::status(&app, fs, upload, access).await?
        }
        "parts" => {
            let input: Parts = parse(value)?;
            uploads::part_urls(&app, fs, upload, access, input.parts).await?
        }
        "complete" => {
            let input: Finalize = parse(value)?;
            uploads::finalize(&app, fs, upload, access, input.parts).await?
        }
        _ => return Err(ApiError::not_found()),
    }))
}
async fn enrichment_bytes(
    State(app): State<App>,
    Path((op, upload)): Path<(Uuid, Uuid)>,
    body: Body,
) -> Result<Json<Value>, ApiError> {
    let s = processing::open(&app, op, false).await?;
    let fs = s.fs;
    drop(s);
    Ok(Json(
        uploads::transfer(&app, fs, upload, uploads::Access::Enrichment(op), body).await?,
    ))
}
fn attempt((operation_id, generation, attempt_id): (Uuid, i32, Uuid)) -> processing::Attempt {
    processing::Attempt {
        operation_id,
        generation,
        attempt_id,
    }
}
async fn action(
    State(app): State<App>,
    Path((op, generation, id, action)): Path<(Uuid, i32, Uuid, String)>,
    Json(value): Json<Value>,
) -> Result<Json<Value>, ApiError> {
    let attempt = attempt((op, generation, id));
    let value = match action.as_str() {
        "prepare" => {
            parse::<Empty>(value)?;
            processing::prepare(&app, &attempt).await?
        }
        "outputs" => processing::prepare_output(&app, &attempt, parse(value)?).await?,
        "complete" => processing::complete(&app, &attempt, parse(value)?).await?,
        "abort" => {
            let input: Abort = parse(value)?;
            processing::abort(&app, &attempt, &input.code).await?;
            serde_json::json!({"state":"failed"})
        }
        _ => return Err(ApiError::not_found()),
    };
    Ok(Json(value))
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Empty {}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Abort {
    code: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Parts {
    parts: Vec<uploads::PartRequest>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Finalize {
    parts: Option<Vec<uploads::Receipt>>,
}
fn parse<T: serde::de::DeserializeOwned>(value: Value) -> Result<T, ApiError> {
    serde_json::from_value(value).map_err(|_| ApiError::bad("invalid processing request"))
}
async fn upload_action(
    State(app): State<App>,
    Path((op, generation, id, upload, action)): Path<(Uuid, i32, Uuid, Uuid, String)>,
    Json(value): Json<Value>,
) -> Result<Json<Value>, ApiError> {
    let attempt = attempt((op, generation, id));
    let s = processing::open(&app, op, false).await?;
    let fs = s.fs;
    drop(s);
    let access = uploads::Access::Processor(attempt);
    let value = match action.as_str() {
        "status" => {
            parse::<Empty>(value)?;
            uploads::status(&app, fs, upload, access).await?
        }
        "parts" => {
            let input: Parts = parse(value)?;
            uploads::part_urls(&app, fs, upload, access, input.parts).await?
        }
        "complete" => {
            let input: Finalize = parse(value)?;
            uploads::finalize(&app, fs, upload, access, input.parts).await?
        }
        _ => return Err(ApiError::not_found()),
    };
    Ok(Json(value))
}
async fn bytes(
    State(app): State<App>,
    Path((op, generation, id, upload)): Path<(Uuid, i32, Uuid, Uuid)>,
    body: Body,
) -> Result<Json<Value>, ApiError> {
    let s = processing::open(&app, op, false).await?;
    let fs = s.fs;
    drop(s);
    Ok(Json(
        uploads::transfer(
            &app,
            fs,
            upload,
            uploads::Access::Processor(attempt((op, generation, id))),
            body,
        )
        .await?,
    ))
}
