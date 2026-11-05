//! Fetches the repository sources (scripts, patches, port, lock files) that a
//! launcher outside a source checkout needs to build the game. They are cloned
//! at the commit the launcher was built from into a per-user folder; without
//! git the matching GitHub archive is downloaded instead.

use crate::tools;
use std::{
    fs,
    io::Read,
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::{Mutex, PoisonError},
    time::Duration,
};

/// Characters of the commit id that name its sources folder. Windows paths
/// stop at 260 characters, and the SDK checkout inside this folder already
/// needs about 180 of them.
const FOLDER_COMMIT_LEN: usize = 12;

/// For every git child: no terminal or Git Credential Manager prompt nobody
/// can answer (a 401 from a renamed or private repository fails instead of
/// waiting on a hidden dialog).
pub const GIT_NO_PROMPT: [(&str, &str); 2] = [("GIT_TERMINAL_PROMPT", "0"), ("GCM_INTERACTIVE", "never")];
/// A fetch slower than 1000 bytes/s for a minute gives up instead of hanging
/// (http.lowSpeedLimit / http.lowSpeedTime).
const GIT_LOW_SPEED: [(&str, &str); 2] = [("GIT_HTTP_LOW_SPEED_LIMIT", "1000"), ("GIT_HTTP_LOW_SPEED_TIME", "60")];
/// What `ensure` returns once its `cancelled` check turned true.
pub const CANCELLED: &str = "Fetching the sources was cancelled.";
/// How often a running git or curl, or a wait for another fetch, checks for Cancel.
const POLL: Duration = Duration::from_millis(100);
/// One fetch at a time in this process; `lock_sources` covers other launchers.
static FETCH: Mutex<()> = Mutex::new(());

/// Where the sources for `commit` live below `base`.
pub fn managed_root(base: &Path, commit: &str) -> PathBuf {
    base.join("sources").join(&commit[..commit.len().min(FOLDER_COMMIT_LEN)])
}

/// Folders named after the full commit id, which earlier launchers created.
fn legacy_root(base: &Path, commit: &str) -> PathBuf {
    base.join("sources").join(commit)
}

/// The folder can be written to (an install under Program Files or /usr cannot).
fn writable(dir: &Path) -> bool {
    let probe = dir.join(".sotr-write-test");
    let ok = fs::File::create(&probe).is_ok();
    let _ = fs::remove_file(probe);
    ok
}

/// Sources, the SDK and build output stay next to the launcher, where its game
/// folders are, so the whole install moves and deletes as one folder. A folder
/// that already holds these sources wins (including the per-user one earlier
/// launchers used), and a launcher in a read-only place uses the per-user folder.
pub fn managed_root_for(launcher_dir: &Path, data_dir: Option<&Path>, commit: &str) -> Option<PathBuf> {
    let beside = launcher_dir.join("build");
    let per_user = data_dir.map(|d| d.join("SoulsOfTheReaper"));
    let candidates: Vec<PathBuf> = std::iter::once(beside.clone()).chain(per_user.clone()).collect();
    let existing = candidates
        .iter()
        .flat_map(|b| [managed_root(b, commit), legacy_root(b, commit)])
        .find(|r| is_complete(r));
    existing.or_else(|| {
        let base = if writable(launcher_dir) { beside } else { per_user? };
        Some(managed_root(&base, commit))
    })
}

/// Folder that holds the default game folders of a launcher outside a checkout
/// whose sources live at `managed`: beside the launcher, unless the launcher's
/// folder cannot be written to and the sources went to the per-user folder.
/// Then the game folders go there too, so the build does not fail on its first
/// step. A writable launcher folder keeps them beside it even when it reuses
/// sources an earlier launcher fetched per user, since that is where those
/// launchers put the game.
pub fn game_base(launcher_dir: &Path, managed: &Path) -> PathBuf {
    match managed.ancestors().nth(2) {
        Some(base) if !managed.starts_with(launcher_dir) && !writable(launcher_dir) => base.to_path_buf(),
        _ => launcher_dir.to_path_buf(),
    }
}

/// The folder holds what scripts/build_client.py needs.
pub fn is_complete(root: &Path) -> bool {
    root.join("port/CMakeLists.txt").is_file() && root.join("scripts/build_client.py").is_file()
}

/// "https://github.com/o/r.git" or "git@github.com:o/r" -> "https://github.com/o/r".
pub fn github_url(remote: &str) -> Option<String> {
    let path = remote
        .trim()
        .strip_prefix("https://github.com/")
        .or_else(|| remote.trim().strip_prefix("git@github.com:"))?
        .trim_end_matches('/');
    let path = path.strip_suffix(".git").unwrap_or(path);
    (path.split('/').count() == 2 && !path.contains(char::is_whitespace))
        .then(|| format!("https://github.com/{path}"))
}

fn read_all(mut pipe: impl Read + Send + 'static) -> std::thread::JoinHandle<String> {
    std::thread::spawn(move || {
        let mut data = Vec::new();
        let _ = pipe.read_to_end(&mut data);
        String::from_utf8_lossy(&data).into_owned()
    })
}

/// Runs `program args` in `dir` and returns its stdout; stderr goes to `log`.
/// Once `cancelled` turns true the child and what it started are stopped.
fn run(program: &Path, args: &[&str], dir: &Path, log: &dyn Fn(&str), cancelled: &dyn Fn() -> bool) -> Result<String, String> {
    let mut command = Command::new(program);
    command
        .args(args)
        .current_dir(dir)
        .envs(GIT_NO_PROMPT)
        .envs(GIT_LOW_SPEED)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0); // for tools::kill_tree
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let mut child = command
        .spawn()
        .map_err(|e| format!("Unable to run {}: {e}", program.display()))?;
    let (stdout, stderr) = (read_all(child.stdout.take().unwrap()), read_all(child.stderr.take().unwrap()));
    let status = loop {
        match child.try_wait() {
            Ok(None) if cancelled() => {
                tools::kill_tree(child.id());
                let _ = child.wait();
                break None;
            }
            Ok(None) => std::thread::sleep(POLL),
            Ok(Some(status)) => break Some(status),
            Err(e) => {
                let _ = child.kill();
                return Err(format!("{}: {e}", program.display()));
            }
        }
    };
    let stdout = stdout.join().unwrap_or_default();
    for line in stderr.join().unwrap_or_default().lines() {
        log(line);
    }
    match status {
        None => Err(CANCELLED.into()),
        Some(status) if status.success() => Ok(stdout),
        Some(_) => Err(format!("{} {} failed.", program.display(), args.first().unwrap_or(&""))),
    }
}

fn clone_with_git(
    git: &Path,
    url: &str,
    commit: &str,
    dest: &Path,
    log: &dyn Fn(&str),
    cancelled: &dyn Fn() -> bool,
) -> Result<(), String> {
    let run_git = |args: &[&str]| run(git, args, dest, log, cancelled);
    run_git(&["init", "--quiet"])?;
    // Git for Windows defaults: no paths over 260 characters, and CRLF line endings.
    run_git(&["config", "core.longpaths", "true"])?;
    run_git(&["config", "core.autocrlf", "false"])?;
    run_git(&["remote", "add", "origin", url])?;
    run_git(&["fetch", "--depth", "1", "origin", commit])?;
    run_git(&["checkout", "--quiet", "FETCH_HEAD"])?;
    let head = run_git(&["rev-parse", "HEAD"])?;
    if head.trim() != commit {
        return Err(format!("Fetched revision {} instead of {commit}.", head.trim()));
    }
    Ok(())
}

/// curl and tar from System32 on Windows (both ship with Windows 10 and
/// later): Git's GNU tar, when on PATH, reads `C:\...` as a remote host.
fn system_tool(name: &str) -> PathBuf {
    #[cfg(windows)]
    if let Some(root) = std::env::var_os("SystemRoot") {
        let path = PathBuf::from(root).join("System32").join(format!("{name}.exe"));
        if path.is_file() {
            return path;
        }
    }
    PathBuf::from(name)
}

/// Windows refuses to rename a folder while antivirus or the search indexer
/// still has a just-written file open, so give them a moment.
fn rename_with_retry(from: &Path, to: &Path) -> std::io::Result<()> {
    let mut attempt = 0;
    loop {
        match fs::rename(from, to) {
            Err(e) if attempt < 5 && e.kind() == std::io::ErrorKind::PermissionDenied => {
                attempt += 1;
                std::thread::sleep(std::time::Duration::from_millis(500));
            }
            result => return result,
        }
    }
}

/// Downloads GitHub's archive of `commit` with curl and unpacks it with tar,
/// dropping the top-level folder. A download slower than 1000 bytes/s for a
/// minute gives up, like git's.
fn download_archive(url: &str, commit: &str, dest: &Path, log: &dyn Fn(&str), cancelled: &dyn Fn() -> bool) -> Result<(), String> {
    let archive = dest.join("sources.tar.gz");
    let archive_name = archive.to_string_lossy().into_owned();
    run(
        &system_tool("curl"),
        &[
            "--fail", "--location", "--silent", "--show-error",
            "--connect-timeout", "30", "--speed-limit", "1000", "--speed-time", "60",
            "--output", &archive_name, &format!("{url}/archive/{commit}.tar.gz"),
        ],
        dest,
        log,
        cancelled,
    )?;
    run(&system_tool("tar"), &["-xzf", &archive_name, "--strip-components=1"], dest, log, cancelled)?;
    let _ = fs::remove_file(archive);
    Ok(())
}

/// Holds `<root>.lock` while the sources are fetched, so a second launcher
/// fetching the same commit waits instead of deleting the .partial folder
/// under the first. The system releases the lock with the process, so a
/// crash leaves nothing stale behind.
fn lock_sources(root: &Path, log: &dyn Fn(&str), cancelled: &dyn Fn() -> bool) -> Result<fs::File, String> {
    let path = root.with_extension("lock");
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("Unable to create {}: {e}", parent.display()))?;
    }
    let file = fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(&path)
        .map_err(|e| format!("Unable to create {}: {e}", path.display()))?;
    let mut waiting = false;
    loop {
        match file.try_lock() {
            Ok(()) => return Ok(file),
            Err(fs::TryLockError::WouldBlock) if cancelled() => return Err(CANCELLED.into()),
            Err(fs::TryLockError::WouldBlock) => {
                if !std::mem::replace(&mut waiting, true) {
                    log("Waiting for another launcher to finish fetching the same sources");
                }
                std::thread::sleep(POLL);
            }
            Err(fs::TryLockError::Error(e)) => return Err(format!("Unable to lock {}: {e}", path.display())),
        }
    }
}

/// Makes sure the sources for `commit` are on disk and returns their folder.
/// `git` is the git executable, if one was found. Progress goes to `log`;
/// once `cancelled` returns true the fetch stops with [`CANCELLED`]. Fetches
/// run one at a time, and one that waited reuses what the other fetched.
pub fn ensure(
    root: &Path,
    remote: &str,
    commit: &str,
    git: Option<&Path>,
    log: &dyn Fn(&str),
    cancelled: &dyn Fn() -> bool,
) -> Result<PathBuf, String> {
    if is_complete(root) {
        return Ok(root.to_path_buf());
    }
    let url = github_url(remote).ok_or_else(|| format!("Cannot fetch sources from {remote:?}: not a GitHub repository."))?;
    let _one_at_a_time = FETCH.lock().unwrap_or_else(PoisonError::into_inner);
    let _lock = lock_sources(root, log, cancelled)?;
    if is_complete(root) {
        return Ok(root.to_path_buf());
    }
    let partial = root.with_extension("partial");
    let _ = fs::remove_dir_all(&partial);
    fs::create_dir_all(&partial).map_err(|e| format!("Unable to create {}: {e}", partial.display()))?;
    let fetched = match git {
        Some(git) => {
            log(&format!("Cloning {url} at {commit}"));
            clone_with_git(git, &url, commit, &partial, log, cancelled)
        }
        None => {
            log(&format!("git was not found; downloading the source archive for {commit}"));
            download_archive(&url, commit, &partial, log, cancelled)
        }
    };
    fetched
        .and_then(|()| {
            is_complete(&partial)
                .then_some(())
                .ok_or_else(|| "The fetched sources are missing the build scripts.".to_string())
        })
        .and_then(|()| {
            let _ = fs::remove_dir_all(root);
            rename_with_retry(&partial, root).map_err(|e| format!("Unable to move sources into place: {e}"))
        })
        .inspect_err(|_| {
            let _ = fs::remove_dir_all(&partial);
        })?;
    Ok(root.to_path_buf())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn github_remotes_are_normalised() {
        let want = Some("https://github.com/CrippledTrack/Souls-of-the-Reaper".to_string());
        assert_eq!(github_url("https://github.com/CrippledTrack/Souls-of-the-Reaper.git"), want);
        assert_eq!(github_url("git@github.com:CrippledTrack/Souls-of-the-Reaper.git\n"), want);
        assert_eq!(github_url("https://github.com/CrippledTrack/Souls-of-the-Reaper/"), want);
        assert_eq!(github_url("https://example.test/a/b.git"), None);
        assert_eq!(github_url("https://github.com/only-owner"), None);
    }

    #[test]
    fn sources_are_keyed_by_commit() {
        let root = managed_root(Path::new("/data"), "abc");
        assert!(root.ends_with("sources/abc"));
        let id = "c94f5ebdcb3c9d1a460ca48e04f9758448f8d518";
        assert!(managed_root(Path::new("/data"), id).ends_with("sources/c94f5ebdcb3c"));
    }

    #[test]
    fn sources_fetched_under_the_full_commit_are_still_used() {
        let (launcher, data) = (scratch("launcher4"), scratch("data4"));
        let id = "c94f5ebdcb3c9d1a460ca48e04f9758448f8d518";
        let old = launcher.join("build/sources").join(id);
        make_complete(&old);
        assert_eq!(managed_root_for(&launcher, Some(&data), id).unwrap(), old);
    }

    fn scratch(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("sotr-root-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn make_complete(root: &Path) {
        fs::create_dir_all(root.join("port")).unwrap();
        fs::create_dir_all(root.join("scripts")).unwrap();
        fs::write(root.join("port/CMakeLists.txt"), "").unwrap();
        fs::write(root.join("scripts/build_client.py"), "").unwrap();
    }

    #[test]
    fn sources_default_to_beside_the_launcher() {
        let (launcher, data) = (scratch("launcher"), scratch("data"));
        let root = managed_root_for(&launcher, Some(&data), "abc").unwrap();
        assert_eq!(root, launcher.join("build/sources/abc"));
        assert!(!launcher.join(".sotr-write-test").exists());
    }

    #[test]
    fn fetched_sources_in_the_per_user_folder_are_still_used() {
        let (launcher, data) = (scratch("launcher2"), scratch("data2"));
        let old = managed_root(&data.join("SoulsOfTheReaper"), "abc");
        make_complete(&old);
        assert_eq!(managed_root_for(&launcher, Some(&data), "abc").unwrap(), old);
        make_complete(&managed_root(&launcher.join("build"), "abc"));
        assert_eq!(managed_root_for(&launcher, Some(&data), "abc").unwrap(), launcher.join("build/sources/abc"));
    }

    #[test]
    fn an_unwritable_launcher_folder_falls_back_to_the_per_user_one() {
        let data = scratch("data3");
        let root = managed_root_for(Path::new("/nonexistent-sotr-launcher-dir"), Some(&data), "abc").unwrap();
        assert_eq!(root, data.join("SoulsOfTheReaper/sources/abc"));
        assert_eq!(managed_root_for(Path::new("/nonexistent-sotr-launcher-dir"), None, "abc"), None);
    }

    #[test]
    fn game_folders_follow_sources_that_left_an_unwritable_launcher_folder() {
        let (launcher, data) = (scratch("launcher5"), scratch("data5"));
        let unwritable = Path::new("/nonexistent-sotr-launcher-dir");
        let per_user = managed_root_for(unwritable, Some(&data), "abc").unwrap();
        assert_eq!(game_base(unwritable, &per_user), data.join("SoulsOfTheReaper"));
        // Beside a writable launcher, and with per-user sources an earlier launcher
        // fetched (it put the game beside itself), the game stays beside the launcher.
        assert_eq!(game_base(&launcher, &managed_root_for(&launcher, Some(&data), "abc").unwrap()), launcher);
        assert_eq!(game_base(&launcher, &per_user), launcher);
    }

    fn command_line(windows: &[&'static str], unix: &[&'static str]) -> (PathBuf, Vec<&'static str>) {
        let words = if cfg!(windows) { windows } else { unix };
        (PathBuf::from(words[0]), words[1..].to_vec())
    }

    #[test]
    fn children_return_their_output_and_stop_when_cancelled() {
        let dir = scratch("run");
        let (echo, args) = command_line(&["cmd", "/C", "echo hi"], &["sh", "-c", "echo hi"]);
        assert_eq!(run(&echo, &args, &dir, &|_| {}, &|| false).unwrap().trim(), "hi");
        // A long child is stopped at the first poll after Cancel, not when it ends.
        let (slow, args) = command_line(&["ping", "-n", "60", "127.0.0.1"], &["sleep", "60"]);
        let polls = std::cell::Cell::new(0);
        let start = std::time::Instant::now();
        let result = run(&slow, &args, &dir, &|_| {}, &|| {
            polls.set(polls.get() + 1);
            polls.get() > 3
        });
        assert_eq!(result, Err(CANCELLED.to_string()));
        assert!(start.elapsed() < Duration::from_secs(20), "took {:?}", start.elapsed());
    }

    #[test]
    fn a_second_fetch_of_the_same_sources_waits_for_the_first() {
        let root = managed_root(&scratch("lock"), "abc");
        let first = lock_sources(&root, &|_| {}, &|| false).unwrap();
        let lines = std::cell::RefCell::new(Vec::new());
        let waited = lock_sources(&root, &|l| lines.borrow_mut().push(l.to_string()), &|| !lines.borrow().is_empty());
        assert_eq!(waited.err().as_deref(), Some(CANCELLED));
        assert!(lines.borrow()[0].contains("another launcher"));
        drop(first);
        assert!(lock_sources(&root, &|_| {}, &|| true).is_ok());
    }

    #[test]
    fn complete_needs_the_build_scripts() {
        let dir = std::env::temp_dir().join(format!("sotr-sources-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(dir.join("port")).unwrap();
        fs::create_dir_all(dir.join("scripts")).unwrap();
        assert!(!is_complete(&dir));
        fs::write(dir.join("port/CMakeLists.txt"), "").unwrap();
        assert!(!is_complete(&dir));
        fs::write(dir.join("scripts/build_client.py"), "").unwrap();
        assert!(is_complete(&dir));
        let _ = fs::remove_dir_all(&dir);
    }

    /// Fetches a real pushed commit (SOTR_TEST_COMMIT, from SOTR_TEST_REMOTE).
    /// Run with `cargo test -- --ignored`; needs network access and git, curl
    /// and tar on PATH.
    #[test]
    #[ignore]
    fn fetches_a_pushed_commit_with_git_and_without() {
        let commit = std::env::var("SOTR_TEST_COMMIT").expect("set SOTR_TEST_COMMIT to a pushed commit");
        let remote = std::env::var("SOTR_TEST_REMOTE")
            .unwrap_or_else(|_| "https://github.com/CrippledTrack/Souls-of-the-Reaper.git".into());
        let base = std::env::temp_dir().join(format!("sotr-fetch-{}", std::process::id()));
        let _ = fs::remove_dir_all(&base);
        let lines = std::cell::RefCell::new(Vec::new());
        let log = |l: &str| lines.borrow_mut().push(l.to_string());
        for (name, git) in [("git", Some(Path::new("git"))), ("archive", None)] {
            let root = managed_root(&base.join(name), &commit);
            let got = ensure(&root, &remote, &commit, git, &log, &|| false)
                .unwrap_or_else(|e| panic!("{name}: {e}\n{:?}", lines.borrow()));
            assert!(is_complete(&got), "{name}");
            // A second call reuses the folder.
            let before = lines.borrow().len();
            ensure(&root, &remote, &commit, git, &log, &|| false).unwrap();
            assert_eq!(lines.borrow().len(), before, "{name} refetched");
            assert!(!root.with_extension("partial").exists());
        }
        assert!(managed_root(&base.join("git"), &commit).join(".git").exists());
        let _ = fs::remove_dir_all(&base);
    }
}
