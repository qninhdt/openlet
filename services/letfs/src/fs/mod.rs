pub mod artifacts;
pub mod copy;
pub mod deletion;
pub mod exports;
pub mod maintenance;
pub mod nodes;
pub mod paths;
pub mod processing;
pub mod ranges;
pub mod trash;
pub mod uploads;
use crate::http::ApiError;
use serde::{Deserialize, Serialize};
use sqlx::{PgPool, Row};
use uuid::Uuid;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EnsureBucket {
    pub id: Uuid,
    pub provision_key: String,
    pub limit_bytes: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EnsureFilesystem {
    pub id: Uuid,
    pub bucket_id: Uuid,
    pub root_id: Uuid,
    pub provision_key: String,
    pub root_name: String,
}
#[derive(Serialize, Deserialize, Debug)]
pub struct Bucket {
    pub id: Uuid,
    pub limit_bytes: String,
    pub used_bytes: String,
    pub state: String,
}
#[derive(Serialize, Deserialize, Debug)]
pub struct Filesystem {
    pub id: Uuid,
    pub bucket_id: Uuid,
    pub root_id: Option<Uuid>,
    pub state: String,
}

pub fn validate_key(s: &str) -> Result<(), ApiError> {
    if s.is_empty() || s.len() > 200 || s.chars().any(char::is_control) {
        return Err(ApiError::bad("invalid provision_key"));
    }
    Ok(())
}
pub fn validate_name(s: &str) -> Result<(), ApiError> {
    if s.is_empty() || s.len() > 255 || matches!(s, "." | "..") || s.contains(['/', '\0']) {
        return Err(ApiError::bad("invalid name"));
    }
    Ok(())
}
pub async fn ensure_bucket(pool: &PgPool, input: EnsureBucket) -> Result<Bucket, ApiError> {
    if input.id.is_nil() {
        return Err(ApiError::bad("invalid id"));
    }
    validate_key(&input.provision_key)?;
    let limit = input
        .limit_bytes
        .parse::<i64>()
        .map_err(|_| ApiError::bad("invalid limit_bytes"))?;
    if limit < 0 || input.limit_bytes != limit.to_string() {
        return Err(ApiError::bad("invalid limit_bytes"));
    }
    let mut tx = pool.begin().await?;
    sqlx::query("INSERT INTO quota_buckets(id,provision_key,limit_bytes) VALUES($1,$2,$3) ON CONFLICT DO NOTHING").bind(input.id).bind(&input.provision_key).bind(limit).execute(&mut *tx).await?;
    let row = sqlx::query("SELECT * FROM quota_buckets WHERE provision_key=$1 FOR UPDATE")
        .bind(&input.provision_key)
        .fetch_optional(&mut *tx)
        .await?
        .ok_or_else(ApiError::conflict)?;
    if row.get::<Uuid, _>("id") != input.id
        || row.get::<i64, _>("limit_bytes") != limit
        || row.get::<String, _>("state") != "active"
    {
        return Err(ApiError::conflict());
    }
    let result = Bucket {
        id: input.id,
        limit_bytes: limit.to_string(),
        used_bytes: row.get::<i64, _>("used_bytes").to_string(),
        state: row.get("state"),
    };
    tx.commit().await?;
    Ok(result)
}
pub async fn ensure_filesystem(
    pool: &PgPool,
    input: EnsureFilesystem,
    max_nodes: i64,
) -> Result<Filesystem, ApiError> {
    if input.id.is_nil() || input.bucket_id.is_nil() || input.root_id.is_nil() {
        return Err(ApiError::bad("invalid id"));
    }
    validate_key(&input.provision_key)?;
    validate_name(&input.root_name)?;
    let mut tx = pool.begin().await?;
    let bucket = sqlx::query("SELECT state FROM quota_buckets WHERE id=$1 FOR UPDATE")
        .bind(input.bucket_id)
        .fetch_optional(&mut *tx)
        .await?
        .ok_or_else(ApiError::not_found)?;
    if bucket.get::<String, _>("state") != "active" {
        return Err(ApiError::conflict());
    }
    let inserted = sqlx::query("INSERT INTO filesystems(id,bucket_id,root_id,provision_key,max_nodes) VALUES($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING").bind(input.id).bind(input.bucket_id).bind(input.root_id).bind(&input.provision_key).bind(max_nodes).execute(&mut *tx).await?.rows_affected();
    if inserted == 1 {
        sqlx::query("INSERT INTO nodes(id,filesystem_id,name,kind) VALUES($1,$2,$3,'directory')")
            .bind(input.root_id)
            .bind(input.id)
            .bind(&input.root_name)
            .execute(&mut *tx)
            .await?;
    }
    let row = sqlx::query("SELECT f.*,n.name AS root_name FROM filesystems f JOIN nodes n ON n.id=f.root_id AND n.filesystem_id=f.id WHERE f.provision_key=$1 FOR UPDATE OF f").bind(&input.provision_key).fetch_optional(&mut *tx).await?.ok_or_else(ApiError::conflict)?;
    if row.get::<Uuid, _>("id") != input.id
        || row.get::<Uuid, _>("bucket_id") != input.bucket_id
        || row.get::<Uuid, _>("root_id") != input.root_id
        || row.get::<String, _>("root_name") != input.root_name
        || row.get::<String, _>("state") != "active"
    {
        return Err(ApiError::conflict());
    }
    let result = Filesystem {
        id: input.id,
        bucket_id: input.bucket_id,
        root_id: Some(input.root_id),
        state: row.get("state"),
    };
    tx.commit().await?;
    Ok(result)
}
#[cfg(test)]
mod tests {
    #[test]
    fn names_are_exact_and_bounded() {
        for bad in ["", ".", "..", "a/b", "a\0b"] {
            assert!(super::validate_name(bad).is_err());
        }
        assert!(super::validate_name("a\\b").is_ok());
        assert!(super::validate_name("Việt Nam").is_ok());
        assert!(super::validate_name(&"x".repeat(256)).is_err());
    }
}
