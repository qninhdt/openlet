use crate::http::ApiError;
use axum::http::StatusCode;

pub fn parse(value: Option<&str>, size: u64) -> Result<Option<(u64, u64)>, ApiError> {
    let invalid = || {
        ApiError(
            StatusCode::RANGE_NOT_SATISFIABLE,
            "INVALID_RANGE",
            "one satisfiable byte range required",
        )
    };
    let Some(value) = value else { return Ok(None) };
    let value = value.strip_prefix("bytes=").ok_or_else(invalid)?;
    if value.contains(',') || size == 0 {
        return Err(invalid());
    }
    let (start, end) = value.split_once('-').ok_or_else(invalid)?;
    let number = |s: &str| -> Result<u64, ApiError> {
        if s.is_empty() || !s.bytes().all(|b| b.is_ascii_digit()) {
            return Err(invalid());
        }
        s.parse().map_err(|_| invalid())
    };
    let result = if start.is_empty() {
        let suffix = number(end)?;
        if suffix == 0 {
            return Err(invalid());
        }
        (size.saturating_sub(suffix), size - 1)
    } else {
        let start = number(start)?;
        let end = if end.is_empty() {
            size - 1
        } else {
            number(end)?.min(size - 1)
        };
        if start >= size || start > end {
            return Err(invalid());
        }
        (start, end)
    };
    Ok(Some(result))
}
#[cfg(test)]
mod tests {
    #[test]
    fn single_range() {
        use super::parse;
        assert_eq!(parse(Some("bytes=-2"), 5).unwrap(), Some((3, 4)));
        assert_eq!(parse(Some("bytes=1-99"), 5).unwrap(), Some((1, 4)));
        assert_eq!(parse(Some("bytes=0-"), 5).unwrap(), Some((0, 4)));
        for value in [
            "bytes=0-1,3-4",
            "bytes=5-",
            "bytes=-0",
            "bytes=+1-",
            "bytes=2-1",
        ] {
            assert!(parse(Some(value), 5).is_err());
        }
        assert!(parse(Some("bytes=0-0"), 0).is_err());
    }
}
