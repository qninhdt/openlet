use super::{enrichment, processing};
use crate::http::{ApiError, App};
use serde_json::{Value, json};
use sqlx::Row;
use uuid::Uuid;

pub async fn prepare(app: &App, op: Uuid) -> Result<Value, ApiError> {
    let mut s = processing::open(app, op, false).await?;
    let row = enrichment::validate(&mut s, op).await?;
    let source: Uuid = row.get("source_id");
    if row.get::<&str, _>("enrichment_state") != "succeeded" {
        return Err(ApiError::state("ENRICHMENT_NOT_COMPLETE"));
    }
    if row.get::<&str, _>("index_state") == "succeeded" {
        return Ok(json!({"state":"succeeded","source_id":source}));
    }
    if row.get::<Option<&str>, _>("index_cleanup_state") == Some("pending") {
        if let Some(collection) = row.get::<Option<String>, _>("vector_collection") {
            delete_points(app, &collection, op).await?;
        }
        sqlx::query("UPDATE operations SET embedding_model=$2,vector_collection=$3,vector_dimension=$4,index_cleanup_state=NULL WHERE id=$1")
            .bind(op).bind(&app.config.search.embedding_model).bind(&app.config.search.vector_collection)
            .bind(app.config.search.vector_dimension).execute(&mut *s.tx).await?;
    }
    sqlx::query("UPDATE operations SET embedding_model=coalesce(embedding_model,$2),vector_collection=coalesce(vector_collection,$3),vector_dimension=coalesce(vector_dimension,$4),index_state='running',index_error=NULL,updated_at=now() WHERE id=$1")
        .bind(op).bind(&app.config.search.embedding_model).bind(&app.config.search.vector_collection).bind(app.config.search.vector_dimension).execute(&mut *s.tx).await?;
    let space = sqlx::query(
        "SELECT embedding_model,vector_collection,vector_dimension FROM operations WHERE id=$1",
    )
    .bind(op)
    .fetch_one(&mut *s.tx)
    .await?;
    let rows = enrichment::inventory(&mut s, source, app.config.processing_max_outputs).await?;
    let nodes = enrichment::inventory_value(app, rows, source).await?;
    let value = json!({"state":"running","filesystem_id":s.fs,"source_id":source,"nodes":nodes,
        "vector_space":{"model":space.get::<String,_>("embedding_model"),"collection":space.get::<String,_>("vector_collection"),"dimension":space.get::<i32,_>("vector_dimension")},
        "max_output_bytes":app.config.processing_max_output_bytes});
    s.tx.commit().await?;
    Ok(value)
}

pub async fn complete(app: &App, op: Uuid) -> Result<Value, ApiError> {
    let mut s = processing::open(app, op, false).await?;
    let row = enrichment::validate(&mut s, op).await?;
    if row.get::<&str, _>("enrichment_state") != "succeeded" {
        return Err(ApiError::state("ENRICHMENT_NOT_COMPLETE"));
    }
    if row.get::<Option<String>, _>("embedding_model").as_deref()
        != Some(&app.config.search.embedding_model)
        || row.get::<Option<String>, _>("vector_collection").as_deref()
            != Some(&app.config.search.vector_collection)
        || row.get::<Option<i32>, _>("vector_dimension") != Some(app.config.search.vector_dimension)
    {
        return Err(ApiError::state("VECTOR_SPACE_CHANGED"));
    }
    if !matches!(row.get::<&str, _>("index_state"), "running" | "succeeded") {
        return Err(ApiError::state("INDEX_NOT_ACTIVE"));
    }
    sqlx::query("UPDATE operations SET index_state='succeeded',index_error=NULL,indexed_at=coalesce(indexed_at,now()),updated_at=now() WHERE id=$1").bind(op).execute(&mut *s.tx).await?;
    let source: Uuid = row.get("source_id");
    s.tx.commit().await?;
    Ok(json!({"state":"succeeded","source_id":source}))
}

pub async fn fail(app: &App, op: Uuid, code: &str) -> Result<(), ApiError> {
    if !matches!(
        code,
        "PROCESSING_FAILED" | "DEPENDENCY_UNAVAILABLE" | "RESOURCE_LIMIT"
    ) {
        return Err(ApiError::bad("invalid indexing failure"));
    }
    let mut s = processing::open(app, op, true).await?;
    enrichment::validate(&mut s, op).await?;
    sqlx::query("UPDATE operations SET index_state='failed',index_error=$2,updated_at=now() WHERE id=$1 AND index_state!='succeeded'").bind(op).bind(code).execute(&mut *s.tx).await?;
    s.tx.commit().await?;
    Ok(())
}

pub async fn cleanup(app: &App) -> Result<u32, ApiError> {
    sqlx::query("UPDATE operations o SET index_cleanup_state='pending',updated_at=now() WHERE kind='process-file' AND vector_collection IS NOT NULL AND index_cleanup_state IS NULL AND (superseded_at IS NOT NULL OR NOT EXISTS(SELECT 1 FROM nodes n JOIN filesystems f ON f.id=n.filesystem_id WHERE n.id=o.source_id AND n.filesystem_id=o.filesystem_id AND f.state='active'))").execute(&app.pool).await?;
    let rows=sqlx::query("SELECT o.id,o.vector_collection FROM operations o WHERE o.kind='process-file' AND o.index_cleanup_state='pending' AND o.vector_collection IS NOT NULL AND o.updated_at<now()-interval '15 minutes' AND (o.superseded_at IS NOT NULL OR NOT EXISTS(SELECT 1 FROM nodes n JOIN filesystems f ON f.id=n.filesystem_id WHERE n.id=o.source_id AND n.filesystem_id=o.filesystem_id AND f.state='active')) ORDER BY o.updated_at,o.id LIMIT 32").fetch_all(&app.pool).await?;
    for row in &rows {
        let op: Uuid = row.get("id");
        if processing::workflow_running(app, op).await? {
            continue;
        }
        let collection: String = row.get("vector_collection");
        delete_points(app, &collection, op).await?;
        sqlx::query("UPDATE operations SET index_cleanup_state='succeeded' WHERE id=$1")
            .bind(op)
            .execute(&app.pool)
            .await?;
    }
    Ok(rows.len() as u32)
}

pub async fn delete_points(app: &App, collection: &str, op: Uuid) -> Result<(), ApiError> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(5))
        .build()
        .map_err(|_| dependency())?;
    let response = client
        .post(format!(
            "{}/collections/{collection}/points/delete?wait=true",
            app.config.search.qdrant_url.trim_end_matches('/')
        ))
        .header("api-key", &app.config.search.qdrant_key)
        .json(&json!({"filter":{"must":[{"key":"operation_id","match":{"value":op}}]}}))
        .send()
        .await
        .map_err(|_| dependency())?;
    if response.status() != reqwest::StatusCode::NOT_FOUND {
        let value: Value = response
            .error_for_status()
            .map_err(|_| dependency())?
            .json()
            .await
            .map_err(|_| dependency())?;
        if value["result"]["status"] != "completed" {
            return Err(dependency());
        }
    }
    Ok(())
}
pub fn dependency() -> ApiError {
    ApiError(
        axum::http::StatusCode::SERVICE_UNAVAILABLE,
        "DEPENDENCY_UNAVAILABLE",
        "search dependency unavailable",
    )
}
