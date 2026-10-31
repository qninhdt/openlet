use super::{ApiError, App};
use crate::fs::{
    enrichment, indexing,
    processing::{self, Attempt, Generation},
    uploads,
};
use axum::{
    Json, Router,
    body::Body,
    extract::{Path, State},
    routing::{post, put},
};
use serde::Deserialize;
use serde_json::{Value, json};
use uuid::Uuid;

pub fn router(app: &App) -> Router<App> {
    Router::new()
        .route("/internal/v1/processing/{file}/{generation}/index/{action}",post(index_action))
        .route("/internal/v1/processing/{file}/{generation}/{stage}/{number}/{attempt}/{action}",post(action))
        .route("/internal/v1/processing/{file}/{generation}/{stage}/{number}/{attempt}/uploads/{upload}/{action}",post(upload_action))
        .route("/internal/v1/processing/{file}/{generation}/{stage}/{number}/{attempt}/uploads/{upload}/bytes",put(bytes).layer(axum::extract::DefaultBodyLimit::max(app.config.inline_limit)))
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Empty {}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Failure {
    code: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Indexed {
    vector_space: indexing::VectorSpace,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct IndexFailure {
    code: String,
    vector_space: indexing::VectorSpace,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Parts {
    parts: Vec<u32>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Finalize {
    parts: Option<Vec<uploads::Receipt>>,
}
fn parse<T: serde::de::DeserializeOwned>(value: Value) -> Result<T, ApiError> {
    serde_json::from_value(value).map_err(|_| ApiError::bad("invalid processing request"))
}
fn attempt(file_id: Uuid, generation: i64, number: i32, attempt_id: Uuid) -> Attempt {
    Attempt {
        source: Generation {
            file_id,
            generation,
        },
        number,
        attempt_id,
    }
}
fn access(stage: &str, attempt: Attempt) -> Result<uploads::Access, ApiError> {
    match stage {
        "parse" => Ok(uploads::Access::Processor(attempt)),
        "enrichment" => Ok(uploads::Access::Enrichment(attempt)),
        _ => Err(ApiError::not_found()),
    }
}
async fn index_action(
    State(app): State<App>,
    Path((file_id, generation, action)): Path<(Uuid, i64, String)>,
    Json(value): Json<Value>,
) -> Result<Json<Value>, ApiError> {
    let source = Generation {
        file_id,
        generation,
    };
    Ok(Json(match action.as_str() {
        "prepare" => {
            parse::<Empty>(value)?;
            indexing::prepare(&app, source).await?
        }
        "complete" => {
            let input: Indexed = parse(value)?;
            indexing::complete(&app, source, &input.vector_space).await?
        }
        "fail" => {
            let input: IndexFailure = parse(value)?;
            indexing::fail(&app, source, &input.vector_space, &input.code).await?;
            json!({"state":"failed"})
        }
        _ => return Err(ApiError::not_found()),
    }))
}
async fn action(
    State(app): State<App>,
    Path((file, generation, stage, number, id, action)): Path<(
        Uuid,
        i64,
        String,
        i32,
        Uuid,
        String,
    )>,
    Json(value): Json<Value>,
) -> Result<Json<Value>, ApiError> {
    let attempt = attempt(file, generation, number, id);
    Ok(Json(match (stage.as_str(), action.as_str()) {
        ("parse", "prepare") => {
            parse::<Empty>(value)?;
            processing::prepare(&app, &attempt).await?
        }
        ("parse", "outputs") => processing::prepare_output(&app, &attempt, parse(value)?).await?,
        ("parse", "complete") => processing::complete(&app, &attempt, parse(value)?).await?,
        ("parse", "abort") => {
            let input: Failure = parse(value)?;
            processing::abort(&app, &attempt, &input.code).await?;
            json!({"state":"failed"})
        }
        ("enrichment", "prepare") => {
            parse::<Empty>(value)?;
            enrichment::prepare(&app, &attempt).await?
        }
        ("enrichment", "outputs") => {
            enrichment::prepare_output(&app, &attempt, parse(value)?).await?
        }
        ("enrichment", "complete") => enrichment::complete(&app, &attempt, parse(value)?).await?,
        ("enrichment", "fail") => {
            let input: Failure = parse(value)?;
            enrichment::fail(&app, &attempt, &input.code).await?;
            json!({"state":"failed"})
        }
        _ => return Err(ApiError::not_found()),
    }))
}
async fn upload_action(
    State(app): State<App>,
    Path((file, generation, stage, number, id, upload, action)): Path<(
        Uuid,
        i64,
        String,
        i32,
        Uuid,
        Uuid,
        String,
    )>,
    Json(value): Json<Value>,
) -> Result<Json<Value>, ApiError> {
    let attempt = attempt(file, generation, number, id);
    let s = processing::open(&app, attempt.source, false).await?;
    let fs = s.fs;
    drop(s);
    let access = access(&stage, attempt)?;
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
async fn bytes(
    State(app): State<App>,
    Path((file, generation, stage, number, id, upload)): Path<(Uuid, i64, String, i32, Uuid, Uuid)>,
    body: Body,
) -> Result<Json<Value>, ApiError> {
    let attempt = attempt(file, generation, number, id);
    let s = processing::open(&app, attempt.source, false).await?;
    let fs = s.fs;
    drop(s);
    Ok(Json(
        uploads::transfer(&app, fs, upload, access(&stage, attempt)?, body).await?,
    ))
}
