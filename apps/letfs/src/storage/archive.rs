use crate::{
    fs::{
        archive::{Archive, Entry},
        nodes,
    },
    http::{ApiError, App},
};
use async_zip::{Compression, ZipEntryBuilder, base::write::ZipFileWriter};
use bytes::Bytes;
use futures::{AsyncWriteExt, Stream, TryStreamExt};
use object_store::{ObjectStoreExt, path::Path};
use opentelemetry::trace::FutureExt;
use sqlx::Row;
use std::{collections::BTreeMap, io, time::Duration};
use tokio::{io::AsyncReadExt, sync::OwnedSemaphorePermit, time::Instant};
use tracing::Instrument;

fn archive_error<T>(_: T) -> ApiError {
    ApiError::state("ARCHIVE_FAILED")
}

async fn payload(
    app: &App,
    archive: &Archive,
    entry: &Entry,
    expected: &BTreeMap<uuid::Uuid, &Entry>,
) -> Result<Option<Vec<u8>>, ApiError> {
    let mut s = nodes::session(app, archive.filesystem, false).await?;
    let rows = sqlx::query(r#"WITH RECURSIVE ancestors AS (
        SELECT n.*,0 AS depth FROM nodes n WHERE n.id=$1 AND n.filesystem_id=$2
        UNION ALL SELECT n.*,a.depth+1 FROM ancestors a JOIN nodes n ON n.id=a.parent_id AND n.filesystem_id=$2
        WHERE a.id<>$3 AND a.depth<128
    ) SELECT a.*,d.object_key,CASE WHEN a.id=$1 THEN d.inline_bytes END AS inline_bytes
    FROM ancestors a LEFT JOIN files d ON d.node_id=a.id ORDER BY depth"#)
        .bind(entry.id).bind(archive.filesystem).bind(s.root).fetch_all(&mut *s.tx).await?;
    if rows
        .last()
        .is_none_or(|r| r.get::<uuid::Uuid, _>("id") != s.root)
    {
        return Err(ApiError::state("SOURCE_CHANGED"));
    }
    for row in &rows {
        if let Some(prior) = expected.get(&row.get::<uuid::Uuid, _>("id"))
            && (row.get::<Option<uuid::Uuid>, _>("parent_id") != prior.parent
                || row.get::<String, _>("name") != prior.name
                || row.get::<String, _>("kind") != prior.kind
                || row.get::<i64, _>("revision") != prior.revision
                || row.get::<i64, _>("size_bytes") != prior.size
                || row.get::<Option<String>, _>("object_key") != prior.key)
        {
            return Err(ApiError::state("SOURCE_CHANGED"));
        }
    }
    Ok(rows[0].get("inline_bytes"))
}

async fn produce(
    app: &App,
    archive: &Archive,
    output: tokio::io::DuplexStream,
) -> Result<(), ApiError> {
    let mut zip = ZipFileWriter::with_tokio(output).force_zip64();
    let expected = archive.entries.iter().map(|e| (e.id, e)).collect();
    let mut total = 0_i64;
    for entry in &archive.entries {
        let inline = payload(app, archive, entry, &expected).await?;
        if entry.path.is_empty() {
            continue;
        }
        let path = if entry.kind == "directory" {
            format!("{}/", entry.path)
        } else {
            entry.path.clone()
        };
        let mut writer = zip
            .write_entry_stream(ZipEntryBuilder::new(path.into(), Compression::Stored))
            .await
            .map_err(archive_error)?;
        if entry.kind == "file" {
            let mut count = 0_i64;
            if let Some(key) = &entry.key {
                let mut input = app
                    .storage
                    .get(&Path::from(key.as_str()))
                    .await
                    .map_err(crate::storage::error)?
                    .into_stream();
                while let Some(chunk) = input.try_next().await.map_err(crate::storage::error)? {
                    count = count
                        .checked_add(chunk.len() as i64)
                        .ok_or_else(|| ApiError::state("RESOURCE_LIMIT"))?;
                    if count > entry.size {
                        return Err(ApiError::state("SOURCE_CHANGED"));
                    }
                    writer.write_all(&chunk).await.map_err(archive_error)?;
                }
            } else {
                let bytes = inline.ok_or_else(|| ApiError::state("SOURCE_CHANGED"))?;
                count = bytes.len() as i64;
                if count != entry.size {
                    return Err(ApiError::state("SOURCE_CHANGED"));
                }
                writer.write_all(&bytes).await.map_err(archive_error)?;
            }
            if count != entry.size {
                return Err(ApiError::state("SOURCE_CHANGED"));
            }
            total = total
                .checked_add(count)
                .ok_or_else(|| ApiError::state("RESOURCE_LIMIT"))?;
            if total > app.config.archive.max_source_bytes {
                return Err(ApiError::state("RESOURCE_LIMIT"));
            }
        }
        writer.close().await.map_err(archive_error)?;
    }
    zip.close().await.map_err(archive_error)?;
    Ok(())
}

// Both futures belong to the body: disconnect drops the producer and its active storage request.
pub fn stream(
    app: App,
    archive: Archive,
    permit: OwnedSemaphorePermit,
    deadline: Instant,
) -> impl Stream<Item = Result<Bytes, io::Error>> + Send {
    let max_bytes = app.config.archive.max_output_bytes;
    let (output, input) = tokio::io::duplex(65536);
    let producer = Box::pin(
        async move {
            produce(&app, &archive, output)
                .await
                .inspect_err(|e| tracing::warn!(code = e.1, "archive stream failed"))
        }
        .instrument(tracing::Span::current())
        .with_current_context(),
    );
    futures::stream::try_unfold(
        (input, Some(producer), permit, 0_i64),
        move |(mut input, mut producer, permit, total)| async move {
            let read = async {
                let mut buffer = vec![0; 65536];
                let count = if let Some(work) = producer.as_mut() {
                    tokio::select! {
                        biased;
                        result = work => {
                            result.map_err(|e| io::Error::other(e.1))?;
                            producer=None;
                            input.read(&mut buffer).await?
                        },
                        result = input.read(&mut buffer) => result?,
                    }
                } else {
                    input.read(&mut buffer).await?
                };
                // EOF can win the read race; do not hide a producer failure behind a successful body.
                if count == 0 {
                    if let Some(work) = producer.take() {
                        work.await.map_err(|e| io::Error::other(e.1))?;
                    }
                    return Ok(None);
                }
                let total = total
                    .checked_add(count as i64)
                    .filter(|n| *n <= max_bytes)
                    .ok_or_else(|| io::Error::other("RESOURCE_LIMIT"))?;
                buffer.truncate(count);
                Ok(Some((
                    Bytes::from(buffer),
                    (input, producer, permit, total),
                )))
            };
            tokio::time::timeout_at(deadline, read)
                .await
                .map_err(|_| io::Error::new(io::ErrorKind::TimedOut, "archive deadline"))?
        },
    )
}

pub fn deadline(app: &App) -> Instant {
    Instant::now() + Duration::from_secs(app.config.archive.runtime_seconds as u64)
}
