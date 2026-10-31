use super::{
    indexing::dependency,
    nodes::*,
    paths::{Locator, Scope},
};
use crate::http::{ApiError, App};
use base64::{Engine, prelude::BASE64_URL_SAFE_NO_PAD};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{Row, postgres::PgRow};
use std::collections::{BTreeMap, BTreeSet};
use uuid::Uuid;

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Filters {
    pub parent: Option<Locator>,
    #[serde(rename = "type")]
    pub semantic_type: Option<String>,
    pub media_type: Option<String>,
    pub created_after: Option<DateTime<Utc>>,
    pub created_before: Option<DateTime<Utc>>,
    pub updated_after: Option<DateTime<Utc>>,
    pub updated_before: Option<DateTime<Utc>>,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Input {
    pub query: String,
    #[serde(default)]
    pub filters: Filters,
    pub limit: Option<usize>,
    pub cursor: Option<String>,
    pub sort: Option<String>,
    pub direction: Option<String>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub scope: Scope,
    pub input: Input,
}
#[derive(Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Cursor {
    binding: String,
    value: String,
    id: Option<Uuid>,
    offset: usize,
    seen: Vec<Uuid>,
}
// Traversing only directories stops at original files and excludes their generated artifacts.
const LIVE: &str = r#"WITH RECURSIVE live AS (
    SELECT n.id,n.kind,$3::text COLLATE "C" AS path,0 AS depth FROM nodes n WHERE n.id=$2 AND n.filesystem_id=$1
    UNION ALL SELECT n.id,n.kind,l.path||'/'||n.name,l.depth+1 FROM nodes n JOIN live l ON n.parent_id=l.id WHERE n.filesystem_id=$1 AND l.kind='directory' AND l.depth<128
) "#;
fn validate(input: &Input, semantic: bool) -> Result<usize, ApiError> {
    let limit = input.limit.unwrap_or(20);
    if !(1..=if semantic { 50 } else { 100 }).contains(&limit)
        || input.query.len() > 2000
        || input.query.contains('\0')
        || (semantic && input.query.trim().is_empty())
        || input
            .filters
            .semantic_type
            .as_ref()
            .is_some_and(|v| v.len() > 100 || v.contains('\0'))
        || input
            .filters
            .media_type
            .as_ref()
            .is_some_and(|v| v.len() > 200 || v.contains('\0'))
        || input
            .filters
            .created_after
            .zip(input.filters.created_before)
            .is_some_and(|(a, b)| a > b)
        || input
            .filters
            .updated_after
            .zip(input.filters.updated_before)
            .is_some_and(|(a, b)| a > b)
        || input
            .sort
            .as_deref()
            .is_some_and(|v| !matches!(v, "name" | "created_at" | "updated_at"))
        || input
            .direction
            .as_deref()
            .is_some_and(|v| !matches!(v, "asc" | "desc"))
        || (semantic && (input.sort.is_some() || input.direction.is_some()))
    {
        return Err(ApiError::bad("invalid search input"));
    }
    Ok(limit)
}
fn binding(fs: Uuid, r: &Request, semantic: bool, app: &App) -> String {
    let mut input = r.input.clone();
    input.cursor = None;
    input.query = input.query.trim().into();
    let data = json!({"filesystem":fs,"scope":r.scope,"input":input,"semantic":semantic,
        "vector_space":if semantic {app.config.search.vector_space()} else {Value::Null},
        "reranker":if semantic {app.config.search.rerank_model.as_str()} else {""}});
    format!("{:x}", Sha256::digest(data.to_string()))
}
fn cursor(input: Option<&str>, binding: &str) -> Result<Cursor, ApiError> {
    let Some(input) = input else {
        return Ok(Cursor {
            binding: binding.into(),
            ..Default::default()
        });
    };
    if input.len() > 16384 {
        return Err(ApiError::bad("cursor too large"));
    }
    let c: Cursor = serde_json::from_slice(
        &BASE64_URL_SAFE_NO_PAD
            .decode(input)
            .map_err(|_| ApiError::bad("invalid cursor"))?,
    )
    .map_err(|_| ApiError::bad("invalid cursor"))?;
    if c.binding != binding
        || c.offset > 10000
        || c.seen.len() > 256
        || c.seen.iter().collect::<BTreeSet<_>>().len() != c.seen.len()
        || c.value.len() > 300
    {
        return Err(ApiError::bad("cursor scope mismatch"));
    }
    Ok(c)
}
fn encode(c: &Cursor) -> Result<String, ApiError> {
    Ok(BASE64_URL_SAFE_NO_PAD
        .encode(serde_json::to_vec(c).map_err(|_| ApiError::bad("invalid cursor"))?))
}
async fn root(
    s: &mut Session<'_>,
    scope: &Scope,
    filter: &Filters,
) -> Result<(Uuid, String), ApiError> {
    let locator = filter.parent.clone().unwrap_or(Locator {
        node_id: Some(s.root),
        path: None,
        cwd_id: None,
        expected_node_id: None,
        expected_parent_id: None,
    });
    let n = s.resolve(scope, &locator).await?;
    n.directory()?;
    n.writable()?;
    let path = source_path(s, scope, n.id).await?;
    Ok((n.id, path))
}
async fn source_path(s: &mut Session<'_>, scope: &Scope, id: Uuid) -> Result<String, ApiError> {
    let parts:Vec<String>=sqlx::query_scalar("WITH RECURSIVE a AS (SELECT id,parent_id,name,0 AS depth FROM nodes WHERE id=$1 AND filesystem_id=$2 UNION ALL SELECT n.id,n.parent_id,n.name,a.depth+1 FROM nodes n JOIN a ON n.id=a.parent_id WHERE n.filesystem_id=$2 AND a.id!=$3 AND a.depth<128) SELECT name FROM a WHERE id!=$3 ORDER BY depth DESC")
        .bind(id).bind(s.fs).bind(s.root).fetch_all(&mut *s.tx).await?;
    let mount = scope
        .mounts
        .iter()
        .find(|m| m.filesystem_id == s.fs)
        .ok_or_else(ApiError::not_found)?;
    Ok(if parts.is_empty() {
        mount.path.clone()
    } else {
        format!("{}/{}", mount.path.trim_end_matches('/'), parts.join("/"))
    })
}
const FILTERS: &str = " AND ($4::text IS NULL OR n.semantic_type=$4) AND ($5::text IS NULL OR n.media_type=$5) AND ($6::timestamptz IS NULL OR n.created_at>=$6) AND ($7::timestamptz IS NULL OR n.created_at<=$7) AND ($8::timestamptz IS NULL OR n.updated_at>=$8) AND ($9::timestamptz IS NULL OR n.updated_at<=$9) ";
fn excerpt(text: &str, query: &str, limit: usize) -> String {
    let lower = text.to_lowercase();
    let position = query
        .split_whitespace()
        .filter_map(|word| lower.find(&word.to_lowercase()))
        .min()
        .unwrap_or(0);
    let start = lower[..position].chars().count().saturating_sub(limit / 4);
    text.chars().skip(start).take(limit).collect()
}
fn item(row: &PgRow) -> Value {
    let mut node = json!(Node::from_row(row));
    node.as_object_mut().expect("node object").remove("context");
    let mut v = json!({"node_id":row.get::<Uuid,_>("id"),"filename":row.get::<String,_>("name"),"path":row.get::<String,_>("path")});
    v.as_object_mut()
        .expect("item object")
        .extend(node.as_object().expect("node object").clone());
    v
}
pub async fn basic(app: &App, fs: Uuid, r: Request) -> Result<Value, ApiError> {
    let limit = validate(&r.input, false)?;
    let bind = binding(fs, &r, false, app);
    let c = cursor(r.input.cursor.as_deref(), &bind)?;
    let mut s = session(app, fs, false).await?;
    let (root, path) = root(&mut s, &r.scope, &r.input.filters).await?;
    let sort = r.input.sort.as_deref().unwrap_or("name");
    let desc = r.input.direction.as_deref() == Some("desc");
    let value = if sort == "name" {
        "n.name".to_string()
    } else {
        format!("to_char(n.{sort} AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US') COLLATE \"C\"")
    };
    let op = if desc { "<" } else { ">" };
    let direction = if desc { "DESC" } else { "ASC" };
    let sql = format!(
        "{LIVE} SELECT n.*,l.path,{value} AS sort_value FROM live l JOIN nodes n ON n.id=l.id WHERE n.kind='file' {FILTERS} AND (strpos(lower(n.name),lower($10))>0 OR strpos(lower(coalesce(n.title,'')),lower($10))>0) AND ($11::uuid IS NULL OR ({value},n.id){op}($12::text,$11::uuid)) ORDER BY {value} {direction},n.id {direction} LIMIT $13"
    );
    let f = &r.input.filters;
    // SQL fragments are constants or validated sort/direction choices; values are bound.
    let rows = sqlx::query(sqlx::AssertSqlSafe(sql.as_str()))
        .bind(fs)
        .bind(root)
        .bind(path)
        .bind(&f.semantic_type)
        .bind(&f.media_type)
        .bind(f.created_after)
        .bind(f.created_before)
        .bind(f.updated_after)
        .bind(f.updated_before)
        .bind(r.input.query.trim())
        .bind(c.id)
        .bind(&c.value)
        .bind((limit + 1) as i64)
        .fetch_all(&mut *s.tx)
        .await?;
    let next = if rows.len() > limit {
        let last = &rows[limit - 1];
        Some(encode(&Cursor {
            binding: bind,
            value: last.get("sort_value"),
            id: Some(last.get("id")),
            ..Default::default()
        })?)
    } else {
        None
    };
    Ok(
        json!({"items":rows.iter().take(limit).map(item).collect::<Vec<_>>(),"next_cursor":next,"degraded":false}),
    )
}

#[derive(Clone, Deserialize, Serialize)]
struct Payload {
    filesystem_id: Uuid,
    source_id: Uuid,
    file_id: Uuid,
    operation_id: Uuid,
    text: String,
}
#[derive(Deserialize)]
struct Point {
    payload: Payload,
}
async fn hydrated(
    app: &App,
    fs: Uuid,
    r: &Request,
    points: &[Point],
) -> Result<BTreeMap<usize, Value>, ApiError> {
    let mut s = session(app, fs, false).await?;
    let (root, path) = root(&mut s, &r.scope, &r.input.filters).await?;
    let requests=points.iter().enumerate().filter(|(_,p)|p.payload.filesystem_id==fs).map(|(i,p)|json!({"idx":i,"source_id":p.payload.source_id,"file_id":p.payload.file_id,"operation_id":p.payload.operation_id})).collect::<Vec<_>>();
    let sql = format!(
        r#"{LIVE}, req AS (SELECT * FROM jsonb_to_recordset($10) AS p(idx int,source_id uuid,file_id uuid,operation_id uuid)),
        ancestors AS (SELECT p.idx,p.source_id,p.operation_id,n.id,n.parent_id,0 AS depth,jsonb_build_array(jsonb_build_object('node_id',n.id,'filename',n.name)) AS breadcrumb FROM req p JOIN nodes n ON n.id=p.file_id AND n.filesystem_id=$1
        UNION ALL SELECT a.idx,a.source_id,a.operation_id,n.id,n.parent_id,a.depth+1,jsonb_build_array(jsonb_build_object('node_id',n.id,'filename',n.name))||a.breadcrumb FROM ancestors a JOIN nodes n ON n.id=a.parent_id WHERE n.filesystem_id=$1 AND a.id!=a.source_id AND a.depth<128)
        SELECT a.idx,n.*,l.path,a.breadcrumb FROM ancestors a JOIN live l ON l.id=a.source_id JOIN nodes n ON n.id=l.id
        JOIN operations o ON o.id=a.operation_id AND o.source_id=n.id AND o.filesystem_id=$1 AND o.kind='process-file'
        WHERE a.id=a.source_id AND n.kind='file' AND o.superseded_at IS NULL AND o.state='succeeded' AND o.enrichment_state='succeeded' AND o.index_state='succeeded'
        AND o.embedding_model=$11 AND o.vector_collection=$12 AND o.vector_dimension=$13 {FILTERS}"#
    );
    let f = &r.input.filters;
    // SQL fragments are constants or validated sort/direction choices; values are bound.
    let rows = sqlx::query(sqlx::AssertSqlSafe(sql.as_str()))
        .bind(fs)
        .bind(root)
        .bind(path)
        .bind(&f.semantic_type)
        .bind(&f.media_type)
        .bind(f.created_after)
        .bind(f.created_before)
        .bind(f.updated_after)
        .bind(f.updated_before)
        .bind(json!(requests))
        .bind(&app.config.search.embedding_model)
        .bind(&app.config.search.vector_collection)
        .bind(app.config.search.vector_dimension)
        .fetch_all(&mut *s.tx)
        .await?;
    let mut out = BTreeMap::new();
    for row in rows {
        let idx = row.get::<i32, _>("idx") as usize;
        let point = &points[idx];
        let mut result = item(&row);
        result["matched"] = json!({"file_id":point.payload.file_id,"breadcrumb":row.get::<Value,_>("breadcrumb"),"snippet":excerpt(&point.payload.text,&r.input.query,600)});
        out.insert(idx, result);
    }
    Ok(out)
}
async fn post(
    client: &reqwest::Client,
    url: String,
    key: &str,
    qdrant: bool,
    body: &Value,
) -> Result<Value, ApiError> {
    let request = client.post(url).json(body);
    let request = if qdrant {
        request.header("api-key", key)
    } else {
        request.bearer_auth(key)
    };
    let response = request.send().await.map_err(|_| dependency())?;
    if response.content_length().is_some_and(|n| n > 8 * 1048576) {
        return Err(dependency());
    }
    let mut response = response.error_for_status().map_err(|_| dependency())?;
    let mut bytes = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|_| dependency())? {
        if bytes.len() + chunk.len() > 8 * 1048576 {
            return Err(dependency());
        }
        bytes.extend_from_slice(&chunk);
    }
    serde_json::from_slice(&bytes).map_err(|_| dependency())
}
pub async fn semantic(app: &App, fs: Uuid, r: Request) -> Result<Value, ApiError> {
    let limit = validate(&r.input, true)?.min(50);
    let bind = binding(fs, &r, true, app);
    let mut c = cursor(r.input.cursor.as_deref(), &bind)?;
    // Validate filesystem, scope and parent before sending the query to a provider.
    let mut s = session(app, fs, false).await?;
    root(&mut s, &r.scope, &r.input.filters).await?;
    drop(s);
    let settings = &app.config.search;
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(15))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|_| dependency())?;
    let embedding=post(&client,format!("{}/embeddings",settings.openrouter_url.trim_end_matches('/')),&settings.openrouter_key,false,&json!({"model":settings.embedding_model,"input":[r.input.query.trim()],"dimensions":settings.vector_dimension,"encoding_format":"float"})).await?;
    let vector = embedding["data"]
        .as_array()
        .filter(|v| v.len() == 1)
        .and_then(|v| v[0]["embedding"].as_array())
        .filter(|v| {
            v.len() == settings.vector_dimension as usize
                && v.iter().all(|n| n.as_f64().is_some_and(f64::is_finite))
        })
        .ok_or_else(dependency)?;
    let mut seen = c.seen.iter().copied().collect::<BTreeSet<_>>();
    let mut selected = Vec::<(Point, Value)>::new();
    let mut per_source = BTreeMap::<Uuid, usize>::new();
    let mut exhausted = false;
    for _ in 0..3 {
        if c.offset >= 10000 || seen.len() >= 256 {
            exhausted = true;
            break;
        }
        let size = 80;
        let filter = json!({"must":[{"key":"filesystem_id","match":{"value":fs}}]});
        let raw=post(&client,format!("{}/collections/{}/points/query",settings.qdrant_url.trim_end_matches('/'),settings.vector_collection),&settings.qdrant_key,true,
            &json!({"prefetch":[{"query":vector,"using":"dense","filter":filter,"limit":c.offset+size},{"query":{"text":r.input.query.trim()},"using":"text","filter":filter,"limit":c.offset+size}],"query":{"fusion":"rrf"},"offset":c.offset,"limit":size,"with_payload":true})).await?;
        let points: Vec<Point> =
            serde_json::from_value(raw["result"]["points"].clone()).map_err(|_| dependency())?;
        if points.len() > size {
            return Err(dependency());
        }
        if points.is_empty() {
            exhausted = true;
            break;
        }
        let valid = hydrated(app, fs, &r, &points).await?;
        let received = points.len();
        let mut consumed = 0;
        for (idx, point) in points.into_iter().enumerate() {
            if selected.len() >= 64 {
                break;
            }
            consumed += 1;
            c.offset += 1;
            let Some(item) = valid.get(&idx) else {
                continue;
            };
            let id = point.payload.source_id;
            if c.seen.contains(&id) {
                continue;
            }
            let count = per_source.entry(id).or_default();
            if *count >= 3 {
                continue;
            }
            if !seen.contains(&id) && seen.len() - c.seen.len() >= limit {
                consumed -= 1;
                c.offset -= 1;
                break;
            }
            seen.insert(id);
            *count += 1;
            selected.push((point, item.clone()));
        }
        if consumed < received {
            break;
        }
        if received < size {
            exhausted = true;
            break;
        }
        if seen.len() - c.seen.len() >= limit {
            break;
        }
    }
    let mut degraded = false;
    let mut order = (0..selected.len()).collect::<Vec<_>>();
    if !selected.is_empty() {
        let documents = selected
            .iter()
            .map(|(p, _)| excerpt(&p.payload.text, &r.input.query, 1024))
            .collect::<Vec<_>>();
        let response=post(&client,format!("{}/rerank",settings.openrouter_url.trim_end_matches('/')),&settings.openrouter_key,false,&json!({"model":settings.rerank_model,"query":r.input.query.trim(),"documents":documents,"top_n":documents.len()})).await;
        let ranked = response
            .ok()
            .and_then(|v| v["results"].as_array().cloned())
            .and_then(|rows| {
                let mut ids = BTreeSet::new();
                let mut values = Vec::new();
                for row in rows {
                    let i = row["index"].as_u64()? as usize;
                    if i >= selected.len()
                        || !ids.insert(i)
                        || !row["relevance_score"].as_f64()?.is_finite()
                    {
                        return None;
                    }
                    values.push(i);
                }
                (values.len() == selected.len()).then_some(values)
            });
        if let Some(ranked) = ranked {
            order = ranked;
        } else {
            degraded = true;
        }
    }
    let mut emitted = BTreeSet::new();
    let mut items = Vec::new();
    for idx in order {
        let (point, item) = &selected[idx];
        if emitted.insert(point.payload.source_id) {
            items.push(item.clone());
        }
    }
    c.seen = seen.into_iter().collect();
    let next = if !exhausted && c.seen.len() < 256 && c.offset < 10000 {
        Some(encode(&c)?)
    } else {
        None
    };
    Ok(
        json!({"items":items,"next_cursor":next,"degraded":degraded,"degraded_reason":if degraded {Some("RERANK_UNAVAILABLE")}else{None}}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn search_bounds_and_cursor_binding() {
        let mut input = Input {
            query: "words".into(),
            filters: Filters::default(),
            limit: Some(20),
            cursor: None,
            sort: None,
            direction: None,
        };
        assert!(validate(&input, true).is_ok());
        input.limit = Some(0);
        assert!(validate(&input, false).is_err());
        input.limit = Some(20);
        input.sort = Some("name;DROP TABLE nodes".into());
        assert!(validate(&input, false).is_err());
        let encoded = encode(&Cursor {
            binding: "scope".into(),
            ..Default::default()
        })
        .unwrap();
        assert!(cursor(Some(&encoded), "scope").is_ok());
        assert!(cursor(Some(&encoded), "foreign").is_err());
        assert!(cursor(Some(&"A".repeat(17000)), "scope").is_err());
    }
}
