use crate::{config::StorageConfig, http::ApiError};
use aws_sigv4::http_request::{
    PercentEncodingMode, SignableBody, SignableRequest, SignatureLocation, SigningSettings,
    UriPathNormalizationMode, sign,
};
use aws_sigv4::sign::v4;
use serde::Serialize;
use std::{collections::BTreeMap, time::Duration};

#[derive(Serialize)]
pub struct SignedUpload {
    pub url: String,
    pub headers: BTreeMap<String, String>,
    // Browsers set this automatically from the body; it is not a JavaScript-settable header.
    pub content_length: String,
    pub expires_at: chrono::DateTime<chrono::Utc>,
}

pub async fn upload_url(
    config: &StorageConfig,
    key: &str,
    size: u64,
    content_md5: Option<&str>,
    lifetime: Duration,
    part: Option<(&str, u32)>,
) -> Result<SignedUpload, ApiError> {
    let mut url = url::Url::parse(&config.signing_endpoint)
        .map_err(|_| ApiError::bad("invalid signing endpoint"))?;
    url.path_segments_mut()
        .map_err(|_| ApiError::bad("invalid signing endpoint"))?
        .pop_if_empty()
        .push(&config.bucket)
        .extend(key.split('/'));
    let mut headers = BTreeMap::<String, String>::new();
    if let Some(md5) = content_md5 {
        headers.insert("content-md5".into(), md5.into());
    }
    if let Some((id, number)) = part {
        url.query_pairs_mut()
            .append_pair("uploadId", id)
            .append_pair("partNumber", &number.to_string());
    } else {
        headers.insert("if-none-match".into(), "*".into());
    }
    let identity = aws_credential_types::Credentials::new(
        &config.access_key,
        &config.secret_key,
        None,
        None,
        "openlet-storage-config",
    )
    .into();
    // object_store excludes Content-Length from signatures; the AWS signer binds it.
    let mut settings = SigningSettings::default();
    settings.signature_location = SignatureLocation::QueryParams;
    settings.expires_in = Some(lifetime);
    settings.percent_encoding_mode = PercentEncodingMode::Single;
    settings.uri_path_normalization_mode = UriPathNormalizationMode::Disabled;
    let now = std::time::SystemTime::now();
    let params = v4::SigningParams::builder()
        .identity(&identity)
        .region(&config.region)
        .name("s3")
        .time(now)
        .settings(settings)
        .build()
        .map_err(|_| ApiError::bad("invalid signing configuration"))?
        .into();
    let length = size.to_string();
    let signed_headers = headers
        .iter()
        .map(|(k, v)| (k.as_str(), v.as_str()))
        .chain(std::iter::once(("content-length", length.as_str())));
    let signable = SignableRequest::new(
        "PUT",
        url.as_str(),
        signed_headers,
        SignableBody::UnsignedPayload,
    )
    .map_err(|_| ApiError::bad("invalid upload signing request"))?;
    let (instructions, _) = sign(signable, &params)
        .map_err(|_| ApiError::state("SIGNING_FAILED"))?
        .into_parts();
    let mut request = axum::http::Request::builder()
        .uri(url.as_str())
        .body(())
        .map_err(|_| ApiError::bad("invalid upload URL"))?;
    instructions.apply_to_request_http1x(&mut request);
    let expires_at = chrono::DateTime::<chrono::Utc>::from(now)
        + chrono::Duration::seconds(lifetime.as_secs() as i64);
    Ok(SignedUpload {
        url: request.uri().to_string(),
        headers,
        content_length: length,
        expires_at,
    })
}
