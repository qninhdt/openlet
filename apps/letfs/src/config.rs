use std::{env, net::SocketAddr};

#[derive(Clone)]
pub struct Config {
    pub listen: SocketAddr,
    pub database_url: String,
    pub workspace_token: String,
    pub processor_token: String,
    pub archive: ArchiveConfig,
    pub processing_max_outputs: i64,
    pub processing_max_output_bytes: i64,
    pub temporal_address: String,
    pub temporal_namespace: String,
    pub max_nodes: i64,
    pub inline_limit: usize,
    pub storage: StorageConfig,
    pub max_file_bytes: i64,
    pub max_outstanding: i64,
    pub max_cleanup_backlog: i64,
    pub max_copy_nodes: i64,
    pub search: SearchConfig,
}

#[derive(Clone)]
pub struct SearchConfig {
    pub openrouter_url: String,
    pub openrouter_key: String,
    pub embedding_model: String,
    pub rerank_model: String,
    pub vector_collection: String,
    pub vector_dimension: i32,
    pub qdrant_url: String,
    pub qdrant_key: String,
}
impl Default for SearchConfig {
    fn default() -> Self {
        Self {
            openrouter_url: "https://openrouter.ai/api/v1".into(),
            openrouter_key: String::new(),
            embedding_model: "openai/text-embedding-3-small".into(),
            rerank_model: "cohere/rerank-v3.5".into(),
            vector_collection: "files".into(),
            vector_dimension: 1536,
            qdrant_url: "http://qdrant:6333".into(),
            qdrant_key: String::new(),
        }
    }
}
impl SearchConfig {
    pub fn vector_space(&self) -> serde_json::Value {
        serde_json::json!({
            "model": self.embedding_model,
            "collection": self.vector_collection,
            "dimension": self.vector_dimension,
        })
    }
    fn load() -> Result<Self, String> {
        let defaults = Self::default();
        let key = |name: &str| -> Result<String, String> {
            let path =
                env::var(format!("{name}_FILE")).map_err(|_| format!("{name}_FILE required"))?;
            let value =
                std::fs::read_to_string(path).map_err(|_| format!("cannot read {name}_FILE"))?;
            let value = value.trim();
            if value.is_empty() {
                return Err(format!("{name} required"));
            }
            Ok(value.into())
        };
        let settings = Self {
            openrouter_url: env::var("OPENROUTER_URL").unwrap_or(defaults.openrouter_url),
            openrouter_key: key("OPENROUTER_API_KEY")?,
            embedding_model: env::var("OPENROUTER_EMBEDDING_MODEL")
                .unwrap_or(defaults.embedding_model),
            rerank_model: env::var("OPENROUTER_RERANK_MODEL").unwrap_or(defaults.rerank_model),
            vector_collection: env::var("QDRANT_COLLECTION").unwrap_or(defaults.vector_collection),
            vector_dimension: positive("EMBEDDING_DIMENSION", defaults.vector_dimension as i64)?
                .try_into()
                .map_err(|_| "invalid EMBEDDING_DIMENSION")?,
            qdrant_url: env::var("QDRANT_URL").unwrap_or(defaults.qdrant_url),
            qdrant_key: key("QDRANT_API_KEY")?,
        };
        let local = env::var("ALLOW_LOCAL_AI").as_deref() == Ok("true");
        validate_storage_endpoint(&settings.openrouter_url, local)?;
        validate_storage_endpoint(&settings.qdrant_url, true)?;
        if settings.embedding_model.trim().is_empty()
            || settings.rerank_model.trim().is_empty()
            || !(1..=65536).contains(&settings.vector_dimension)
            || settings.vector_collection.is_empty()
            || settings.vector_collection.len() > 100
            || !settings
                .vector_collection
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"_-".contains(&c))
        {
            return Err("invalid search configuration".into());
        }
        Ok(settings)
    }
}
#[derive(Clone)]
pub struct ArchiveConfig {
    pub max_entries: i64,
    pub max_source_bytes: i64,
    pub max_output_bytes: i64,
    pub max_concurrent: i64,
    pub runtime_seconds: i64,
}
impl ArchiveConfig {
    pub fn validate(&self) -> Result<(), String> {
        if !(1..=100000).contains(&self.max_entries)
            || !(1..=8).contains(&self.max_concurrent)
            || !(1..=1800).contains(&self.runtime_seconds)
            || !(1..=10_000_000_000).contains(&self.max_source_bytes)
            || !(1..=10_000_000_000).contains(&self.max_output_bytes)
        {
            return Err("invalid archive resource limits".into());
        }
        Ok(())
    }
}
impl Default for ArchiveConfig {
    fn default() -> Self {
        Self {
            max_entries: 10000,
            max_source_bytes: 1073741824,
            max_output_bytes: 1107296256,
            max_concurrent: 2,
            runtime_seconds: 1200,
        }
    }
}
#[derive(Clone)]
pub struct StorageConfig {
    pub endpoint: String,
    pub signing_endpoint: String,
    pub download_url_ttl_seconds: u64,
    pub upload_url_ttl_seconds: u64,
    pub upload_transfer_grace_seconds: u64,
    pub multipart_threshold_bytes: i64,
    pub multipart_part_bytes: i64,
    pub region: String,
    pub bucket: String,
    pub access_key: String,
    pub secret_key: String,
    pub allow_http: bool,
}
fn positive(key: &str, default: i64) -> Result<i64, String> {
    env::var(key)
        .unwrap_or_else(|_| default.to_string())
        .parse::<i64>()
        .ok()
        .filter(|v| *v > 0 && *v <= 10_000_000_000)
        .ok_or_else(|| format!("invalid {key}"))
}
impl Config {
    pub fn load() -> Result<Self, String> {
        let get = |k: &str| {
            if let Ok(path) = env::var(format!("{k}_FILE")) {
                return std::fs::read_to_string(path)
                    .map(|s| s.trim().to_owned())
                    .map_err(|_| format!("cannot read {k}_FILE"));
            }
            env::var(k).map_err(|_| format!("missing {k}"))
        };
        let database_url = get("DATABASE_URL")?;
        let u = url::Url::parse(&database_url).map_err(|_| "invalid DATABASE_URL")?;
        if !matches!(u.scheme(), "postgres" | "postgresql")
            || u.host_str().is_none()
            || u.password().is_none()
        {
            return Err("DATABASE_URL requires PostgreSQL host and credentials".into());
        }
        let workspace_token = get("WORKSPACE_SERVICE_TOKEN")?;
        validate_token(&workspace_token)?;
        let processor_token = get("PROCESSOR_SERVICE_TOKEN")?;
        validate_token(&processor_token)?;
        if processor_token == workspace_token {
            return Err("processor and workspace tokens must differ".into());
        }
        let temporal_address = get("TEMPORAL_ADDRESS")?;
        let u = url::Url::parse(&temporal_address).map_err(|_| "invalid TEMPORAL_ADDRESS")?;
        if !matches!(u.scheme(), "http" | "https") || u.host_str().is_none() {
            return Err("invalid TEMPORAL_ADDRESS".into());
        }
        let temporal_namespace = get("TEMPORAL_NAMESPACE")?;
        if temporal_namespace.is_empty() {
            return Err("empty TEMPORAL_NAMESPACE".into());
        }
        let max_nodes = env::var("MAX_NODES")
            .unwrap_or_else(|_| "1000000".into())
            .parse::<i64>()
            .map_err(|_| "invalid MAX_NODES")?;
        if max_nodes <= 0 {
            return Err("MAX_NODES must be positive".into());
        }
        let endpoint = get("S3_ENDPOINT")?;
        let allow_http = env::var("ALLOW_LOCAL_S3").as_deref() == Ok("true");
        validate_storage_endpoint(&endpoint, allow_http)?;
        let signing_endpoint = env::var("S3_SIGNING_ENDPOINT").unwrap_or_else(|_| endpoint.clone());
        validate_storage_endpoint(&signing_endpoint, allow_http)?;
        let download_url_ttl_seconds = env::var("DOWNLOAD_URL_TTL_SECONDS")
            .unwrap_or_else(|_| "300".into())
            .parse::<u64>()
            .ok()
            // Old objects have a fifteen-minute GC grace; leave room for an active GET.
            .filter(|ttl| (1..=600).contains(ttl))
            .ok_or("DOWNLOAD_URL_TTL_SECONDS must be between 1 and 600")?;
        let upload_url_ttl_seconds = positive("UPLOAD_URL_TTL_SECONDS", 900)? as u64;
        let upload_transfer_grace_seconds = positive("UPLOAD_TRANSFER_GRACE_SECONDS", 3600)? as u64;
        let multipart_threshold_bytes = positive("MULTIPART_THRESHOLD_BYTES", 16777216)?;
        let multipart_part_bytes = positive("MULTIPART_PART_BYTES", 8388608)?;
        if upload_url_ttl_seconds > 3600
            || upload_transfer_grace_seconds > 86400
            || !(5242880..=5368709120).contains(&multipart_part_bytes)
            || multipart_threshold_bytes < multipart_part_bytes
        {
            return Err("invalid direct upload limits".into());
        }
        if positive("MAX_FILE_BYTES", 104857600)? > multipart_part_bytes * 10000 {
            return Err("MAX_FILE_BYTES exceeds native multipart part-count limit".into());
        }
        let storage = StorageConfig {
            endpoint,
            signing_endpoint,
            download_url_ttl_seconds,
            upload_url_ttl_seconds,
            upload_transfer_grace_seconds,
            multipart_threshold_bytes,
            multipart_part_bytes,
            region: get("S3_REGION")?,
            bucket: get("S3_BUCKET")?,
            access_key: get("S3_ACCESS_KEY_ID")?,
            secret_key: get("S3_SECRET_ACCESS_KEY")?,
            allow_http,
        };
        if [
            &storage.region,
            &storage.bucket,
            &storage.access_key,
            &storage.secret_key,
        ]
        .iter()
        .any(|v| v.is_empty())
        {
            return Err("empty S3 configuration".into());
        }
        let archive = ArchiveConfig {
            max_entries: positive("ARCHIVE_MAX_ENTRIES", 10000)?,
            max_source_bytes: positive("ARCHIVE_MAX_SOURCE_BYTES", 1073741824)?,
            max_output_bytes: positive("ARCHIVE_MAX_OUTPUT_BYTES", 1107296256)?,
            max_concurrent: positive("ARCHIVE_MAX_CONCURRENT", 2)?,
            runtime_seconds: positive("ARCHIVE_RUNTIME_SECONDS", 1200)?,
        };
        archive.validate()?;
        Ok(Self {
            search: SearchConfig::load()?,
            listen: env::var("LISTEN_ADDR")
                .unwrap_or_else(|_| "0.0.0.0:8080".into())
                .parse()
                .map_err(|_| "invalid LISTEN_ADDR")?,
            database_url,
            workspace_token,
            processor_token,
            archive,
            processing_max_outputs: positive("PROCESSING_MAX_OUTPUTS", 512)?,
            processing_max_output_bytes: positive("PROCESSING_MAX_OUTPUT_BYTES", 268435456)?,
            temporal_address,
            temporal_namespace,
            max_nodes,
            storage,
            max_file_bytes: positive("MAX_FILE_BYTES", 104857600)?,
            max_outstanding: positive("MAX_OUTSTANDING_STORAGE", 16)?,
            max_cleanup_backlog: positive("MAX_CLEANUP_BACKLOG", 10000)?,
            max_copy_nodes: positive("MAX_COPY_NODES", 10000)?,
            inline_limit: env::var("INLINE_LIMIT_BYTES")
                .unwrap_or_else(|_| "262144".into())
                .parse::<usize>()
                .ok()
                .filter(|v| *v > 0 && *v <= 1048576)
                .ok_or("invalid INLINE_LIMIT_BYTES")?,
        })
    }
}
fn validate_storage_endpoint(endpoint: &str, allow_http: bool) -> Result<(), String> {
    let parsed = url::Url::parse(endpoint).map_err(|_| "invalid S3 endpoint")?;
    if parsed.host_str().is_none()
        || !parsed.username().is_empty()
        || parsed.password().is_some()
        || parsed.query().is_some()
        || parsed.fragment().is_some()
        || !(parsed.scheme() == "https" || (allow_http && parsed.scheme() == "http"))
    {
        return Err("S3 endpoint requires HTTPS unless local storage is explicitly enabled".into());
    }
    Ok(())
}
pub fn validate_token(token: &str) -> Result<(), String> {
    if token.len() < 32
        || !token
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"-_".contains(&c))
    {
        return Err("service token must contain at least 32 URL-safe random characters".into());
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    #[test]
    fn signing_endpoint_preserves_the_storage_trust_boundary() {
        for endpoint in [
            "http://storage:8333",
            "https://user:secret@storage",
            "https://storage?x=1",
            "https://storage/#fragment",
            "file:///tmp/data",
        ] {
            assert!(super::validate_storage_endpoint(endpoint, false).is_err());
        }
        assert!(
            super::validate_storage_endpoint("https://private.example/bucket-prefix", false)
                .is_ok()
        );
        assert!(super::validate_storage_endpoint("http://127.0.0.1:8333", true).is_ok());
    }
    #[test]
    fn tokens_reject_short_or_header_injection() {
        assert!(super::validate_token("short").is_err());
        assert!(super::validate_token(&format!("{}\n", "a".repeat(32))).is_err());
        assert!(super::validate_token(&"a".repeat(43)).is_ok());
    }
}
