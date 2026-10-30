use crate::http::ApiError;
use serde::{Deserialize, Serialize};
use serde_json::json;
use sqlx::{PgConnection, Row};
use uuid::Uuid;

pub const MAX_DEPTH: usize = 128;
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Locator {
    pub node_id: Option<Uuid>,
    pub path: Option<String>,
    pub cwd_id: Option<Uuid>,
    pub expected_node_id: Option<Uuid>,
    pub expected_parent_id: Option<Uuid>,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Mount {
    pub path: String,
    pub filesystem_id: Uuid,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Scope {
    pub actor_id: Uuid,
    pub mounts: Vec<Mount>,
}
pub fn node_alias(name: &str) -> Option<Uuid> {
    let name = name.strip_prefix('@')?;
    let id = Uuid::parse_str(name).ok()?;
    id.hyphenated()
        .to_string()
        .eq_ignore_ascii_case(name)
        .then_some(id)
}
fn parts(fs: Uuid, scope: &Scope, l: &Locator) -> Result<Vec<String>, ApiError> {
    if scope.actor_id.is_nil() || scope.mounts.is_empty() || scope.mounts.len() > 32 {
        return Err(ApiError::bad("invalid trusted scope"));
    }
    if !scope.mounts.iter().any(|m| m.filesystem_id == fs) {
        return Err(ApiError::not_found());
    }
    if let Some(id) = l.node_id {
        if id.is_nil() || l.path.is_some() || l.cwd_id.is_some() {
            return Err(ApiError::bad("invalid locator"));
        }
        return Ok(vec![]);
    }
    let path = l
        .path
        .as_deref()
        .ok_or_else(|| ApiError::bad("locator required"))?;
    if path.len() > 4096 || path.contains('\0') || path.is_empty() {
        return Err(ApiError::bad("invalid path"));
    }
    let suffix = if path.starts_with('/') {
        if l.cwd_id.is_some() {
            return Err(ApiError::bad("absolute path cannot have cwd"));
        }
        let mount = scope
            .mounts
            .iter()
            .filter(|m| {
                path == m.path
                    || (path.starts_with(&m.path)
                        && path.as_bytes().get(m.path.len()) == Some(&b'/'))
                    || m.path == "/"
            })
            .max_by_key(|m| m.path.len())
            .ok_or_else(ApiError::not_found)?;
        if mount.filesystem_id != fs {
            return Err(ApiError::cross_filesystem());
        }
        if !mount.path.starts_with('/')
            || (mount.path != "/" && mount.path.ends_with('/'))
            || mount.path.split('/').any(|p| p == ".." || p == ".")
        {
            return Err(ApiError::bad("invalid mount"));
        }
        &path[mount.path.len()..]
    } else {
        path
    };
    let out: Vec<String> = suffix
        .split('/')
        .filter(|p| !p.is_empty() && *p != ".")
        .map(String::from)
        .collect();
    if out.len() > MAX_DEPTH || out.iter().any(|p| p.len() > 255) {
        return Err(ApiError::bad("path bound exceeded"));
    }
    Ok(out)
}
// Resolve a whole bounded batch in one statement; ancestry and paths share its snapshot.
pub async fn resolve(
    conn: &mut PgConnection,
    fs: Uuid,
    root: Uuid,
    scope: &Scope,
    locators: &[Locator],
) -> Result<Vec<super::nodes::Node>, ApiError> {
    if locators.is_empty() || locators.len() > 100 {
        return Err(ApiError::bad("locator batch must contain 1..100 items"));
    }
    let mut requests = vec![];
    for (idx, l) in locators.iter().enumerate() {
        let mut components = parts(fs, scope, l)?;
        let mut start = l.node_id.or(l.cwd_id).unwrap_or(root);
        if l.path.is_some()
            && start == root
            && let Some(id) = components.first().and_then(|name| node_alias(name))
        {
            start = id;
            components.remove(0);
        }
        requests.push(json!({"idx":idx as i32,"start_id":start,"parts":components}));
    }
    let rows=sqlx::query(r#"
WITH RECURSIVE req AS (
 SELECT * FROM jsonb_to_recordset($3) AS x(idx int,start_id uuid,parts text[])
), ancestors(idx,id,parent_id,depth) AS (
 SELECT r.idx,n.id,n.parent_id,0 FROM req r JOIN nodes n ON n.id=r.start_id AND n.filesystem_id=$1
 UNION ALL SELECT a.idx,n.id,n.parent_id,a.depth+1 FROM ancestors a JOIN nodes n ON n.id=a.parent_id AND n.filesystem_id=$1 WHERE a.id<>$2 AND a.depth<128
), live AS (SELECT DISTINCT idx FROM ancestors WHERE id=$2), walk(idx,pos,id,parent_id,kind) AS (
 SELECT r.idx,0,n.id,n.parent_id,n.kind FROM req r JOIN live l USING(idx) JOIN nodes n ON n.id=r.start_id AND n.filesystem_id=$1
 UNION ALL SELECT w.idx,w.pos+1,n.id,n.parent_id,n.kind FROM walk w JOIN req r USING(idx)
 JOIN nodes n ON n.filesystem_id=$1 AND CASE WHEN r.parts[w.pos+1]='..' THEN n.id=w.parent_id AND w.id<>$2 ELSE n.parent_id=w.id AND n.name=r.parts[w.pos+1] END
 WHERE w.pos<cardinality(r.parts)
), resolved AS (
 SELECT r.idx,n.* FROM walk w JOIN req r USING(idx) JOIN nodes n ON n.id=w.id AND n.filesystem_id=$1 WHERE w.pos=cardinality(r.parts)
), provenance(idx,id,parent_id,kind,depth) AS (
 SELECT idx,id,parent_id,kind,0 FROM resolved
 UNION ALL SELECT a.idx,n.id,n.parent_id,n.kind,a.depth+1 FROM provenance a
 JOIN nodes n ON n.id=a.parent_id AND n.filesystem_id=$1 WHERE a.id<>$2 AND a.depth<128
)
SELECT r.*,p.artifact_readonly FROM resolved r JOIN (
 SELECT idx,bool_or(depth>0 AND kind='file') AS artifact_readonly FROM provenance GROUP BY idx
) p USING(idx) ORDER BY r.idx
"#).bind(fs).bind(root).bind(json!(requests)).fetch_all(conn).await?;
    if rows.len() != locators.len() {
        return Err(ApiError::not_found());
    }
    let mut out = vec![];
    for (idx, row) in rows.iter().enumerate() {
        if row.get::<i32, _>("idx") != idx as i32 {
            return Err(ApiError::not_found());
        }
        out.push(super::nodes::Node::from_row(row));
    }
    Ok(out)
}
pub fn guard(locator: &Locator, id: Uuid, parent: bool) -> Result<(), ApiError> {
    if locator.path.is_some() {
        let expected = if parent {
            locator.expected_parent_id
        } else {
            locator.expected_node_id
        };
        if expected.is_none() {
            return Err(ApiError::precondition_required());
        }
        if expected != Some(id) {
            return Err(ApiError::target_mismatch());
        }
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn mounts_use_segment_boundaries_and_exact_bytes() {
        let fs = Uuid::now_v7();
        let other = Uuid::now_v7();
        let scope = Scope {
            actor_id: Uuid::now_v7(),
            mounts: vec![
                Mount {
                    path: "/drive".into(),
                    filesystem_id: fs,
                },
                Mount {
                    path: "/drive/chat".into(),
                    filesystem_id: other,
                },
            ],
        };
        let l = |p: &str| Locator {
            node_id: None,
            path: Some(p.into()),
            cwd_id: None,
            expected_node_id: None,
            expected_parent_id: None,
        };
        assert_eq!(
            parts(fs, &scope, &l("/drive/a/../Việt")).unwrap(),
            vec!["a", "..", "Việt"]
        );
        assert!(parts(fs, &scope, &l("/driver/a")).is_err());
        assert!(parts(fs, &scope, &l("/drive/chat/a")).is_err());
        assert!(parts(fs, &scope, &l("/drive/\0")).is_err());
    }
    #[test]
    fn aliases_require_canonical_hyphenated_names() {
        let id = Uuid::now_v7();
        assert_eq!(node_alias(&format!("@{id}")), Some(id));
        assert_eq!(
            node_alias(&format!("@{}", id.to_string().to_uppercase())),
            Some(id)
        );
        let legacy = Uuid::parse_str("a930c780-a017-45a7-8877-0303ef2788c9").unwrap();
        assert_eq!(node_alias(&format!("@{legacy}")), Some(legacy));
        for name in [
            "@notes".to_owned(),
            id.to_string(),
            format!("@{}", id.simple()),
            format!("@{{{id}}}"),
        ] {
            assert!(node_alias(&name).is_none());
        }
    }
}
