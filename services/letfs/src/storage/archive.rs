use crate::{
    fs::exports::{Attempt, Entry},
    http::{ApiError, App},
};
use async_zip::{Compression, ZipEntryBuilder, base::write::ZipFileWriter};
use bytes::Bytes;
use futures::{AsyncWriteExt, TryStreamExt};
use object_store::{ObjectStoreExt, multipart::MultipartStore, path::Path};
use sqlx::Row;
use std::collections::BTreeMap;
use tokio::io::AsyncReadExt;

fn archive_error<T>(_: T) -> ApiError {
    ApiError::state("ARCHIVE_FAILED")
}

async fn produce(
    app: &App,
    entries: &[Entry],
    output: tokio::io::DuplexStream,
) -> Result<(), ApiError> {
    let mut zip = ZipFileWriter::with_tokio(output).force_zip64();
    let expected: BTreeMap<_, _> = entries.iter().map(|entry| (entry.id, entry)).collect();
    let mut inline = BTreeMap::<uuid::Uuid, Vec<u8>>::new();
    for (index, entry) in entries.iter().enumerate() {
        let path = if entry.kind == "directory" {
            format!("{}/", entry.path)
        } else {
            entry.path.clone()
        };
        let metadata = ZipEntryBuilder::new(path.into(), Compression::Stored);
        let mut writer = zip
            .write_entry_stream(metadata)
            .await
            .map_err(archive_error)?;
        if entry.kind == "file" {
            if let Some(key) = &entry.key {
                let mut input = app
                    .storage
                    .get(&Path::from(key.as_str()))
                    .await
                    .map_err(crate::storage::error)?
                    .into_stream();
                let mut count = 0_i64;
                while let Some(chunk) = input.try_next().await.map_err(crate::storage::error)? {
                    count = count
                        .checked_add(chunk.len() as i64)
                        .ok_or_else(|| ApiError::state("RESOURCE_LIMIT"))?;
                    if count > entry.size {
                        return Err(ApiError::state("SOURCE_CHANGED"));
                    }
                    writer.write_all(&chunk).await.map_err(archive_error)?;
                }
                if count != entry.size {
                    return Err(ApiError::state("SOURCE_CHANGED"));
                }
            } else {
                if !inline.contains_key(&entry.id) {
                    let mut ids = Vec::new();
                    let mut size = 0;
                    for next in entries[index..]
                        .iter()
                        .filter(|e| e.kind == "file" && e.key.is_none())
                    {
                        if ids.len() == 64 || (size + next.size > 1048576 && !ids.is_empty()) {
                            break;
                        }
                        size += next.size;
                        if size > 1048576 {
                            return Err(ApiError::state("RESOURCE_LIMIT"));
                        }
                        ids.push(next.id);
                    }
                    let rows = sqlx::query("SELECT n.id,n.revision,d.inline_bytes FROM nodes n JOIN file_data d ON d.node_id=n.id WHERE n.id=ANY($1) AND d.storage_kind='inline'")
                        .bind(&ids).fetch_all(&app.pool).await?;
                    if rows.len() != ids.len() {
                        return Err(ApiError::state("SOURCE_CHANGED"));
                    }
                    for row in rows {
                        let id = row.get("id");
                        let expected_entry = expected[&id];
                        let bytes: Vec<u8> = row.get("inline_bytes");
                        if row.get::<i64, _>("revision") != expected_entry.revision
                            || bytes.len() as i64 != expected_entry.size
                        {
                            return Err(ApiError::state("SOURCE_CHANGED"));
                        }
                        inline.insert(id, bytes);
                    }
                }
                let bytes = inline
                    .remove(&entry.id)
                    .ok_or_else(|| ApiError::state("SOURCE_CHANGED"))?;
                writer.write_all(&bytes).await.map_err(archive_error)?;
            }
        }
        writer.close().await.map_err(archive_error)?;
    }
    let writer = zip.close().await.map_err(archive_error)?;
    // Closing the writer signals EOF to the bounded multipart consumer.
    drop(writer);
    Ok(())
}

pub async fn build(app: &App, attempt: &Attempt) -> Result<i64, ApiError> {
    let key = Path::from(attempt.key.as_str());
    let remote = app
        .storage
        .create_multipart(&key)
        .await
        .map_err(crate::storage::error)?;
    let saved = sqlx::query("UPDATE export_attempts a SET multipart_id=$2 WHERE a.id=$1 AND EXISTS(SELECT 1 FROM operations o WHERE o.id=a.operation_id AND o.attempt_id=a.id AND o.state='running')")
        .bind(attempt.id).bind(&remote).execute(&app.pool).await;
    match saved {
        Ok(result) if result.rows_affected() == 1 => {}
        other => {
            let _ = app.storage.abort_multipart(&key, &remote).await;
            return Err(match other {
                Err(e) => e.into(),
                _ => ApiError::state("STALE_EXPORT_ATTEMPT"),
            });
        }
    }
    let (output, mut input) = tokio::io::duplex(65536);
    let upload = async {
        let mut parts = Vec::new();
        let mut total = 0_i64;
        let part_bytes = app.config.storage.multipart_part_bytes.min(8 * 1048576) as usize;
        loop {
            let mut buffer = vec![0; part_bytes];
            let mut used = 0;
            while used < buffer.len() {
                let count = input
                    .read(&mut buffer[used..])
                    .await
                    .map_err(archive_error)?;
                if count == 0 {
                    break;
                }
                used += count;
                total = total
                    .checked_add(count as i64)
                    .ok_or_else(|| ApiError::state("RESOURCE_LIMIT"))?;
                if total > app.config.exports.max_output_bytes {
                    return Err(ApiError::state("RESOURCE_LIMIT"));
                }
            }
            if used == 0 {
                break;
            }
            if parts.len() >= 10000 {
                return Err(ApiError::state("RESOURCE_LIMIT"));
            }
            buffer.truncate(used);
            parts.push(
                app.storage
                    .put_part(&key, &remote, parts.len(), Bytes::from(buffer).into())
                    .await
                    .map_err(crate::storage::error)?,
            );
        }
        app.storage
            .complete_multipart(&key, &remote, parts)
            .await
            .map_err(crate::storage::error)?;
        Ok(total)
    };
    let result = futures::try_join!(produce(app, &attempt.snapshot.entries, output), upload);
    match result {
        Ok(((), size)) => Ok(size),
        Err(e) => {
            // Persisted multipart identity lets maintenance retry cleanup after cancellation or an unknown outcome.
            let _ = app.storage.abort_multipart(&key, &remote).await;
            Err(e)
        }
    }
}
