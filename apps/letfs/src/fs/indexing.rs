use super::{
    enrichment,
    nodes::Session,
    processing::{self, Generation},
};
use crate::http::{ApiError, App};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sqlx::Row;
use uuid::Uuid;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct VectorSpace {
    pub model: String,
    pub collection: String,
    pub dimension: i32,
}
impl VectorSpace {
    pub fn configured(app: &App) -> Self {
        Self {
            model: app.config.search.embedding_model.clone(),
            collection: app.config.search.vector_collection.clone(),
            dimension: app.config.search.vector_dimension,
        }
    }
    fn matches(&self, row: &sqlx::postgres::PgRow) -> bool {
        row.get::<Option<String>, _>("embedding_model").as_deref() == Some(&self.model)
            && row.get::<Option<String>, _>("vector_collection").as_deref()
                == Some(&self.collection)
            && row.get::<Option<i32>, _>("vector_dimension") == Some(self.dimension)
    }
}
pub async fn enqueue(s: &mut Session<'_>, files: &[Uuid]) -> Result<(), ApiError> {
    sqlx::query("INSERT INTO index_deletions(file_id,generation,embedding_model,vector_collection,vector_dimension) SELECT node_id,desired_generation,embedding_model,vector_collection,vector_dimension FROM files WHERE node_id=ANY($1) AND desired_generation>0 AND embedding_model IS NOT NULL AND vector_collection IS NOT NULL AND vector_dimension IS NOT NULL ON CONFLICT DO NOTHING")
        .bind(files).execute(&mut *s.tx).await?;
    Ok(())
}
pub async fn prepare(app: &App, source: Generation) -> Result<Value, ApiError> {
    let mut s = processing::open(app, source, false).await?;
    let row = enrichment::validate(&mut s, source).await?;
    if row.get::<&str, _>("publication_status") != "ready" {
        return Err(ApiError::state("PUBLICATION_NOT_COMPLETE"));
    }
    let space = VectorSpace::configured(app);
    if space.matches(&row)
        && row.get::<&str, _>("index_status") == "ready"
        && row.get::<Option<i64>, _>("indexed_generation") == Some(source.generation)
    {
        return Ok(json!({"state":"succeeded","source_id":source.file_id}));
    }
    if !space.matches(&row) {
        enqueue(&mut s, &[source.file_id]).await?;
    }
    sqlx::query("UPDATE files SET embedding_model=$2,vector_collection=$3,vector_dimension=$4,index_status='pending',indexed_generation=NULL,processing_error=NULL,processing_updated_at=now() WHERE node_id=$1")
        .bind(source.file_id).bind(&space.model).bind(&space.collection).bind(space.dimension).execute(&mut *s.tx).await?;
    let rows =
        enrichment::inventory(&mut s, source.file_id, app.config.processing_max_outputs).await?;
    let nodes = enrichment::inventory_value(app, rows, source.file_id).await?;
    let value = json!({"state":"running","filesystem_id":s.fs,"source_id":source.file_id,"generation":source.generation,"nodes":nodes,"vector_space":space,"max_output_bytes":app.config.processing_max_output_bytes});
    s.tx.commit().await?;
    Ok(value)
}
pub async fn complete(
    app: &App,
    source: Generation,
    space: &VectorSpace,
) -> Result<Value, ApiError> {
    let mut s = processing::open(app, source, false).await?;
    let row = enrichment::validate(&mut s, source).await?;
    if row.get::<&str, _>("publication_status") != "ready" {
        return Err(ApiError::state("PUBLICATION_NOT_COMPLETE"));
    }
    if !space.matches(&row) || space != &VectorSpace::configured(app) {
        return Err(ApiError::state("VECTOR_SPACE_CHANGED"));
    }
    sqlx::query("UPDATE files SET indexed_generation=desired_generation,index_status='ready',processing_error=NULL,processing_updated_at=now() WHERE node_id=$1")
        .bind(source.file_id).execute(&mut *s.tx).await?;
    processing::complete_receipt(&mut s, source).await?;
    s.tx.commit().await?;
    Ok(json!({"state":"succeeded","source_id":source.file_id}))
}
pub async fn fail(
    app: &App,
    source: Generation,
    space: &VectorSpace,
    code: &str,
) -> Result<(), ApiError> {
    if !matches!(
        code,
        "PROCESSING_FAILED" | "DEPENDENCY_UNAVAILABLE" | "RESOURCE_LIMIT"
    ) {
        return Err(ApiError::bad("invalid indexing failure"));
    }
    let mut s = processing::open(app, source, true).await?;
    let row = enrichment::validate(&mut s, source).await?;
    if !space.matches(&row) {
        return Err(ApiError::state("VECTOR_SPACE_CHANGED"));
    }
    sqlx::query("UPDATE files SET index_status='failed',processing_error=$2,processing_updated_at=now() WHERE node_id=$1 AND index_status!='ready'")
        .bind(source.file_id).bind(code).execute(&mut *s.tx).await?;
    processing::complete_receipt(&mut s, source).await?;
    s.tx.commit().await?;
    Ok(())
}
pub async fn reconcile_space(app: &App) -> Result<(), ApiError> {
    let space = VectorSpace::configured(app);
    let rows = sqlx::query("WITH RECURSIVE live AS (SELECT n.id,n.kind,0 AS depth FROM nodes n JOIN filesystems fs ON fs.root_id=n.id JOIN quota_buckets b ON b.id=fs.bucket_id WHERE fs.state='active' AND b.state='active' UNION ALL SELECT n.id,n.kind,l.depth+1 FROM nodes n JOIN live l ON n.parent_id=l.id WHERE l.kind='directory' AND l.depth<128) SELECT f.node_id,f.desired_generation FROM files f JOIN live l ON l.id=f.node_id WHERE f.publication_status='ready' AND (f.embedding_model,f.vector_collection,f.vector_dimension) IS DISTINCT FROM ($1::text,$2::text,$3::int) ORDER BY f.processing_updated_at,f.node_id LIMIT 16")
        .bind(&space.model).bind(&space.collection).bind(space.dimension).fetch_all(&app.pool).await?;
    for row in rows {
        let source = Generation {
            file_id: row.get("node_id"),
            generation: row.get("desired_generation"),
        };
        let mut s = processing::open(app, source, true).await?;
        let row = processing::current(&mut s, source).await?;
        if row.get::<&str, _>("publication_status") != "ready" || space.matches(&row) {
            continue;
        }
        if let Err(error) = processing::source(&mut s, &row).await {
            if !error.0.is_client_error() {
                return Err(error);
            }
            continue;
        }
        enqueue(&mut s, &[source.file_id]).await?;
        sqlx::query("UPDATE files SET embedding_model=$2,vector_collection=$3,vector_dimension=$4,index_status='pending',indexed_generation=NULL,processing_error=NULL,processing_updated_at=now() WHERE node_id=$1")
            .bind(source.file_id).bind(&space.model).bind(&space.collection).bind(space.dimension).execute(&mut *s.tx).await?;
        s.tx.commit().await?;
    }
    Ok(())
}
pub async fn cleanup(app: &App) -> Result<u32, ApiError> {
    let rows=sqlx::query("SELECT d.* FROM index_deletions d WHERE d.eligible_at<=now() AND NOT EXISTS(SELECT 1 FROM files f WHERE f.node_id=d.file_id AND f.desired_generation=d.generation AND f.embedding_model=d.embedding_model AND f.vector_collection=d.vector_collection AND f.vector_dimension=d.vector_dimension AND f.publication_status='ready' AND f.index_status IN ('pending','ready')) ORDER BY d.eligible_at,d.file_id LIMIT 32")
        .fetch_all(&app.pool).await?;
    let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(30);
    let mut count = 0;
    for row in rows {
        if tokio::time::Instant::now() >= deadline {
            break;
        }
        let source = Generation {
            file_id: row.get("file_id"),
            generation: row.get("generation"),
        };
        if processing::workflow_running(app, source).await? {
            continue;
        }
        let space = VectorSpace {
            model: row.get("embedding_model"),
            collection: row.get("vector_collection"),
            dimension: row.get("vector_dimension"),
        };
        let id = crate::temporal::process_file_workflow::index_workflow_id(source, &space)?;
        if processing::workflow_status_since(app, &id, None).await? == Some(true) {
            continue;
        }
        // Serialize the final serving-state check with generation and space changes.
        let fs: Option<Uuid> = sqlx::query_scalar("SELECT filesystem_id FROM nodes WHERE id=$1")
            .bind(source.file_id)
            .fetch_optional(&app.pool)
            .await?;
        let mut guard = if let Some(fs) = fs {
            Some(super::nodes::lifecycle_session(app, fs).await?)
        } else {
            None
        };
        if let Some(s) = guard.as_mut() {
            let active: bool = sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM files WHERE node_id=$1 AND desired_generation=$2 AND embedding_model=$3 AND vector_collection=$4 AND vector_dimension=$5 AND publication_status='ready' AND index_status IN ('pending','ready'))")
                .bind(source.file_id).bind(source.generation).bind(&space.model).bind(&space.collection).bind(space.dimension).fetch_one(&mut *s.tx).await?;
            if active {
                continue;
            }
        }
        delete_points(app, source, &space).await?;
        if let Some(s) = guard {
            s.tx.commit().await?;
        }
        // A timed-out old remote write may outlive its producer: retain the compact tombstone.
        sqlx::query("UPDATE index_deletions SET eligible_at=now()+interval '1 day' WHERE file_id=$1 AND generation=$2 AND embedding_model=$3 AND vector_collection=$4 AND vector_dimension=$5")
            .bind(source.file_id).bind(source.generation).bind(&space.model).bind(&space.collection).bind(space.dimension).execute(&app.pool).await?;
        count += 1;
    }
    Ok(count)
}
pub async fn delete_points(
    app: &App,
    source: Generation,
    space: &VectorSpace,
) -> Result<(), ApiError> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(5))
        .build()
        .map_err(|_| dependency())?;
    let client = reqwest_middleware::ClientBuilder::new(client)
        .with(reqwest_tracing::TracingMiddleware::<
            crate::telemetry::HttpSpan,
        >::new())
        .build();
    let response=client.post(format!("{}/collections/{}/points/delete?wait=true",app.config.search.qdrant_url.trim_end_matches('/'),space.collection))
        .header("api-key",&app.config.search.qdrant_key)
        .json(&json!({"filter":{"must":[{"key":"source_id","match":{"value":source.file_id}},{"key":"generation","match":{"value":source.generation}},{"key":"embedding_model","match":{"value":space.model}},{"key":"vector_dimension","match":{"value":space.dimension}}]}}))
        .send().await.map_err(|_|dependency())?;
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
