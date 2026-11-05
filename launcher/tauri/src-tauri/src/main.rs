#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod build_info;
mod launch;
mod sources;
mod tools;

use launch::{Build, BuildRequest, Defaults, GameOptions, Platform, Settings};
use serde::Serialize;
use std::{
    collections::VecDeque,
    fs,
    io::{BufRead, BufReader, Read},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex, MutexGuard, PoisonError,
    },
    time::{Duration, Instant},
};
use tauri::{Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_dialog::DialogExt;

/// Folder defaults resolved at startup; builds are found again after the
/// Build panel finishes.
struct Host {
    platform: Platform,
    builds: Mutex<Vec<Build>>,
    defaults: Defaults,
    settings_file: PathBuf,
    launcher_dir: PathBuf,
    search: Vec<PathBuf>,
    /// Source checkout, needed to build the game.
    repo: Option<PathBuf>,
    /// Where a launcher outside a checkout fetches the sources for its own
    /// commit; None when that commit cannot be fetched.
    managed: Option<PathBuf>,
    /// The build or tool install that is running, if any.
    job: JobSlot,
}

impl Host {
    /// Folder the build scripts run from: the checkout, else the fetched sources.
    fn build_root(&self) -> Option<PathBuf> {
        self.repo.clone().or_else(|| self.managed.clone())
    }
}

const CANCELLED: &str = "Build cancelled. Run it again to continue where it stopped.";

/// What the Build panel runs. There is one at a time: start_build and
/// install_tools claim the slot before their first check, so a second click
/// is turned away before it fetches or starts anything.
#[derive(Debug, Default)]
enum Job {
    #[default]
    Idle,
    /// A build: checking tools and fetching sources until `pid` is set, then
    /// scripts/build_client.py. Cancel sets `cancel`, which also stops a fetch
    /// and keeps the script from starting.
    Build { cancel: Arc<AtomicBool>, pid: Option<u32> },
    /// winget and the installers it starts, which are not stopped halfway.
    Install,
}

#[derive(Debug, Default)]
struct JobSlot(Mutex<Job>);

/// A claimed slot. Dropping it frees the slot, so every exit path of the
/// command that holds it (errors and `?` included) does.
struct Claim<'a> {
    slot: &'a JobSlot,
    cancel: Arc<AtomicBool>,
}

impl JobSlot {
    fn lock(&self) -> MutexGuard<'_, Job> {
        self.0.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// Takes the slot for a build, or for a tool install when `build` is false.
    fn claim(&self, build: bool) -> Result<Claim<'_>, String> {
        let mut job = self.lock();
        match *job {
            Job::Idle => {}
            Job::Build { .. } => return Err("A build is already running.".into()),
            Job::Install => return Err("The build tools are being installed.".into()),
        }
        let cancel = Arc::new(AtomicBool::new(false));
        *job = if build {
            Job::Build { cancel: cancel.clone(), pid: None }
        } else {
            Job::Install
        };
        Ok(Claim { slot: self, cancel })
    }

    /// Cancels a build and hands over its script's process id once it runs,
    /// for the caller to stop (only once, so a second Cancel cannot hit a
    /// reused id). Tool installs are left to finish.
    fn cancel(&self) -> Option<u32> {
        match &mut *self.lock() {
            Job::Build { cancel, pid } => {
                cancel.store(true, Ordering::SeqCst);
                pid.take()
            }
            _ => None,
        }
    }
}

impl Claim<'_> {
    fn cancelled(&self) -> bool {
        self.cancel.load(Ordering::SeqCst)
    }

    /// Records the started build script for Cancel. False when Cancel came
    /// first; the caller then stops the script itself.
    fn started(&self, id: u32) -> bool {
        let mut job = self.slot.lock();
        if self.cancelled() {
            return false;
        }
        if let Job::Build { pid, .. } = &mut *job {
            *pid = Some(id);
        }
        true
    }
}

impl Drop for Claim<'_> {
    fn drop(&mut self) {
        *self.slot.lock() = Job::Idle;
    }
}

/// Injected ahead of the page scripts as window.LAUNCHER_CAPS.
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Caps<'a> {
    platform: &'static str,
    /// Renderers the page may offer: both on Windows (one executable holds
    /// them), Vulkan only on Linux.
    backends: &'static [&'static str],
    builds: &'a [Build],
    defaults: &'a Defaults,
    can_build: bool,
    /// The title update is in the game folder (drives the update autoselect and the
    /// Build panel's default variant).
    update_installed: bool,
    /// Source revision the launcher was built from.
    version: build_info::BuildInfo,
}

fn load_settings(path: &Path) -> Settings {
    fs::read(path)
        .map(|data| launch::parse_settings(&data))
        .unwrap_or_default()
}

fn write_settings(path: &Path, settings: &Settings) -> Result<(), String> {
    fs::create_dir_all(path.parent().unwrap()).map_err(|e| e.to_string())?;
    let data = serde_json::to_vec_pretty(settings).map_err(|e| e.to_string())?;
    fs::write(path, data).map_err(|e| e.to_string())
}

#[tauri::command]
fn save_settings(host: tauri::State<Host>, settings: Settings) -> Result<(), String> {
    write_settings(&host.settings_file, &settings)
}

/// Grants the game the foreground; Windows otherwise opens it behind the
/// closing launcher (see Launcher.ps1's AllowSetForegroundWindow note).
#[cfg(target_os = "windows")]
fn allow_foreground(pid: u32) {
    #[link(name = "user32")]
    extern "system" {
        fn AllowSetForegroundWindow(process_id: u32) -> i32;
    }
    unsafe {
        AllowSetForegroundWindow(pid);
    }
}

#[cfg(not(target_os = "windows"))]
fn allow_foreground(_pid: u32) {}

/// Validates the selected build and folders, saves the launcher choices and
/// starts the game. Returns once the game has survived startup briefly, so an
/// immediate failure is reported here instead of disappearing with the window.
#[tauri::command]
async fn launch_game(
    window: tauri::WebviewWindow,
    host: tauri::State<'_, Host>,
    settings: Settings,
    mut options: GameOptions,
) -> Result<(), String> {
    // A launch setting (Launch settings panel), not a menu choice.
    options.video_driver = settings.video_driver.trim().to_string();
    let build = {
        let builds = host.builds.lock().unwrap();
        match &options.build {
            Some(id) => builds.iter().find(|b| &b.id == id),
            None => builds.first(),
        }
        .ok_or("No game build found. Build the game or place the launcher next to diablo3.")?
        .clone()
    };
    let (game, user) = launch::folders_for(&build, &settings, &host.defaults);
    let game =
        fs::canonicalize(&game).map_err(|e| format!("Game folder {}: {e}", game.display()))?;
    let game = launch::plain_path(game);
    launch::validate_game_dir(&build, &game)?;
    fs::create_dir_all(&user).map_err(|e| format!("Save folder {}: {e}", user.display()))?;
    let user = launch::plain_path(fs::canonicalize(&user).map_err(|e| e.to_string())?);
    let args = launch::launch_arguments(
        host.platform,
        &build,
        &game,
        &user,
        &options,
        settings.vulkan_device,
    )?;
    write_settings(&host.settings_file, &settings)?;

    let stdio_log = user.join("launcher-stdio.log");
    let output = fs::File::create(&stdio_log).map_err(|e| e.to_string())?;
    let mut child = Command::new(&build.executable)
        .args(&args)
        .env("SOTR_USERNAME", settings.username.trim())
        .current_dir(build.executable.parent().unwrap())
        .stdout(Stdio::from(output.try_clone().map_err(|e| e.to_string())?))
        .stderr(Stdio::from(output))
        .spawn()
        .map_err(|e| format!("Unable to start {}: {e}", build.executable.display()))?;
    allow_foreground(child.id());
    let exited = tauri::async_runtime::spawn_blocking(move || {
        let deadline = Instant::now() + Duration::from_millis(1500);
        while Instant::now() < deadline {
            match child.try_wait() {
                Ok(Some(status)) => return Some(status),
                Ok(None) => std::thread::sleep(Duration::from_millis(100)),
                Err(_) => break,
            }
        }
        None
    })
    .await
    .map_err(|e| e.to_string())?;
    if let Some(status) = exited.filter(|s| !s.success()) {
        return Err(format!(
            "The game exited during startup ({status}). See {}.",
            stdio_log.display()
        ));
    }
    window.close().map_err(|e| e.to_string())
}

/// Cancels the build: a source fetch stops and the script is not started, or
/// the running script stops with the CMake/Ninja/compiler processes it started.
fn stop_build(host: &Host) {
    if let Some(pid) = host.job.cancel() {
        // The script leads its own process group on Unix (see start_build).
        tools::kill_tree(pid);
    }
}

/// Sends each output line to the page as a build-output event and keeps the
/// last lines for the error message. `clean` rewrites a line or drops it.
fn forward_output(
    app: tauri::AppHandle,
    stream: impl Read + Send + 'static,
    tail: Arc<Mutex<VecDeque<String>>>,
    clean: fn(&str) -> Option<String>,
) -> std::thread::JoinHandle<()> {
    std::thread::spawn(move || {
        let mut reader = BufReader::new(stream);
        let mut buffer = Vec::new();
        while reader.read_until(b'\n', &mut buffer).is_ok_and(|n| n > 0) {
            let line = clean(String::from_utf8_lossy(&buffer).trim_end());
            buffer.clear();
            let Some(line) = line else { continue };
            let _ = app.emit("build-output", &line);
            let mut tail = tail.lock().unwrap();
            if tail.len() == 20 {
                tail.pop_front();
            }
            tail.push_back(line);
        }
    })
}

/// Runs scripts/build_client.py into the launcher's game folders, streaming
/// its output, and returns the builds found afterwards.
#[tauri::command]
async fn start_build(
    app: tauri::AppHandle,
    host: tauri::State<'_, Host>,
    settings: Settings,
    request: BuildRequest,
) -> Result<Vec<Build>, String> {
    // Held until this returns. A second build is turned away here, before the
    // tool check and the source fetch, not when the script would start.
    let claim = host.inner().job.claim(true)?;
    let repo = host
        .build_root()
        .ok_or("This launcher cannot fetch its sources. Build from a Souls of the Reaper source checkout.")?;
    let (game, game_update) = launch::game_folders(&settings, &host.defaults);
    let args = launch::build_client_arguments(host.platform, &repo, &request, &game, &game_update)?;
    // Checked before downloading anything, so a missing tool costs no download.
    let report = tools::detect(host.platform, &repo, &request.cmake);
    if !report.ready {
        let missing: Vec<_> = report.tools.iter().filter(|t| !t.found).map(|t| t.label.as_str()).collect();
        return Err(format!("Missing build tools: {}.", missing.join(", ")));
    }
    let tool_path = |id: &str| report.tools.iter().find(|t| t.id == id).map(|t| PathBuf::from(&t.path));
    let fetch = host.repo.is_none() && !sources::is_complete(&repo);
    if fetch {
        if !request.download_sources {
            return Err("The game sources are not downloaded yet. Approve the download to continue.".into());
        }
        let git = tool_path("git");
        let (root, app, cancel) = (repo.clone(), app.clone(), claim.cancel.clone());
        let fetched = tauri::async_runtime::spawn_blocking(move || {
            sources::ensure(
                &root,
                build_info::BuildInfo::repository(),
                &build_info::BuildInfo::current().commit,
                git.as_deref(),
                &|line| {
                    let _ = app.emit("build-output", line);
                },
                &|| cancel.load(Ordering::SeqCst),
            )
        })
        .await
        .map_err(|e| e.to_string())?;
        if claim.cancelled() {
            return Err(CANCELLED.into());
        }
        fetched?;
    }
    // The SDK state comes from the sources' build script, which only now exists.
    let python = tool_path("python").unwrap_or_default();
    let report = if fetch { tools::detect(host.platform, &repo, &request.cmake) } else { report };
    if !report.sdk.installed && !request.download_sdk {
        return Err("The ReXGlue SDK needs to be built. Approve the download to continue.".into());
    }
    if claim.cancelled() {
        return Err(CANCELLED.into());
    }
    write_settings(&host.settings_file, &settings)?;

    // The interpreter the tool check accepted, not whatever "python" resolves to.
    let mut command = Command::new(&python);
    command
        .args(&args)
        .current_dir(&repo)
        .env("PYTHONUNBUFFERED", "1")
        .envs(tools::PYTHON_UTF8)
        // The SDK checkout and the update patch tool are fetched with git too.
        .envs(sources::GIT_NO_PROMPT)
        .envs(tools::path_with(&report.path_dirs).map(|p| ("PATH", p)))
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let mut child = command
        .spawn()
        .map_err(|e| format!("Unable to start Python 3: {e}. Install Python 3 to build the game."))?;
    if !claim.started(child.id()) {
        tools::kill_tree(child.id());
        let _ = child.wait();
        return Err(CANCELLED.into());
    }
    let tail = Arc::new(Mutex::new(VecDeque::new()));
    let keep = |line: &str| Some(line.to_string());
    let readers = [
        forward_output(app.clone(), child.stdout.take().unwrap(), tail.clone(), keep),
        forward_output(app.clone(), child.stderr.take().unwrap(), tail.clone(), keep),
    ];
    let status = tauri::async_runtime::spawn_blocking(move || {
        let status = child.wait();
        for reader in readers {
            let _ = reader.join();
        }
        status
    })
    .await
    .map_err(|e| e.to_string())?
    .map_err(|e| e.to_string());
    if claim.cancelled() {
        return Err(CANCELLED.into());
    }
    if !status?.success() {
        let tail = tail.lock().unwrap();
        let reason = tail
            .iter()
            .rev()
            .find(|l| l.starts_with("Build failed:"))
            .or(tail.back())
            .cloned()
            .unwrap_or_else(|| "Build failed.".into());
        return Err(reason);
    }
    let builds = launch::discover_builds(host.platform, &host.launcher_dir, &host.search);
    *host.builds.lock().unwrap() = builds.clone();
    Ok(builds)
}

/// Build tools and SDK state for the Build panel; `cmake` is its CMake field.
#[tauri::command]
async fn check_build_tools(
    host: tauri::State<'_, Host>,
    cmake: String,
) -> Result<tools::ToolReport, String> {
    let repo = host
        .build_root()
        .ok_or("This launcher cannot fetch its sources. Build from a Souls of the Reaper source checkout.")?;
    let platform = host.platform;
    let missing = host.repo.is_none() && !sources::is_complete(&repo);
    tauri::async_runtime::spawn_blocking(move || {
        let mut report = tools::detect(platform, &repo, &cmake);
        if missing {
            report.sources = Some(tools::Sources {
                repository: build_info::BuildInfo::repository().into(),
                commit: build_info::BuildInfo::current().commit,
            });
        }
        report
    })
        .await
        .map_err(|e| e.to_string())
}

/// Installs the missing build tools with winget, one after another, streaming
/// its output like a build, and returns the tool report afterwards. The page
/// only calls this after the user pressed the install button, whose text says
/// that it accepts the packages' license agreements.
#[tauri::command]
async fn install_tools(
    app: tauri::AppHandle,
    host: tauri::State<'_, Host>,
    cmake: String,
) -> Result<tools::ToolReport, String> {
    if host.platform != Platform::Windows {
        return Err("Installing tools is only offered on Windows.".into());
    }
    let repo = host
        .build_root()
        .ok_or("This launcher cannot fetch its sources. Build from a Souls of the Reaper source checkout.")?;
    // Held through the tool check at the end, so two installs never overlap
    // (the second would fail with MSI error 1618) and no build starts meanwhile.
    let _claim = host.inner().job.claim(false)?;
    let platform = host.platform;
    let (dir, app_handle, cmake_choice) = (repo.clone(), app.clone(), cmake.clone());
    let failed = tauri::async_runtime::spawn_blocking(move || {
        let report = tools::detect(platform, &dir, &cmake);
        let missing = tools::install_order(&report);
        let mut failed = Vec::new();
        for (index, tool) in missing.iter().enumerate() {
            let _ = app_handle.emit(
                "build-output",
                format!("::step::{}/{}::Installing {}", index + 1, missing.len(), tool.label),
            );
            let mut command = Command::new("winget");
            command
                .args(tools::winget_arguments(tool.winget))
                .stdin(Stdio::null())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped());
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
            }
            let status = command.spawn().and_then(|mut child| {
                let tail = Arc::new(Mutex::new(VecDeque::new()));
                let readers = [
                    forward_output(app_handle.clone(), child.stdout.take().unwrap(), tail.clone(), tools::clean_winget_line),
                    forward_output(app_handle.clone(), child.stderr.take().unwrap(), tail, tools::clean_winget_line),
                ];
                let status = child.wait();
                for reader in readers {
                    let _ = reader.join();
                }
                status
            });
            // winget reports "already installed" and "restart needed" as failures too;
            // the tool check below decides what is really missing.
            if !status.is_ok_and(|s| s.success()) {
                failed.push(tool.label.clone());
            }
        }
        failed
    })
    .await
    .map_err(|e| e.to_string())?;
    if !failed.is_empty() {
        let _ = app.emit("build-output", format!("winget did not finish cleanly for: {}.", failed.join(", ")));
    }
    check_build_tools(host, cmake_choice).await
}

#[tauri::command]
fn cancel_build(host: tauri::State<Host>) {
    stop_build(&host);
}

/// Native file picker for the Build panel; None when dismissed.
#[tauri::command]
async fn pick_file(app: tauri::AppHandle, kind: String) -> Result<Option<String>, String> {
    let dialog = app.dialog().file();
    let dialog = match kind.as_str() {
        "iso" => dialog
            .set_title("Select the Diablo III disc image")
            .add_filter("Xbox 360 disc image", &["iso", "xiso"]),
        "titleUpdate" => dialog.set_title("Select the Title Update package"),
        "cmake" => dialog.set_title("Select the CMake executable"),
        _ => return Err("Unknown file type.".into()),
    };
    let picked = tauri::async_runtime::spawn_blocking(move || dialog.blocking_pick_file())
        .await
        .map_err(|e| e.to_string())?;
    Ok(picked
        .and_then(|p| p.into_path().ok())
        .map(|p| p.display().to_string()))
}

/// Opens a page link in the default browser. WebView2 (Launcher.ps1) handled
/// target="_blank" itself; a Tauri webview ignores it, so the page asks here.
#[tauri::command]
fn open_external(url: String) -> Result<(), String> {
    if !launch::is_external_url(&url) {
        return Err("Only https links can be opened.".into());
    }
    let mut command = if cfg!(target_os = "windows") {
        // No cmd.exe: its own parsing would treat & in a URL as a command separator.
        let mut c = Command::new("rundll32");
        c.arg("url.dll,FileProtocolHandler");
        c
    } else if cfg!(target_os = "macos") {
        Command::new("open")
    } else {
        Command::new("xdg-open")
    };
    command
        .arg(&url)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map(|_| ())
        .map_err(|e| format!("Unable to open the link: {e}"))
}

#[tauri::command]
fn window_action(window: tauri::WebviewWindow, action: String) -> Result<(), String> {
    match action.as_str() {
        "close" => window.close(),
        "minimize" => window.minimize(),
        "dragStart" => window.start_dragging(),
        _ => return Err("Unknown window action.".into()),
    }
    .map_err(|e| e.to_string())
}

fn setup(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let platform = Platform::current();
    let launcher_dir = std::env::current_exe()?
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_default();
    let mut search = vec![launcher_dir.clone()];
    search.extend(std::env::current_dir().ok());
    let repo = launch::repository_root(&search);
    let info = build_info::BuildInfo::current();
    let managed = (repo.is_none() && info.fetchable())
        // Local, not roaming, app data on Windows: a build takes about 15 GB.
        .then(|| sources::managed_root_for(&launcher_dir, app.path().local_data_dir().ok().as_deref(), &info.commit))
        .flatten();
    // Builds made from fetched sources land inside them.
    search.extend(managed.clone());
    let builds = launch::discover_builds(platform, &launcher_dir, &search);
    // Source checkouts keep game folders at the repository root; installs
    // keep them beside the launcher, or with the fetched sources when those
    // went to the per-user folder because the launcher's is read-only.
    let base = repo
        .clone()
        .filter(|_| !builds.iter().any(|b| b.game_dir.is_some()))
        .or_else(|| managed.as_deref().map(|m| sources::game_base(&launcher_dir, m)))
        .unwrap_or_else(|| launcher_dir.clone());
    let user_base = match platform {
        Platform::Windows => app.path().document_dir()?,
        Platform::Linux => app.path().data_dir()?,
    };
    let defaults = launch::default_folders(platform, &base, &user_base);
    let settings_file = app.path().app_config_dir()?.join("launcher.json");
    let mut settings = load_settings(&settings_file);
    if settings.ui_state.is_null() {
        // Extras builds start on their in-game resolution and window mode.
        settings.ui_state = serde_json::json!({ "res": -1, "display": -1 });
    }

    // The title update is an overlay in the base game folder: once its files are there, open on it.
    let update = launch::update_installed(&builds, &settings, &defaults);
    launch::apply_default_build(&mut settings.ui_state, &builds, update);

    let caps = Caps {
        platform: platform.name(),
        backends: match platform {
            Platform::Windows => &["d3d12", "vulkan"],
            Platform::Linux => &["vulkan"],
        },
        builds: &builds,
        defaults: &defaults,
        can_build: repo.as_ref().is_some_and(|r| r.join("scripts/build_client.py").is_file())
            || (repo.is_none() && managed.is_some()),
        update_installed: update,
        version: build_info::BuildInfo::current(),
    };
    // The page shows its Player Name row from the name reported here.
    let mut saved_state = settings.ui_state.clone();
    if let Some(state) = saved_state.as_object_mut() {
        state.insert("username".into(), settings.username.clone().into());
    }
    let init = format!(
        "window.LAUNCHER_CAPS={};window.LAUNCHER_SETTINGS={};window.SAVED_STATE={};",
        serde_json::to_string(&caps)?,
        serde_json::to_string(&settings)?,
        serde_json::to_string(&saved_state)?,
    );
    app.manage(Host {
        platform,
        builds: Mutex::new(builds),
        defaults,
        settings_file,
        launcher_dir,
        search,
        repo,
        managed,
        job: JobSlot::default(),
    });
    // Sized to the v6 design's 500px stage (aspect 1088/1445), like Launcher.ps1.
    WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
        .title("Souls of the Reaper")
        .inner_size(500.0, 664.0)
        .resizable(false)
        .decorations(false)
        .center()
        .initialization_script(&init)
        .build()?;
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(setup)
        .invoke_handler(tauri::generate_handler![
            save_settings,
            launch_game,
            start_build,
            cancel_build,
            check_build_tools,
            install_tools,
            pick_file,
            open_external,
            window_action
        ])
        .build(tauri::generate_context!())
        .expect("Unable to run launcher")
        .run(|app, event| {
            // Closing the launcher also stops a running build.
            if let (RunEvent::Exit, Some(host)) = (event, app.try_state::<Host>()) {
                stop_build(&host);
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn one_job_runs_at_a_time_until_its_claim_drops() {
        let slot = JobSlot::default();
        let build = slot.claim(true).unwrap();
        assert_eq!(slot.claim(true).err().as_deref(), Some("A build is already running."));
        assert!(slot.claim(false).is_err(), "no install during a build");
        drop(build);
        let install = slot.claim(false).unwrap();
        assert_eq!(slot.claim(false).err().as_deref(), Some("The build tools are being installed."));
        assert!(slot.claim(true).is_err(), "no build during an install");
        drop(install);
        assert!(slot.claim(true).is_ok());
    }

    #[test]
    fn simultaneous_build_clicks_admit_one() {
        let slot = JobSlot::default();
        let start = std::sync::Barrier::new(8);
        let admitted = std::thread::scope(|s| {
            let tries: Vec<_> = (0..8)
                .map(|_| {
                    s.spawn(|| {
                        start.wait();
                        // Kept, not dropped, so the slot stays taken for the others.
                        slot.claim(true).map(std::mem::forget).is_ok()
                    })
                })
                .collect();
            tries.into_iter().map(|t| t.join().unwrap()).filter(|&ok| ok).count()
        });
        assert_eq!(admitted, 1);
    }

    #[test]
    fn cancel_while_preparing_keeps_the_script_from_starting() {
        let slot = JobSlot::default();
        let claim = slot.claim(true).unwrap();
        assert!(!claim.cancelled());
        assert_eq!(slot.cancel(), None, "no process to stop yet");
        assert!(claim.cancelled(), "the fetch sees the flag");
        assert!(!claim.started(42), "a script started after Cancel is refused");
        assert_eq!(slot.cancel(), None, "and not recorded");
    }

    #[test]
    fn cancel_stops_a_running_script() {
        let slot = JobSlot::default();
        let claim = slot.claim(true).unwrap();
        assert!(claim.started(42));
        assert_eq!(slot.cancel(), Some(42));
        assert!(claim.cancelled());
        assert_eq!(slot.cancel(), None, "a second Cancel stops nothing again");
        drop(claim);
        assert!(slot.claim(true).is_ok(), "the slot is free once the build returns");
    }

    #[test]
    fn tool_installs_are_not_cancelled() {
        let slot = JobSlot::default();
        let install = slot.claim(false).unwrap();
        assert_eq!(slot.cancel(), None);
        assert!(!install.cancelled());
    }
}
