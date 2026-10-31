use super::{Bucket, EnsureBucket, EnsureFilesystem, Filesystem};
use crate::http::ApiError;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use sqlx::{PgPool, Postgres, Row, Transaction};
use uuid::Uuid;

pub(super) async fn save_receipt(
    tx: &mut Transaction<'_, Postgres>,
    operation: &str,
    key: &str,
    input: &impl Serialize,
    result: &impl Serialize,
) -> Result<(), ApiError> {
    let input =
        serde_json::to_vec(input).map_err(|_| ApiError::bad("invalid provisioning input"))?;
    let hash = format!("{:x}", Sha256::digest(input));
    let result = serde_json::to_value(result).map_err(|_| ApiError::conflict())?;
    let changed = sqlx::query("INSERT INTO idempotency_keys(scope,operation,request_key,request_hash,result) VALUES('workspace-provisioning',$1,$2,$3,$4) ON CONFLICT(scope,operation,request_key) DO UPDATE SET request_hash=excluded.request_hash WHERE idempotency_keys.request_hash=excluded.request_hash")
        .bind(operation).bind(key).bind(hash).bind(result).execute(&mut **tx).await?.rows_affected();
    if changed != 1 {
        return Err(ApiError::state("IDEMPOTENCY_CONFLICT"));
    }
    Ok(())
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BucketInput {
    pub workspace_id: Uuid,
    pub limit_bytes: String,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FilesystemInput {
    pub workspace_id: Uuid,
    pub bucket_id: Uuid,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BucketScope {
    pub workspace_id: Uuid,
    pub bucket_id: Uuid,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FilesystemPage {
    pub workspace_id: Uuid,
    pub bucket_id: Uuid,
    pub after: Uuid,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Provisioned {
    pub workspace_id: Uuid,
    pub bucket_id: Uuid,
    pub filesystem_id: Uuid,
    pub root_id: Uuid,
}
fn bucket_key(workspace: Uuid) -> Result<String, ApiError> {
    if workspace.is_nil() {
        return Err(ApiError::bad("invalid workspace identity"));
    }
    Ok(format!("workspace/{workspace}"))
}
fn filesystem_key(workspace: Uuid) -> Result<String, ApiError> {
    bucket_key(workspace)?;
    Ok(format!("workspace-drive/{workspace}"))
}
async fn owned_bucket(
    tx: &mut Transaction<'_, Postgres>,
    scope: &BucketScope,
) -> Result<String, ApiError> {
    let row = sqlx::query("SELECT provision_key,state FROM quota_buckets WHERE id=$1 FOR UPDATE")
        .bind(scope.bucket_id)
        .fetch_optional(&mut **tx)
        .await?
        .ok_or_else(ApiError::not_found)?;
    if row.get::<String, _>("provision_key") != bucket_key(scope.workspace_id)? {
        return Err(ApiError::state("SCOPE_CONFLICT"));
    }
    Ok(row.get("state"))
}
pub async fn bucket(pool: &PgPool, input: BucketInput) -> Result<Bucket, ApiError> {
    super::ensure_bucket(
        pool,
        EnsureBucket {
            provision_key: bucket_key(input.workspace_id)?,
            limit_bytes: input.limit_bytes,
        },
    )
    .await
}
pub async fn filesystem(
    pool: &PgPool,
    input: FilesystemInput,
    max_nodes: i64,
) -> Result<Filesystem, ApiError> {
    let mut tx = pool.begin().await?;
    owned_bucket(
        &mut tx,
        &BucketScope {
            workspace_id: input.workspace_id,
            bucket_id: input.bucket_id,
        },
    )
    .await?;
    tx.commit().await?;
    super::ensure_filesystem(
        pool,
        EnsureFilesystem {
            bucket_id: input.bucket_id,
            provision_key: filesystem_key(input.workspace_id)?,
            root_name: "drive".into(),
        },
        max_nodes,
    )
    .await
}
pub async fn release(pool: &PgPool, input: Provisioned) -> Result<(), ApiError> {
    let mut tx = pool.begin().await?;
    owned_bucket(
        &mut tx,
        &BucketScope {
            workspace_id: input.workspace_id,
            bucket_id: input.bucket_id,
        },
    )
    .await?;
    let valid:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM filesystems WHERE id=$1 AND bucket_id=$2 AND (root_id=$3 OR state='deleted') AND provision_key=$4)")
        .bind(input.filesystem_id).bind(input.bucket_id).bind(input.root_id).bind(filesystem_key(input.workspace_id)?).fetch_one(&mut *tx).await?;
    if !valid {
        return Err(ApiError::state("SCOPE_CONFLICT"));
    }
    sqlx::query("UPDATE idempotency_keys SET completed_at=COALESCE(completed_at,now()),expires_at=COALESCE(expires_at,now()+interval '24 hours') WHERE scope='workspace-provisioning' AND ((operation='provision-bucket' AND request_key=$1) OR (operation='provision-filesystem' AND request_key=$2))")
        .bind(bucket_key(input.workspace_id)?).bind(filesystem_key(input.workspace_id)?).execute(&mut *tx).await?;
    tx.commit().await?;
    Ok(())
}
pub async fn freeze(pool: &PgPool, mut input: BucketScope) -> Result<Uuid, ApiError> {
    let key = bucket_key(input.workspace_id)?;
    let mut tx = pool.begin().await?;
    if input.bucket_id.is_nil() {
        // A failed provision may have lost its result; fence late creation with the same owner key.
        sqlx::query("INSERT INTO quota_buckets(id,provision_key,limit_bytes,state) VALUES($1,$2,0,'frozen') ON CONFLICT(provision_key) DO NOTHING")
            .bind(Uuid::now_v7()).bind(&key).execute(&mut *tx).await?;
        input.bucket_id = sqlx::query_scalar("SELECT id FROM quota_buckets WHERE provision_key=$1")
            .bind(key)
            .fetch_one(&mut *tx)
            .await?;
    }
    owned_bucket(&mut tx, &input).await?;
    sqlx::query("UPDATE quota_buckets SET state=CASE WHEN state='active' THEN 'frozen' ELSE state END WHERE id=$1").bind(input.bucket_id).execute(&mut *tx).await?;
    tx.commit().await?;
    Ok(input.bucket_id)
}
pub async fn filesystems(pool: &PgPool, input: FilesystemPage) -> Result<Vec<Uuid>, ApiError> {
    let mut tx = pool.begin().await?;
    let state = owned_bucket(
        &mut tx,
        &BucketScope {
            workspace_id: input.workspace_id,
            bucket_id: input.bucket_id,
        },
    )
    .await?;
    if state != "frozen" && state != "deleted" {
        return Err(ApiError::state("BUCKET_NOT_FROZEN"));
    }
    let ids = sqlx::query_scalar(
        "SELECT id FROM filesystems WHERE bucket_id=$1 AND state!='deleted' AND id>$2 ORDER BY id LIMIT 64",
    )
    .bind(input.bucket_id)
    .bind(input.after)
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    Ok(ids)
}
pub async fn complete(pool: &PgPool, input: BucketScope) -> Result<(), ApiError> {
    let mut tx = pool.begin().await?;
    owned_bucket(&mut tx, &input).await?;
    let changed=sqlx::query("UPDATE quota_buckets b SET state='deleted' WHERE id=$1 AND state IN ('frozen','deleted') AND used_bytes=0 AND NOT EXISTS(SELECT 1 FROM filesystems WHERE bucket_id=b.id AND state!='deleted') AND NOT EXISTS(SELECT 1 FROM uploads WHERE bucket_id=b.id AND state IN ('open','completing'))").bind(input.bucket_id).execute(&mut *tx).await?.rows_affected();
    if changed != 1 {
        return Err(ApiError::state("DELETION_INCOMPLETE"));
    }
    // A deleted owner has no remaining consumer; release partial provisioning receipts as well.
    sqlx::query("UPDATE idempotency_keys SET completed_at=COALESCE(completed_at,now()),expires_at=COALESCE(expires_at,now()+interval '24 hours') WHERE scope='workspace-provisioning' AND ((operation='provision-bucket' AND request_key=$1) OR (operation='provision-filesystem' AND request_key=$2))")
        .bind(bucket_key(input.workspace_id)?).bind(filesystem_key(input.workspace_id)?).execute(&mut *tx).await?;
    tx.commit().await?;
    Ok(())
}
pub async fn prune_receipts(pool: &PgPool) -> Result<(), ApiError> {
    sqlx::query("DELETE FROM idempotency_keys WHERE (scope,operation,request_key) IN (SELECT scope,operation,request_key FROM idempotency_keys WHERE expires_at<=now() ORDER BY expires_at LIMIT 100)").execute(pool).await?;
    Ok(())
}
