pub mod archive;
pub mod provider_smoke;
pub mod transfers;
use crate::{config::Config, http::ApiError};
use object_store::{ClientOptions, RetryConfig, aws, aws::AmazonS3Builder};
use std::{sync::Arc, time::Duration};

pub fn build(config: &Config) -> Result<(Arc<aws::AmazonS3>, Arc<aws::AmazonS3>), String> {
    let control = build_endpoint(config, &config.storage.endpoint)?;
    let signer = if config.storage.signing_endpoint == config.storage.endpoint {
        control.clone()
    } else {
        build_endpoint(config, &config.storage.signing_endpoint)?
    };
    Ok((control, signer))
}
fn build_endpoint(config: &Config, endpoint: &str) -> Result<Arc<aws::AmazonS3>, String> {
    let s = &config.storage;
    let store = AmazonS3Builder::new()
        .with_endpoint(endpoint)
        .with_region(&s.region)
        .with_bucket_name(&s.bucket)
        .with_access_key_id(&s.access_key)
        .with_secret_access_key(&s.secret_key)
        .with_virtual_hosted_style_request(false)
        .with_client_options(
            ClientOptions::new()
                .with_timeout(Duration::from_secs(120))
                .with_allow_http(s.allow_http),
        )
        .with_retry(RetryConfig {
            max_retries: 3,
            retry_timeout: Duration::from_secs(120),
            ..Default::default()
        })
        .build()
        .map_err(|_| "invalid S3 configuration")?;
    Ok(Arc::new(store))
}
pub async fn download_url(
    app: &crate::http::App,
    key: &str,
    name: &str,
) -> Result<url::Url, ApiError> {
    use object_store::signer::Signer;
    app.signer
        .signed_url_opts(
            axum::http::Method::GET,
            &object_store::path::Path::from(key),
            Duration::from_secs(app.config.storage.download_url_ttl_seconds),
            &download_options(name),
        )
        .await
        .map_err(error)
}
pub(crate) fn download_options(name: &str) -> object_store::signer::SignedUrlOptions {
    let encoded = url::form_urlencoded::byte_serialize(name.as_bytes())
        .collect::<String>()
        .replace('+', "%20");
    object_store::signer::SignedUrlOptions::new().with_query([
        (
            "response-content-disposition",
            format!("attachment; filename=\"download\"; filename*=UTF-8''{encoded}"),
        ),
        ("response-content-type", "application/octet-stream".into()),
        ("response-cache-control", "private, no-store".into()),
    ])
}
pub fn error(e: object_store::Error) -> ApiError {
    let kind = match e {
        object_store::Error::NotFound { .. } => "not_found",
        object_store::Error::PermissionDenied { .. } => "permission_denied",
        object_store::Error::Unauthenticated { .. } => "unauthenticated",
        object_store::Error::Precondition { .. } => "precondition",
        _ => "provider",
    };
    tracing::error!(kind, "object storage request failed");
    ApiError(
        axum::http::StatusCode::SERVICE_UNAVAILABLE,
        "DEPENDENCY_UNAVAILABLE",
        "object storage unavailable",
    )
}
#[cfg(test)]
mod tests {
    #[test]
    fn download_names_cannot_inject_headers_or_query_parameters() {
        let options = super::download_options("report \"?&é\r\nX-Evil: yes.pdf");
        let query = options
            .extra_query
            .into_iter()
            .collect::<std::collections::HashMap<_, _>>();
        let disposition = &query["response-content-disposition"];
        assert_eq!(
            disposition,
            "attachment; filename=\"download\"; filename*=UTF-8''report%20%22%3F%26%C3%A9%0D%0AX-Evil%3A%20yes.pdf"
        );
        assert!(!disposition.contains(['\r', '\n']));
        assert_eq!(query["response-content-type"], "application/octet-stream");
    }
}
