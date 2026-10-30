use crate::{config::Config, storage};
use bytes::Bytes;
use object_store::{GetOptions, GetRange, ObjectStore, ObjectStoreExt, PutPayload, path::Path};

pub async fn run() -> Result<(), String> {
    let config = Config::load()?;
    if config.storage.allow_http {
        return Err("provider smoke requires external HTTPS storage".into());
    }
    let (store, signer) = storage::build(&config)?;
    let prefix = format!("smoke/{}", uuid::Uuid::now_v7());
    direct_upload_contract(&store, &config.storage, &prefix).await?;
    if std::env::var("STORAGE_BROWSER_CHECK").as_deref() == Ok("true") {
        browser_contract(&config.storage, &store, &signer).await?;
    }
    let source = Path::from(format!("{prefix}/source"));
    let copied = Path::from(format!("{prefix}/copied"));
    let test = async {
        let data = Bytes::from_static(b"\0openlet-provider\xff");
        store
            .put(&source, PutPayload::from(data.clone()))
            .await
            .map_err(|_| "put failed")?;
        store
            .copy(&source, &copied)
            .await
            .map_err(|_| "copy failed")?;
        let bytes = store
            .get(&copied)
            .await
            .map_err(|_| "get failed")?
            .bytes()
            .await
            .map_err(|_| "body failed")?;
        if bytes != data {
            return Err("provider changed bytes");
        }
        let bytes = store
            .get_opts(
                &source,
                GetOptions {
                    range: Some(GetRange::Bounded(1..5)),
                    ..Default::default()
                },
            )
            .await
            .map_err(|_| "range failed")?
            .bytes()
            .await
            .map_err(|_| "range body failed")?;
        if bytes != data.slice(1..5) {
            return Err("provider range mismatch");
        }
        use object_store::signer::Signer;
        let direct = signer
            .signed_url_opts(
                axum::http::Method::GET,
                &source,
                std::time::Duration::from_secs(60),
                &super::download_options("provider ü.bin"),
            )
            .await
            .map_err(|_| "GET signing failed")?;
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(15))
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|_| "HTTP configuration failed")?;
        let response = client
            .get(direct)
            .header("range", "bytes=1-4")
            .send()
            .await
            .map_err(|_| "signed GET failed")?;
        if response.status() != axum::http::StatusCode::PARTIAL_CONTENT
            || response
                .headers()
                .get("content-type")
                .and_then(|v| v.to_str().ok())
                != Some("application/octet-stream")
            || response
                .headers()
                .get("content-disposition")
                .and_then(|v| v.to_str().ok())
                .is_none_or(|v| !v.contains("provider%20%C3%BC.bin"))
            || response
                .bytes()
                .await
                .map_err(|_| "signed GET body failed")?
                != data.slice(1..5)
        {
            return Err("signed GET/range/attachment contract mismatch");
        }
        let url = format!(
            "{}/{}/{}",
            config.storage.endpoint.trim_end_matches('/'),
            config.storage.bucket,
            source
        );
        let anonymous = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(15))
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|_| "HTTP configuration failed")?
            .get(url)
            .send()
            .await
            .map_err(|_| "anonymous check failed")?;
        if anonymous.status().is_success() {
            return Err("bucket permits anonymous object reads");
        }
        Ok(())
    }
    .await;
    let first = store.delete(&source).await;
    let second = store.delete(&copied).await;
    test.map_err(str::to_owned)?;
    first.map_err(|_| "source cleanup failed")?;
    second.map_err(|_| "copy cleanup failed")?;
    match store.get(&source).await {
        Err(object_store::Error::NotFound { .. }) => Ok(()),
        _ => Err("deleted key is still readable".into()),
    }
}

/// The same protocol gate runs against pinned local storage and the selected external provider.
pub async fn direct_upload_contract(
    store: &object_store::aws::AmazonS3,
    signing_config: &crate::config::StorageConfig,
    prefix: &str,
) -> Result<(), String> {
    use object_store::multipart::{MultipartStore, PartId};
    use std::time::Duration;
    let key = format!("{prefix}/conditional");
    let multipart_key = format!("{prefix}/multipart");
    let path = Path::from(key.clone());
    let multipart_path = Path::from(multipart_key.clone());
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(30))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|_| "cannot build provider client")?;
    let mut multipart_id = None;
    let check = async {
        let signed = super::transfers::upload_url(
            signing_config,
            &key,
            5,
            "XUFAKrxLKna5cZ2REBfFkg==",
            Duration::from_secs(60),
            None,
        )
        .await
        .map_err(|_| "cannot sign conditional upload")?;
        for missing in ["content-md5", "if-none-match"] {
            let mut request = client.put(&signed.url).body("hello");
            for (name, value) in &signed.headers {
                if name != missing {
                    request = request.header(name, value);
                }
            }
            let response = request
                .send()
                .await
                .map_err(|_| "header-removal request failed")?;
            if response.status().is_success() {
                return Err("provider accepted missing signed header");
            }
        }
        for wrong_body in ["HELLO", "hi"] {
            let mut request = client.put(&signed.url).body(wrong_body);
            for (name, value) in &signed.headers {
                request = request.header(name, value);
            }
            let response = request
                .send()
                .await
                .map_err(|_| "integrity request failed")?;
            if response.status().is_success() {
                return Err("provider accepted incorrect checksum or length");
            }
        }
        for (name, changed) in [
            ("content-md5", "AAAAAAAAAAAAAAAAAAAAAA=="),
            ("if-none-match", "\"other\""),
        ] {
            let mut request = client.put(&signed.url).body("hello");
            for (header, value) in &signed.headers {
                request = request.header(header, if header == name { changed } else { value });
            }
            if request
                .send()
                .await
                .map_err(|_| "altered-header request failed")?
                .status()
                .is_success()
            {
                return Err("provider accepted altered signed header");
            }
        }
        let put = || {
            let mut request = client.put(&signed.url).body("hello");
            for (name, value) in &signed.headers {
                request = request.header(name, value);
            }
            request
        };
        let (first, second) = tokio::join!(put().send(), put().send());
        let first = first
            .map_err(|_| "concurrent conditional PUT failed")?
            .status();
        let second = second
            .map_err(|_| "concurrent conditional PUT failed")?
            .status();
        let (winner, loser) = if first.is_success() {
            (first, second)
        } else {
            (second, first)
        };
        if !winner.is_success() || !matches!(loser.as_u16(), 409 | 412) {
            if first.is_success() && second.is_success() {
                return Err("provider admitted both concurrent conditional writers");
            }
            if !first.is_success() && !second.is_success() {
                return Err("provider rejected both concurrent conditional writers");
            }
            return Err("provider did not admit exactly one conditional writer");
        }
        let replay = put()
            .send()
            .await
            .map_err(|_| "conditional replay failed")?;
        if replay.status() != axum::http::StatusCode::PRECONDITION_FAILED {
            return Err("provider did not enforce immutable conditional PUT");
        }
        let head = store
            .head(&path)
            .await
            .map_err(|_| "conditional HEAD failed")?;
        if head.size != 5 || head.e_tag.as_deref() != Some("\"5d41402abc4b2a76b9719d911017c592\"") {
            return Err("conditional size/checksum evidence mismatch");
        }
        let id = store
            .create_multipart(&multipart_path)
            .await
            .map_err(|_| "create multipart failed")?;
        multipart_id = Some(id.clone());
        let bodies = [vec![b'a'; 5 * 1024 * 1024], b"last part".to_vec()];
        let checksums = ["ebKBBg0ze5srhMzzkK3PdA==", "yk1/IZBsZ8aQJ2jcxpXxDA=="];
        let mut receipts = Vec::new();
        for (index, (body, checksum)) in bodies.iter().zip(checksums).enumerate() {
            let signed = super::transfers::upload_url(
                signing_config,
                &multipart_key,
                body.len() as u64,
                checksum,
                Duration::from_secs(60),
                Some((&id, index as u32 + 1)),
            )
            .await
            .map_err(|_| "part signing failed")?;
            let mut request = client.put(&signed.url).body(body.clone());
            for (name, value) in &signed.headers {
                request = request.header(name, value);
            }
            let response = request.send().await.map_err(|_| "part PUT failed")?;
            if !response.status().is_success() {
                return Err("provider rejected valid signed part");
            }
            let etag = response
                .headers()
                .get("etag")
                .and_then(|v| v.to_str().ok())
                .ok_or("missing part ETag")?;
            receipts.push(PartId {
                content_id: etag.to_owned(),
            });
        }
        let complete = store
            .complete_multipart(&multipart_path, &id, receipts)
            .await
            .map_err(|_| "multipart completion failed")?;
        let head = store
            .head(&multipart_path)
            .await
            .map_err(|_| "multipart HEAD failed")?;
        if head.size != (5 * 1024 * 1024 + 9) || head.e_tag != complete.e_tag {
            return Err("multipart completion evidence mismatch");
        }
        let body = store
            .get(&multipart_path)
            .await
            .map_err(|_| "multipart GET failed")?
            .bytes()
            .await
            .map_err(|_| "multipart body failed")?;
        if body[..5 * 1024 * 1024] != bodies[0] || body[5 * 1024 * 1024..] != bodies[1] {
            return Err("multipart changed bytes");
        }
        Ok(())
    }
    .await;
    if let Some(id) = multipart_id {
        // A completed upload may already be absent; deletion below still cleans its object.
        let _ = store.abort_multipart(&multipart_path, &id).await;
    }
    let clean_single = store.delete(&path).await;
    let clean_multipart = store.delete(&multipart_path).await;
    check.map_err(str::to_owned)?;
    clean_single.map_err(|_| "conditional test cleanup failed")?;
    clean_multipart.map_err(|_| "multipart test cleanup failed")?;
    Ok(())
}

pub async fn browser_contract(
    config: &crate::config::StorageConfig,
    store: &object_store::aws::AmazonS3,
    signer: &object_store::aws::AmazonS3,
) -> Result<(), String> {
    use object_store::signer::Signer;
    use tokio::io::AsyncWriteExt;
    let key = format!("smoke/{}/browser", uuid::Uuid::now_v7());
    let path = Path::from(key.clone());
    let upload = super::transfers::upload_url(
        config,
        &key,
        5,
        "XUFAKrxLKna5cZ2REBfFkg==",
        std::time::Duration::from_secs(60),
        None,
    )
    .await
    .map_err(|_| "browser upload signing failed")?;
    let download = signer
        .signed_url_opts(
            axum::http::Method::GET,
            &path,
            std::time::Duration::from_secs(60),
            &super::download_options("browser.txt"),
        )
        .await
        .map_err(|_| "browser GET signing failed")?;
    let payload =
        serde_json::to_vec(&serde_json::json!({"upload":upload,"download":download.as_str()}))
            .map_err(|_| "browser input failed")?;
    let check = async {
        let python = std::env::var("STORAGE_BROWSER_PYTHON").unwrap_or_else(|_| "python3".into());
        let mut child = tokio::process::Command::new(python)
            .arg(
                std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                    .join("../../scripts/test-storage-browser.py"),
            )
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .map_err(|_| "cannot start browser check")?;
        let mut stdin = child.stdin.take().ok_or("browser stdin unavailable")?;
        stdin
            .write_all(&payload)
            .await
            .map_err(|_| "browser input write failed")?;
        drop(stdin);
        let output =
            tokio::time::timeout(std::time::Duration::from_secs(90), child.wait_with_output())
                .await
                .map_err(|_| "browser check deadline exceeded")?
                .map_err(|_| "browser process failed")?;
        if !output.status.success() {
            let diagnostic = String::from_utf8_lossy(&output.stderr)
                .replace(&upload.url, "[redacted upload capability]")
                .replace(download.as_str(), "[redacted download capability]");
            eprintln!("{}", diagnostic.chars().take(4000).collect::<String>());
            return Err("browser protocol/CORS check failed");
        }
        Ok(())
    }
    .await;
    let cleanup = store.delete(&path).await;
    check.map_err(str::to_owned)?;
    cleanup.map_err(|_| "browser object cleanup failed")?;
    Ok(())
}
