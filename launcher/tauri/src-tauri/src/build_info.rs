//! The source revision this launcher was built from (embedded by build.rs).
//! Later releases use it to fetch the matching sources for the game build.

use serde::Serialize;

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BuildInfo {
    /// Full commit id, or "unknown" when the build had no git data.
    pub commit: String,
    /// The working tree had uncommitted changes, so the commit alone does not
    /// describe the sources.
    pub dirty: bool,
    /// Short text for the window, e.g. "a1b2c3d4 (modified)".
    pub label: String,
}

pub fn label(commit: &str, dirty: bool) -> String {
    let short: String = commit.chars().take(8).collect();
    if dirty {
        format!("{short} (modified)")
    } else {
        short
    }
}

impl BuildInfo {
    pub fn new(commit: &str, dirty: bool) -> Self {
        Self {
            commit: commit.into(),
            dirty,
            label: label(commit, dirty),
        }
    }

    pub fn current() -> Self {
        Self::new(env!("SOTR_COMMIT"), env!("SOTR_DIRTY") == "1")
    }

    /// Remote the sources are fetched from (embedded by build.rs).
    pub fn repository() -> &'static str {
        env!("SOTR_REPO")
    }

    /// The commit can name a downloadable source archive: known and unmodified.
    pub fn fetchable(&self) -> bool {
        !self.dirty && self.commit.len() == 40 && self.commit.bytes().all(|b| b.is_ascii_hexdigit())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn labels_are_short_and_flag_local_changes() {
        let id = "c94f5ebdcb3c9d1a460ca48e04f9758448f8d518";
        assert_eq!(label(id, false), "c94f5ebd");
        assert_eq!(label(id, true), "c94f5ebd (modified)");
        assert_eq!(label("unknown", false), "unknown");
    }

    #[test]
    fn only_clean_full_commits_can_be_fetched() {
        let id = "c94f5ebdcb3c9d1a460ca48e04f9758448f8d518";
        assert!(BuildInfo::new(id, false).fetchable());
        assert!(!BuildInfo::new(id, true).fetchable());
        assert!(!BuildInfo::new("unknown", false).fetchable());
        assert!(!BuildInfo::new("c94f5ebd", false).fetchable());
    }

    #[test]
    fn the_embedded_revision_is_present() {
        assert!(!BuildInfo::current().commit.is_empty());
    }
}
