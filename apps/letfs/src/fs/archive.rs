use super::{
    nodes,
    paths::{Locator, Scope},
};
use crate::http::{ApiError, App};
use sqlx::Row;
use std::collections::BTreeSet;
use unicode_normalization::UnicodeNormalization;
use uuid::Uuid;

#[derive(Clone, Debug)]
pub struct Entry {
    pub id: Uuid,
    pub parent: Option<Uuid>,
    pub name: String,
    pub path: String,
    pub kind: String,
    pub revision: i64,
    pub size: i64,
    pub key: Option<String>,
}
pub struct Archive {
    pub filesystem: Uuid,
    pub name: String,
    pub entries: Vec<Entry>,
}

pub fn safe_component(name: &str) -> Result<(), ApiError> {
    super::validate_name(name)?;
    let stem = name.split('.').next().unwrap().to_ascii_uppercase();
    if name
        .chars()
        .any(|c| c.is_control() || "\\:<>\"|?*".contains(c))
        || name.ends_with(['.', ' '])
        || matches!(stem.as_str(), "CON" | "PRN" | "AUX" | "NUL")
        || (stem.chars().count() == 4
            && (stem.starts_with("COM") || stem.starts_with("LPT"))
            && matches!(stem.chars().last(), Some('1'..='9' | '¹' | '²' | '³')))
    {
        return Err(ApiError::bad("unsafe archive name"));
    }
    Ok(())
}

fn collision_key(path: &str) -> String {
    path.nfc().flat_map(char::to_lowercase).nfc().collect()
}

pub async fn preflight(
    app: &App,
    fs: Uuid,
    node: Uuid,
    scope: &Scope,
) -> Result<Archive, ApiError> {
    let mut s = nodes::session(app, fs, false).await?;
    let locator = Locator {
        node_id: Some(node),
        path: None,
        cwd_id: None,
        expected_node_id: None,
        expected_parent_id: None,
    };
    let selected = s.resolve(scope, &locator).await?;
    selected.directory()?;
    let rows = sqlx::query(r#"WITH RECURSIVE tree AS (
        SELECT n.*, ''::text COLLATE pg_catalog."C" AS path,0 AS depth FROM nodes n WHERE n.filesystem_id=$1 AND n.id=$2
        UNION ALL SELECT n.*,CASE WHEN t.path='' THEN n.name ELSE t.path||'/'||n.name END,t.depth+1
        FROM tree t JOIN nodes n ON n.filesystem_id=$1 AND n.parent_id=t.id
        WHERE t.kind='directory' AND t.depth<128
    ) SELECT t.*,d.object_key,d.storage_kind FROM tree t LEFT JOIN files d ON d.node_id=t.id LIMIT $3"#)
        .bind(fs).bind(node).bind(app.config.archive.max_entries+2).fetch_all(&mut *s.tx).await?;
    if rows.len() as i64 > app.config.archive.max_entries + 1 {
        return Err(ApiError::state("RESOURCE_LIMIT"));
    }
    let mut names = BTreeSet::new();
    let mut total = 0_i64;
    let mut entries = Vec::with_capacity(rows.len());
    for row in rows {
        let id = row.get("id");
        let path: String = row.get("path");
        if id != node {
            for part in path.split('/') {
                safe_component(part)?;
            }
            if path.len() > 4096 || !names.insert(collision_key(&path)) {
                return Err(ApiError::bad("ambiguous archive path"));
            }
        }
        let kind: String = row.get("kind");
        let size: i64 = row.get("size_bytes");
        if kind == "file" && row.get::<Option<String>, _>("storage_kind").is_none() {
            return Err(ApiError::state("SOURCE_CHANGED"));
        }
        total = total
            .checked_add(size)
            .ok_or_else(|| ApiError::state("RESOURCE_LIMIT"))?;
        if total > app.config.archive.max_source_bytes {
            return Err(ApiError::state("RESOURCE_LIMIT"));
        }
        entries.push(Entry {
            id,
            parent: row.get("parent_id"),
            name: row.get("name"),
            path,
            kind,
            revision: row.get("revision"),
            size,
            key: row.get("object_key"),
        });
    }
    entries.sort_by(|a, b| a.path.cmp(&b.path));
    Ok(Archive {
        filesystem: fs,
        name: format!("{}.zip", selected.name),
        entries,
    })
}
#[cfg(test)]
mod tests {
    #[test]
    fn archive_names_detect_case_and_unicode_normalization_collisions() {
        assert_eq!(
            super::collision_key("Folder/É.txt"),
            super::collision_key("folder/e\u{301}.txt")
        );
        assert_ne!(super::collision_key("é.txt"), super::collision_key("e.txt"));
    }
    #[test]
    fn archive_names_reject_extraction_ambiguity() {
        for name in [
            "",
            ".",
            "..",
            "a/b",
            "a\\b",
            "/root",
            "C:drive",
            "CON.txt",
            "lpt1",
            "a.",
            "a ",
            "x\ny",
            "a?b",
            "COM¹.txt",
            "LPT²",
            "com³.csv",
        ] {
            assert!(super::safe_component(name).is_err(), "{name}");
        }
        for name in ["Việt Nam", "report.pdf", "composition", "COM10.txt"] {
            assert!(super::safe_component(name).is_ok());
        }
    }
}
