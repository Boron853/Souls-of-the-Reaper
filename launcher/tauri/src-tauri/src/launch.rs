//! Build discovery, game-folder validation and game arguments. Kept free of
//! Tauri so both platforms' launch rules are unit-tested on any host. The
//! rules mirror scripts/run_linux.py and scripts/run_windows.ps1.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::{Path, PathBuf},
};

/// Verified guest executables (scripts/title_updates.py).
pub const BASE_HASH: &str = "cc918a70940517f974d0fd60d4936c8236e8dc21130cf4a8b8ae915451c289ef";
pub const USA_UPDATE_HASH: &str = "447652ffa8abe4c7b8bed590a3887efc23e1181fd836b7a3192b8a2a37ddf80f";
/// Update assets a staged update folder must hold (scripts/stage_title_update.py).
pub const UPDATE_CPKS: [&str; 4] = [
    "Patch.cpk",
    "Patch2.cpk",
    "enUS_Patch.cpk",
    "enUS_Patch2.cpk",
];
/// Only executables compiled with the optional PC features register this cvar.
const EXTRAS_MARKER: &[u8] = b"pc_use_saved_render_scale";

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Platform {
    Windows,
    Linux,
}

impl Platform {
    pub fn current() -> Self {
        if cfg!(target_os = "windows") {
            Platform::Windows
        } else {
            Platform::Linux
        }
    }
    pub fn name(self) -> &'static str {
        match self {
            Platform::Windows => "windows",
            Platform::Linux => "linux",
        }
    }
    fn build_prefix(self) -> &'static str {
        match self {
            Platform::Windows => "win-amd64",
            Platform::Linux => "linux-amd64",
        }
    }
    fn executable(self) -> &'static str {
        match self {
            Platform::Windows => "diablo3.exe",
            Platform::Linux => "diablo3",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Build {
    pub id: String,
    pub label: String,
    pub update: bool,
    /// Launch with `--extra_features`. An executable that carries the features
    /// is offered twice, with and without this, so the plain game stays one click away.
    pub extras: bool,
    pub executable: PathBuf,
    /// Release installs pair the executable with the game folder beside it.
    pub game_dir: Option<PathBuf>,
}

fn variant(update: bool, extras: bool) -> (&'static str, &'static str) {
    match (update, extras) {
        (false, false) => ("base", "Base"),
        (false, true) => ("extras", "Base + Extras"),
        (true, false) => ("update", "Update"),
        (true, true) => ("update-extras", "Update + Extras"),
    }
}

fn make_build(update: bool, extras: bool, executable: PathBuf, game_dir: Option<PathBuf>) -> Build {
    let (id, label) = variant(update, extras);
    Build {
        id: id.into(),
        label: label.into(),
        update,
        extras,
        executable,
        game_dir,
    }
}

/// Folder names the overlay is staged under, newest first.
const OVERLAY_NAMES: [&str; 2] = ["update", "tu2"];

/// Where an update game folder keeps its files: `(update root, executable)`. The overlay
/// layout puts the patched executable and update CPKs in `<game>/update` beside the
/// unmodified disc; otherwise the folder is a complete staged copy.
pub fn update_layout(game: &Path) -> (PathBuf, PathBuf) {
    // The overlay was staged as `tu2` before it was renamed; that folder still works.
    for name in OVERLAY_NAMES {
        let overlay = game.join(name);
        if overlay.join("Default.xex").is_file() {
            return (overlay.clone(), overlay.join("Default.xex"));
        }
    }
    (game.to_path_buf(), game.join("Default.xex"))
}

pub fn sha256_file(path: &Path) -> Result<String, String> {
    let data = fs::read(path).map_err(|e| format!("{}: {e}", path.display()))?;
    Ok(format!("{:x}", Sha256::digest(&data)))
}

fn has_extras_marker(executable: &Path) -> bool {
    fs::read(executable)
        .map(|data| {
            data.windows(EXTRAS_MARKER.len())
                .any(|w| w == EXTRAS_MARKER)
        })
        .unwrap_or(false)
}

/// Adds the builds an executable offers: plain, and with extras when it was
/// compiled with the optional PC features. Earlier entries win a duplicate.
fn push_builds(
    builds: &mut Vec<Build>,
    update: bool,
    has_extras: bool,
    executable: &Path,
    game_dir: Option<&Path>,
) {
    for extras in [false, true] {
        if (extras && !has_extras) || builds.iter().any(|b| b.update == update && b.extras == extras) {
            continue;
        }
        builds.push(make_build(
            update,
            extras,
            executable.to_path_buf(),
            game_dir.map(Path::to_path_buf),
        ));
    }
}

/// Finds game builds for `platform`. A release install keeps one executable
/// beside the launcher and its game folder; its update flavour is read from that
/// folder's Default.xex and whether it carries the extras from the executable
/// itself. A source checkout is found from `search_from` upwards and offers
/// every built `port/out/build/<platform>-amd64[-update][-plain]-<config>`
/// variant (`-plain` was compiled without the extras).
pub fn discover_builds(
    platform: Platform,
    launcher_dir: &Path,
    search_from: &[PathBuf],
) -> Vec<Build> {
    let mut builds = Vec::new();
    let installed = launcher_dir.join(platform.executable());
    if installed.is_file() {
        let game = launcher_dir.join("game");
        let update = sha256_file(&update_layout(&game).1).is_ok_and(|h| h == USA_UPDATE_HASH);
        push_builds(&mut builds, update, has_extras_marker(&installed), &installed, Some(&game));
    }
    if let Some(root) = repository_root(search_from) {
        for (update, plain) in [(false, false), (true, false), (false, true), (true, true)] {
            // Update builds compiled before the rename live in `…-tu2-…` directories.
            let flavours: &[&str] = if update { &["-update", "-tu2"] } else { &[""] };
            let found = flavours.iter().find_map(|flavour| {
                let mut name = platform.build_prefix().to_string() + flavour;
                if plain {
                    name += "-plain";
                }
                ["relwithdebinfo", "release", "debug"].iter().find_map(|config| {
                    let exe = root
                        .join("port/out/build")
                        .join(format!("{name}-{config}"))
                        .join(platform.executable());
                    exe.is_file().then_some(exe)
                })
            });
            if let Some(exe) = found {
                push_builds(&mut builds, update, !plain, &exe, None);
            }
        }
    }
    builds
}

pub fn repository_root(search_from: &[PathBuf]) -> Option<PathBuf> {
    search_from.iter().find_map(|start| {
        start
            .ancestors()
            .find(|p| p.join("port/CMakeLists.txt").is_file())
            .map(Path::to_path_buf)
    })
}

/// Launcher settings persisted in launcher.json. Empty strings use defaults.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct Settings {
    pub game_dir: String,
    pub game_dir_update: String,
    pub user_data_root: String,
    pub user_data_root_update: String,
    /// In-game player name; empty keeps the SDK default.
    pub username: String,
    /// Linux only; -1 lets the SDK choose.
    pub vulkan_device: i32,
    /// Linux display server: "" (automatic), "wayland" or "x11".
    pub video_driver: String,
    /// Last inputs of the Build panel (scripts/build_client.py).
    pub build_iso: String,
    pub build_title_update: String,
    pub build_cmake: String,
    pub ui_state: serde_json::Value,
}

impl Default for Settings {
    fn default() -> Self {
        Settings {
            game_dir: String::new(),
            game_dir_update: String::new(),
            user_data_root: String::new(),
            user_data_root_update: String::new(),
            username: String::new(),
            vulkan_device: -1,
            video_driver: String::new(),
            build_iso: String::new(),
            build_title_update: String::new(),
            build_cmake: String::new(),
            ui_state: serde_json::Value::Null,
        }
    }
}

/// Reads launcher.json. The first prototype stored one game/save folder plus a
/// `tu2` flag; a flagged entry moves to the update fields so its saves stay in use.
/// The update fields were once called `gameDirTu2`/`userDataRootTu2`; those still load.
pub fn parse_settings(data: &[u8]) -> Settings {
    let Ok(mut raw) = serde_json::from_slice::<serde_json::Value>(data) else {
        return Settings::default();
    };
    if let Some(fields) = raw.as_object_mut() {
        for (old, new) in [("gameDirTu2", "gameDirUpdate"), ("userDataRootTu2", "userDataRootUpdate")] {
            if let Some(value) = fields.remove(old) {
                fields.entry(new).or_insert(value);
            }
        }
    }
    let mut settings: Settings = serde_json::from_value(raw.clone()).unwrap_or_default();
    if raw.get("tu2") == Some(&serde_json::Value::Bool(true)) && raw.get("gameDirUpdate").is_none() {
        settings.game_dir_update = std::mem::take(&mut settings.game_dir);
        settings.user_data_root_update = std::mem::take(&mut settings.user_data_root);
    }
    settings
}

/// Folder defaults shown as placeholders and used for empty settings.
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Defaults {
    pub game_dir: PathBuf,
    pub game_dir_update: PathBuf,
    pub user_data_root: PathBuf,
    pub user_data_root_update: PathBuf,
}

/// Linux matches run_linux.py ($XDG_DATA_HOME/souls-of-the-reaper[-update]).
/// Windows matches run_windows.ps1 and the SDK default (Documents\diablo3).
pub fn default_folders(platform: Platform, base: &Path, user_base: &Path) -> Defaults {
    let (user, user_update, user_legacy) = match platform {
        Platform::Linux => (
            user_base.join("souls-of-the-reaper"),
            user_base.join("souls-of-the-reaper-update"),
            user_base.join("souls-of-the-reaper-tu2"),
        ),
        Platform::Windows => (
            user_base.join("diablo3"),
            user_base.join("diablo3-update"),
            user_base.join("diablo3-tu2"),
        ),
    };
    // Saves created before the folder was renamed (`-tu2`) stay in use.
    let user_update = if !user_update.exists() && user_legacy.exists() {
        user_legacy
    } else {
        user_update
    };
    Defaults {
        game_dir: base.join("game"),
        // The title update is an overlay inside the game folder unless a full staged copy exists.
        game_dir_update: ["game-update", "game-tu2"]
            .iter()
            .map(|name| base.join(name))
            .find(|dir| dir.exists())
            .unwrap_or_else(|| base.join("game")),
        user_data_root: user,
        user_data_root_update: user_update,
    }
}

fn choose(setting: &str, default: &Path) -> PathBuf {
    if setting.trim().is_empty() {
        default.to_path_buf()
    } else {
        PathBuf::from(setting.trim())
    }
}

/// The game folder the update runs from. The title update is normally an overlay (`<game>/update`) inside the
/// base game folder, so that folder is used. An older full staged copy still works: a
/// saved update folder that holds an executable, else a `game-update` default that exists.
fn update_game_folder(settings: &Settings, defaults: &Defaults, base_game: &Path) -> PathBuf {
    let saved = settings.game_dir_update.trim();
    if !saved.is_empty() && Path::new(saved).join("Default.xex").is_file() {
        return PathBuf::from(saved);
    }
    if update_layout(base_game).0 != base_game {
        return base_game.to_path_buf();
    }
    if defaults.game_dir_update != defaults.game_dir {
        return defaults.game_dir_update.clone();
    }
    base_game.to_path_buf()
}

/// Base and update game folders (often the same folder): settings, then defaults.
pub fn game_folders(settings: &Settings, defaults: &Defaults) -> (PathBuf, PathBuf) {
    let base = choose(&settings.game_dir, &defaults.game_dir);
    let update = update_game_folder(settings, defaults, &base);
    (base, update)
}

/// Game and save folders for `build`: settings, then the release pairing,
/// then defaults. The title update uses separate save folders so saves never mix.
pub fn folders_for(build: &Build, settings: &Settings, defaults: &Defaults) -> (PathBuf, PathBuf) {
    let base_default = build.game_dir.as_deref().unwrap_or(&defaults.game_dir);
    let base = choose(&settings.game_dir, base_default);
    if build.update {
        (
            update_game_folder(settings, defaults, &base),
            choose(&settings.user_data_root_update, &defaults.user_data_root_update),
        )
    } else {
        (base, choose(&settings.user_data_root, &defaults.user_data_root))
    }
}

/// Windows `canonicalize` returns `\\?\C:\...` paths, which the Windows API does not
/// normalise: the game appends `update/Default.xex` with a forward slash and then fails to
/// open it. Drop the prefix for plain drive paths.
pub fn plain_path(path: PathBuf) -> PathBuf {
    let text = path.to_string_lossy().into_owned();
    match text.strip_prefix(r"\\?\") {
        Some(rest) if rest.as_bytes().get(1) == Some(&b':') => PathBuf::from(rest),
        _ => path,
    }
}

/// Checks the game folder holds the executable this build was compiled for.
pub fn validate_game_dir(build: &Build, game: &Path) -> Result<(), String> {
    let (update_root, update_xex) = update_layout(game);
    let xex = if build.update { update_xex } else { game.join("Default.xex") };
    if !xex.is_file() {
        return Err(format!(
            "{} has no Default.xex. Choose the {} game folder in Launch settings (Linux filenames are case-sensitive).",
            game.display(),
            if build.update { "staged update" } else { "extracted base-disc" }
        ));
    }
    let hash = sha256_file(&xex)?;
    let (expected, other, wanted, found) = if build.update {
        (USA_UPDATE_HASH, BASE_HASH, "the staged update", "the base-disc")
    } else {
        (BASE_HASH, USA_UPDATE_HASH, "the unmodified base-disc", "the update")
    };
    if hash != expected {
        if build.update && hash == other && xex.parent() == Some(game) {
            return Err(format!(
                "The title update is not installed in {} (there is no update/Default.xex). Open Launch settings, choose Build from disc image… and pick the Title Update package to add it.",
                game.display()
            ));
        }
        return Err(if hash == other {
            format!(
                "{} holds {found} executable; the {} build needs {wanted} folder.",
                game.display(),
                build.label
            )
        } else {
            format!("Default.xex in {} is not the verified USA Ultimate Evil Edition {wanted} executable.", game.display())
        });
    }
    if build.update {
        if let Some(missing) = UPDATE_CPKS
            .iter()
            .find(|n| !update_root.join("CPKs").join(n).is_file())
        {
            return Err(format!(
                "Missing update asset CPKs/{missing} in {}.",
                update_root.display()
            ));
        }
    }
    Ok(())
}

/// True when an update build exists and its game folder holds the verified update
/// executable and CPKs. The title update is an overlay in the base game folder, so providing
/// the update is what makes the update builds usable.
pub fn update_installed(builds: &[Build], settings: &Settings, defaults: &Defaults) -> bool {
    builds.iter().filter(|b| b.update).any(|b| {
        let (game, _) = folders_for(b, settings, defaults);
        validate_game_dir(b, &game).is_ok()
    })
}

/// Seeds the menu's build choice when none was saved (or the saved one is gone):
/// the update build with the same extras setting as the first build, when update is
/// installed. An explicit saved choice is never overridden.
pub fn apply_default_build(
    ui_state: &mut serde_json::Value,
    builds: &[Build],
    update_installed: bool,
) {
    let saved = ui_state
        .get("build")
        .and_then(|v| v.as_str())
        .is_some_and(|id| builds.iter().any(|b| b.id == id));
    if saved || !update_installed {
        return;
    }
    let extras = builds.first().is_some_and(|b| b.extras);
    let pick = builds
        .iter()
        .find(|b| b.update && b.extras == extras)
        .or_else(|| builds.iter().find(|b| b.update));
    if let (Some(build), Some(state)) = (pick, ui_state.as_object_mut()) {
        state.insert("build".into(), build.id.clone().into());
    }
}

/// Build ids scripts/build_client.py accepts.
/// `-plain` compiles without the optional PC features.
pub const BUILD_VARIANTS: [&str; 4] = ["base", "update", "base-plain", "update-plain"];

/// Inputs of the Build panel.
#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BuildRequest {
    pub iso: String,
    pub title_update: String,
    pub variants: Vec<String>,
    pub cmake: String,
    /// The user agreed to fetch and build the pinned ReXGlue SDK when it is missing.
    #[serde(default)]
    pub download_sdk: bool,
    /// The user agreed to fetch the repository sources when the launcher has no checkout.
    #[serde(default)]
    pub download_sources: bool,
}

/// Arguments for scripts/build_client.py, writing into the launcher's game
/// folders. The script compiles with build_linux.py or build_windows.py,
/// whichever matches the host.
pub fn build_client_arguments(
    _platform: Platform,
    repo: &Path,
    request: &BuildRequest,
    game: &Path,
    game_update: &Path,
) -> Result<Vec<String>, String> {
    let mut args = vec![
        repo.join("scripts/build_client.py").display().to_string(),
        format!("--game-dir={}", game.display()),
    ];
    // One folder for both means update is built as an overlay inside it.
    if game_update != game {
        args.push(format!("--game-dir-update={}", game_update.display()));
    }
    for (flag, value) in [
        ("--iso", &request.iso),
        ("--title-update", &request.title_update),
        ("--cmake", &request.cmake),
    ] {
        if !value.trim().is_empty() {
            args.push(format!("{flag}={}", value.trim()));
        }
    }
    if let Some(bad) = request
        .variants
        .iter()
        .find(|v| !BUILD_VARIANTS.contains(&v.as_str()))
    {
        return Err(format!("Unknown build {bad}."));
    }
    if request.variants.is_empty() {
        return Err("Choose at least one build.".into());
    }
    args.push(format!("--variants={}", request.variants.join(",")));
    if !request.download_sdk {
        args.push("--no-sdk-download".into());
    }
    Ok(args)
}

/// Choices from the launcher menu (buildLaunchConfig in the HTML).
#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GameOptions {
    pub build: Option<String>,
    pub fps: u32,
    pub vsync: bool,
    pub mnk_mouse: bool,
    pub present: String,
    /// 0 keeps the extras build's saved in-game scale.
    pub res_scale: u32,
    /// None keeps the extras build's saved in-game window mode.
    pub fullscreen: Option<bool>,
    pub lang_id: u32,
    pub country_id: u32,
    pub rtp: String,
    pub vk_path: String,
    /// Windows renderer: "d3d12" (also when absent) or "vulkan". Linux is always Vulkan.
    #[serde(default)]
    pub backend: String,
    /// Linux display server, filled from the saved settings (the page does not send it).
    #[serde(default)]
    pub video_driver: String,
}

/// Image scaling for the Vulkan presenter. The effect is only compiled into
/// SDKs built with patches/linux/rexglue-present-effects.patch (or Windows').
fn vulkan_present(options: &GameOptions) -> Result<&str, String> {
    match options.present.as_str() {
        // Older saved settings and Launcher.ps1 send "fsr" by default; the UI
        // always sends an explicit choice, so pass it through unchanged.
        present @ ("bilinear" | "fsr" | "cas") => Ok(present),
        _ => Err("Unsupported image scaling.".into()),
    }
}

pub fn launch_arguments(
    platform: Platform,
    build: &Build,
    game: &Path,
    user: &Path,
    options: &GameOptions,
    vulkan_device: i32,
) -> Result<Vec<String>, String> {
    if options.res_scale > 3 || (options.res_scale == 0 && !build.extras) {
        return Err("Choose a supported internal resolution.".into());
    }
    if options.fullscreen.is_none() && !build.extras {
        return Err("Choose fullscreen or windowed.".into());
    }
    let mut args = vec![
        format!("--game_data_root={}", game.display()),
        format!("--user_data_root={}", user.display()),
    ];
    if build.extras {
        args.push("--extra_features=true".into());
    }
    if build.update {
        // The update reads its patch CPKs through update:\ even with a prepatched XEX.
        args.push(format!("--update_data_root={}", update_layout(game).0.display()));
    }
    match platform {
        Platform::Linux => {
            if !["fsi", "host"].contains(&options.vk_path.as_str()) {
                return Err("Unsupported Vulkan render path.".into());
            }
            args.push(format!("--cache_root={}", user.join("cache").display()));
            args.push(format!("--log_file={}", user.join("diablo3.log").display()));
            args.push(format!("--render_target_path_vulkan={}", options.vk_path));
            args.push(format!("--vsync={}", options.vsync));
            args.push(format!("--present_effect={}", vulkan_present(options)?));
            if vulkan_device >= 0 {
                args.push(format!("--vulkan_device={vulkan_device}"));
            }
            match options.video_driver.as_str() {
                "" => {}
                driver @ ("wayland" | "x11") => args.push(format!("--video_driver={driver}")),
                _ => return Err("Unsupported display server.".into()),
            }
        }
        Platform::Windows => {
            // One executable holds both renderers; --gpu_backend picks one.
            let backend = match options.backend.as_str() {
                "" | "d3d12" => "d3d12",
                "vulkan" => "vulkan",
                _ => return Err("Unsupported renderer.".into()),
            };
            args.push(format!("--gpu_backend={backend}"));
            if backend == "vulkan" {
                // Same rules as Linux: the Vulkan backend has no D3D12 render
                // path or frame limiter, but shares the FSR/CAS presenter.
                if !["fsi", "host"].contains(&options.vk_path.as_str()) {
                    return Err("Unsupported Vulkan render path.".into());
                }
                args.push(format!("--render_target_path_vulkan={}", options.vk_path));
                args.push(format!("--vsync={}", options.vsync));
                args.push(format!("--present_effect={}", vulkan_present(options)?));
                if vulkan_device >= 0 {
                    args.push(format!("--vulkan_device={vulkan_device}"));
                }
            } else {
                if !["rov", "rtv"].contains(&options.rtp.as_str()) {
                    return Err("Unsupported render path.".into());
                }
                if ![30, 60, 120, 144, 240].contains(&options.fps) {
                    return Err("Unsupported frame rate.".into());
                }
                if !["fsr", "cas", "bilinear"].contains(&options.present.as_str()) {
                    return Err("Unsupported image scaling.".into());
                }
                args.push(format!("--render_target_path_d3d12={}", options.rtp));
                args.push("--rtv_color_depth_ownership_mode=8".into());
                args.push("--execute_unclipped_draw_vs_on_cpu=true".into());
                args.push(format!("--d3_frame_limit={}", options.fps));
                args.push(format!("--vsync={}", options.vsync));
                args.push(format!("--present_effect={}", options.present));
            }
            args.push("--mnk_cursor_visible=false".into());
        }
    }
    args.push("--mnk_mode=true".into());
    args.push(format!("--mnk_mouse={}", options.mnk_mouse));
    args.push(format!("--user_language={}", options.lang_id));
    args.push(format!("--user_country={}", options.country_id));
    if options.res_scale > 0 {
        args.push(format!("--draw_resolution_scale_x={}", options.res_scale));
        args.push(format!("--draw_resolution_scale_y={}", options.res_scale));
        if build.extras {
            args.push("--pc_use_saved_render_scale=false".into());
        }
    }
    if let Some(fullscreen) = options.fullscreen {
        args.push(format!("--fullscreen={fullscreen}"));
        if build.extras {
            args.push("--pc_use_saved_window_mode=false".into());
        }
    }
    Ok(args)
}

/// Page links (the font credit under Play) that open in the default browser.
/// Only plain web URLs: no spaces, quotes or shell metacharacters, so the value
/// is safe to hand to the OS opener as a single argument.
pub fn is_external_url(url: &str) -> bool {
    let Some(rest) = url.strip_prefix("https://") else {
        return false;
    };
    !rest.is_empty()
        && url.len() <= 2048
        && url.chars().all(|c| c.is_ascii_alphanumeric() || "-._~:/?#[]@!$&()*+,;=%".contains(c))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_plain_https_links_open_externally() {
        assert!(is_external_url("https://fernandoforeroart.com/old-fenris-diablo-iv-official-font"));
        assert!(!is_external_url("http://example.com"));
        assert!(!is_external_url("file:///C:/Windows/System32/calc.exe"));
        assert!(!is_external_url("javascript:alert(1)"));
        assert!(!is_external_url("https://"));
        assert!(!is_external_url("https://example.com/a b"));
        assert!(!is_external_url("https://example.com/\"&calc.exe"));
        assert!(!is_external_url("https://example.com/a|b"));
    }

    fn options() -> GameOptions {
        GameOptions {
            build: None,
            fps: 120,
            vsync: false,
            mnk_mouse: false,
            present: "fsr".into(),
            res_scale: 2,
            fullscreen: Some(true),
            lang_id: 1,
            country_id: 103,
            rtp: "rtv".into(),
            vk_path: "fsi".into(),
            backend: String::new(),
            video_driver: String::new(),
        }
    }

    fn request(variants: &[&str]) -> BuildRequest {
        BuildRequest {
            iso: " /isos/d3 usa.iso ".into(),
            title_update: String::new(),
            variants: variants.iter().map(|v| v.to_string()).collect(),
            cmake: String::new(),
            download_sdk: false,
            download_sources: false,
        }
    }

    #[test]
    fn build_arguments_target_launcher_game_folders() {
        let args = build_client_arguments(
            Platform::Linux,
            Path::new("/repo"),
            &request(&["base", "update-plain"]),
            Path::new("/g/base"),
            Path::new("/g/update"),
        )
        .unwrap();
        let script = Path::new("/repo").join("scripts/build_client.py");
        assert_eq!(
            args,
            [
                script.to_str().unwrap(),
                "--game-dir=/g/base",
                "--game-dir-update=/g/update",
                "--iso=/isos/d3 usa.iso",
                "--variants=base,update-plain",
                "--no-sdk-download",
            ]
        );
        let mut approved = request(&["base"]);
        approved.download_sdk = true;
        let args = build_client_arguments(
            Platform::Linux,
            Path::new("/repo"),
            &approved,
            Path::new("/g"),
            Path::new("/g"),
        )
        .unwrap();
        assert!(!args.contains(&"--no-sdk-download".to_string()));
    }

    #[test]
    fn build_arguments_reject_unknown_or_missing_builds() {
        let folders = (Path::new("/g"), Path::new("/t"));
        let run = |platform, variants: &[&str]| {
            build_client_arguments(platform, Path::new("/r"), &request(variants), folders.0, folders.1)
        };
        for platform in [Platform::Linux, Platform::Windows] {
            assert!(run(platform, &[]).is_err());
            assert!(run(platform, &["base;rm"]).is_err());
        }
        let windows = run(Platform::Windows, &["base", "update"]).unwrap();
        assert!(windows.contains(&"--variants=base,update".to_string()));
        assert!(!windows.contains(&"--data-only".to_string()));
    }

    fn build(update: bool, extras: bool) -> Build {
        make_build(update, extras, PathBuf::from("diablo3"), None)
    }

    fn scratch(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("sotr-launcher-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn update_mounts_update_root_and_keeps_paths_with_spaces() {
        let game = Path::new("/tmp/game with spaces");
        let args = launch_arguments(
            Platform::Linux,
            &build(true, false),
            game,
            Path::new("/s d"),
            &options(),
            1,
        )
        .unwrap();
        assert!(args.contains(&"--game_data_root=/tmp/game with spaces".into()));
        assert!(args.contains(&"--update_data_root=/tmp/game with spaces".into()));
        let log = Path::new("/s d").join("diablo3.log");
        assert!(args.contains(&format!("--log_file={}", log.display())));
        let base = launch_arguments(
            Platform::Linux,
            &build(false, false),
            game,
            Path::new("/s"),
            &options(),
            1,
        )
        .unwrap();
        assert!(!base.iter().any(|a| a.starts_with("--update_data_root")));
    }

    #[test]
    fn display_server_setting_loads_and_defaults_to_automatic() {
        assert_eq!(parse_settings(br#"{"videoDriver":"x11"}"#).video_driver, "x11");
        assert_eq!(parse_settings(br#"{"gameDir":"/g"}"#).video_driver, "");
    }

    #[test]
    fn linux_display_server_is_passed_only_when_chosen() {
        let run = |platform, driver: &str| {
            let mut o = options();
            o.video_driver = driver.into();
            launch_arguments(platform, &build(false, false), Path::new("/g"), Path::new("/s"), &o, -1)
        };
        let auto = run(Platform::Linux, "").unwrap();
        assert!(!auto.iter().any(|a| a.starts_with("--video_driver")));
        assert!(run(Platform::Linux, "wayland").unwrap().contains(&"--video_driver=wayland".into()));
        assert!(run(Platform::Linux, "x11").unwrap().contains(&"--video_driver=x11".into()));
        assert!(run(Platform::Linux, "mir").is_err());
        let windows = run(Platform::Windows, "wayland").unwrap();
        assert!(!windows.iter().any(|a| a.starts_with("--video_driver")), "Windows ignores it");
    }

    #[test]
    fn linux_omits_d3d12_and_windows_only_options() {
        let args = launch_arguments(
            Platform::Linux,
            &build(false, false),
            Path::new("/g"),
            Path::new("/s"),
            &options(),
            -1,
        )
        .unwrap();
        assert!(args.contains(&"--render_target_path_vulkan=fsi".into()));
        assert!(!args.iter().any(|a| a.contains("d3d12") || a.contains("d3_frame_limit")));
        assert!(args.contains(&"--present_effect=fsr".into()));
        let mut off = options();
        off.present = "bilinear".into();
        let off_args = launch_arguments(
            Platform::Linux,
            &build(false, false),
            Path::new("/g"),
            Path::new("/s"),
            &off,
            -1,
        )
        .unwrap();
        assert!(off_args.contains(&"--present_effect=bilinear".into()));
        off.present = "fsr2".into();
        assert!(launch_arguments(
            Platform::Linux,
            &build(false, false),
            Path::new("/g"),
            Path::new("/s"),
            &off,
            -1
        )
        .is_err());
        assert!(
            !args.iter().any(|a| a.starts_with("--vulkan_device")),
            "auto device passes nothing"
        );
        let pinned = launch_arguments(
            Platform::Linux,
            &build(false, false),
            Path::new("/g"),
            Path::new("/s"),
            &options(),
            0,
        )
        .unwrap();
        assert!(pinned.contains(&"--vulkan_device=0".into()));
    }

    #[test]
    fn windows_passes_d3d12_presentation_and_frame_limit() {
        let args = launch_arguments(
            Platform::Windows,
            &build(false, false),
            Path::new("C:\\g"),
            Path::new("C:\\s"),
            &options(),
            1,
        )
        .unwrap();
        for expected in [
            "--render_target_path_d3d12=rtv",
            "--d3_frame_limit=120",
            "--present_effect=fsr",
            "--vsync=false",
        ] {
            assert!(args.contains(&expected.into()), "{expected}");
        }
        assert!(args.contains(&"--gpu_backend=d3d12".into()));
        assert!(!args.iter().any(|a| a.contains("vulkan")));
    }

    fn pair(update: bool, extras: bool) -> Build {
        make_build(update, extras, PathBuf::from("/x"), None)
    }

    #[test]
    fn update_becomes_the_default_build_when_it_is_installed() {
        let builds = [pair(false, false), pair(false, true), pair(true, false), pair(true, true)];
        let mut state = serde_json::json!({ "res": -1 });
        apply_default_build(&mut state, &builds, true);
        assert_eq!(state["build"], "update");
        assert_eq!(state["res"], -1, "other saved menu state is kept");

        // Extras builds first: the update default keeps extras.
        let extras_first = [pair(false, true), pair(true, true)];
        let mut state = serde_json::Value::Null;
        state = if state.is_null() { serde_json::json!({}) } else { state };
        apply_default_build(&mut state, &extras_first, true);
        assert_eq!(state["build"], "update-extras");
    }

    #[test]
    fn default_build_respects_saved_choice_and_missing_update() {
        let builds = [pair(false, false), pair(true, false)];
        let mut saved = serde_json::json!({ "build": "base" });
        apply_default_build(&mut saved, &builds, true);
        assert_eq!(saved["build"], "base", "explicit choice wins");
        let mut none = serde_json::json!({});
        apply_default_build(&mut none, &builds, false);
        assert!(none.get("build").is_none(), "no update files, stay on base");
        let mut stale = serde_json::json!({ "build": "update-plain" });
        apply_default_build(&mut stale, &builds, true);
        assert_eq!(stale["build"], "update", "a saved build that no longer exists is replaced");
        let mut only_base = serde_json::json!({});
        apply_default_build(&mut only_base, &[pair(false, false)], true);
        assert!(only_base.get("build").is_none(), "no update build to select");
    }

    #[test]
    fn windows_vulkan_uses_vulkan_options_not_d3d12_ones() {
        let mut opts = options();
        opts.backend = "vulkan".into();
        opts.vsync = true;
        let args = launch_arguments(
            Platform::Windows,
            &build(false, true),
            Path::new("C:/g"),
            Path::new("C:/s"),
            &opts,
            1,
        )
        .unwrap();
        for expected in [
            "--gpu_backend=vulkan",
            "--render_target_path_vulkan=fsi",
            "--vsync=true",
            "--vulkan_device=1",
            "--present_effect=fsr",
            "--mnk_cursor_visible=false",
        ] {
            assert!(args.contains(&expected.into()), "{expected}");
        }
        assert!(!args.iter().any(|a| a.contains("d3d12")
            || a.contains("d3_frame_limit")
            || a.contains("rtv_color_depth")));
        opts.backend = "metal".into();
        assert!(launch_arguments(
            Platform::Windows,
            &build(false, true),
            Path::new("C:/g"),
            Path::new("C:/s"),
            &opts,
            -1,
        )
        .is_err());
    }

    #[test]
    fn extras_in_game_choices_leave_saved_settings_alone() {
        let mut opts = options();
        opts.res_scale = 0;
        opts.fullscreen = None;
        let args = launch_arguments(
            Platform::Linux,
            &build(false, true),
            Path::new("/g"),
            Path::new("/s"),
            &opts,
            -1,
        )
        .unwrap();
        assert!(!args.iter().any(|a| a.contains("resolution_scale")
            || a.contains("pc_use_saved")
            || a.starts_with("--fullscreen")));
        // The same choices are invalid for a normal build.
        assert!(launch_arguments(
            Platform::Linux,
            &build(false, false),
            Path::new("/g"),
            Path::new("/s"),
            &opts,
            -1
        )
        .is_err());
    }

    #[test]
    fn extras_flag_is_only_passed_when_chosen() {
        let run = |extras| {
            launch_arguments(
                Platform::Linux,
                &build(false, extras),
                Path::new("/g"),
                Path::new("/s"),
                &options(),
                -1,
            )
            .unwrap()
        };
        assert!(run(true).contains(&"--extra_features=true".to_string()));
        assert!(!run(false).iter().any(|a| a.starts_with("--extra_features")));
    }

    #[test]
    fn extras_explicit_choices_override_saved_settings() {
        let args = launch_arguments(
            Platform::Windows,
            &build(true, true),
            Path::new("/g"),
            Path::new("/s"),
            &options(),
            -1,
        )
        .unwrap();
        for expected in [
            "--draw_resolution_scale_x=2",
            "--pc_use_saved_render_scale=false",
            "--fullscreen=true",
            "--pc_use_saved_window_mode=false",
        ] {
            assert!(args.contains(&expected.into()), "{expected}");
        }
        let normal = launch_arguments(
            Platform::Windows,
            &build(false, false),
            Path::new("/g"),
            Path::new("/s"),
            &options(),
            -1,
        )
        .unwrap();
        assert!(
            !normal.iter().any(|a| a.starts_with("--pc_use_saved")),
            "normal builds lack these cvars"
        );
    }

    #[test]
    fn rejects_unsupported_values() {
        let mut opts = options();
        opts.res_scale = 4;
        assert!(launch_arguments(
            Platform::Linux,
            &build(false, true),
            Path::new("/g"),
            Path::new("/s"),
            &opts,
            -1
        )
        .is_err());
        let mut opts = options();
        opts.vk_path = "rov".into();
        assert!(launch_arguments(
            Platform::Linux,
            &build(false, false),
            Path::new("/g"),
            Path::new("/s"),
            &opts,
            -1
        )
        .is_err());
        let mut opts = options();
        opts.fps = 75;
        assert!(launch_arguments(
            Platform::Windows,
            &build(false, false),
            Path::new("/g"),
            Path::new("/s"),
            &opts,
            -1
        )
        .is_err());
    }

    #[test]
    fn discovers_source_builds_by_variant_and_prefers_relwithdebinfo() {
        let root = scratch("discover");
        fs::create_dir_all(root.join("port")).unwrap();
        fs::write(root.join("port/CMakeLists.txt"), "").unwrap();
        for dir in [
            "linux-amd64-relwithdebinfo",
            "linux-amd64-update-plain-release",
            "linux-amd64-update-plain-relwithdebinfo",
            "win-amd64-relwithdebinfo",
        ] {
            let path = root.join("port/out/build").join(dir);
            fs::create_dir_all(&path).unwrap();
            fs::write(
                path.join(if dir.starts_with("win") {
                    "diablo3.exe"
                } else {
                    "diablo3"
                }),
                "",
            )
            .unwrap();
        }
        let builds = discover_builds(
            Platform::Linux,
            &root.join("launcher"),
            &[root.join("launcher/tauri")],
        );
        let ids: Vec<_> = builds.iter().map(|b| b.id.as_str()).collect();
        // The full build is offered with and without extras; the plain update build only without.
        assert_eq!(ids, ["base", "extras", "update"]);
        assert_eq!(builds[0].executable, builds[1].executable);
        assert!(builds[2]
            .executable
            .ends_with("linux-amd64-update-plain-relwithdebinfo/diablo3"));
        let windows = discover_builds(Platform::Windows, &root, std::slice::from_ref(&root));
        assert_eq!(windows.len(), 2);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn update_builds_from_before_the_rename_are_still_discovered() {
        let root = scratch("discover-legacy");
        fs::create_dir_all(root.join("port")).unwrap();
        fs::write(root.join("port/CMakeLists.txt"), "").unwrap();
        let old = root.join("port/out/build/linux-amd64-tu2-relwithdebinfo");
        fs::create_dir_all(&old).unwrap();
        fs::write(old.join("diablo3"), "").unwrap();
        let builds = discover_builds(Platform::Linux, &root, std::slice::from_ref(&root));
        assert_eq!(builds.len(), 2, "update, and update with extras");
        assert!(builds[0].update && builds[0].executable.starts_with(&old));
        // A rebuilt update directory wins over the old one.
        let new = root.join("port/out/build/linux-amd64-update-relwithdebinfo");
        fs::create_dir_all(&new).unwrap();
        fs::write(new.join("diablo3"), "").unwrap();
        let builds = discover_builds(Platform::Linux, &root, std::slice::from_ref(&root));
        assert!(builds[0].executable.starts_with(&new));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn release_install_detects_extras_from_the_executable() {
        let root = scratch("release");
        fs::write(root.join("diablo3"), b"...pc_use_saved_render_scale...").unwrap();
        let builds = discover_builds(Platform::Linux, &root, &[]);
        assert_eq!(builds.len(), 2);
        assert!(!builds[0].extras && builds[1].extras && !builds[1].update);
        assert_eq!(
            builds[0].game_dir.as_deref(),
            Some(root.join("game").as_path())
        );
        fs::write(root.join("diablo3"), b"plain").unwrap();
        let builds = discover_builds(Platform::Linux, &root, &[]);
        assert_eq!(builds.len(), 1);
        assert!(!builds[0].extras);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn validation_names_the_folder_mismatch() {
        let game = scratch("validate");
        assert!(validate_game_dir(&build(false, false), &game)
            .unwrap_err()
            .contains("no Default.xex"));
        fs::write(game.join("Default.xex"), "not a real xex").unwrap();
        assert!(validate_game_dir(&build(true, false), &game)
            .unwrap_err()
            .contains("not the verified"));
        fs::remove_dir_all(game).unwrap();
    }

    #[test]
    fn missing_settings_fields_keep_automatic_vulkan_device() {
        let settings = parse_settings(br#"{"gameDir":"/g","executable":"old prototype field"}"#);
        assert_eq!(
            (settings.game_dir.as_str(), settings.vulkan_device),
            ("/g", -1)
        );
        assert_eq!(parse_settings(b"not json").vulkan_device, -1);
    }

    #[test]
    fn prototype_update_settings_move_to_update_folders() {
        let settings = parse_settings(
            br#"{"gameDir":"/update","userDataRoot":"/saves","tu2":true,"vulkanDevice":1}"#,
        );
        assert_eq!(settings.game_dir_update, "/update");
        assert_eq!(settings.user_data_root_update, "/saves");
        assert!(settings.game_dir.is_empty() && settings.user_data_root.is_empty());
        assert_eq!(settings.vulkan_device, 1);
        // Files written by this launcher are never migrated again.
        let current = parse_settings(br#"{"gameDir":"/base","gameDirUpdate":"/update","tu2":true}"#);
        assert_eq!(current.game_dir, "/base");
    }

    #[test]
    fn settings_saved_under_the_old_tu2_names_still_load() {
        let settings = parse_settings(
            br#"{"gameDir":"/base","gameDirTu2":"/old","userDataRootTu2":"/old-saves"}"#,
        );
        assert_eq!(settings.game_dir, "/base");
        assert_eq!(settings.game_dir_update, "/old");
        assert_eq!(settings.user_data_root_update, "/old-saves");
        // The new key wins when both are present.
        let both = parse_settings(br#"{"gameDirTu2":"/old","gameDirUpdate":"/new"}"#);
        assert_eq!(both.game_dir_update, "/new");
    }

    #[test]
    fn legacy_tu2_overlay_saves_and_staged_folder_are_still_found() {
        let root = scratch("legacy-tu2");
        let game = root.join("game");
        fs::create_dir_all(game.join("tu2")).unwrap();
        fs::write(game.join("tu2").join("Default.xex"), b"x").unwrap();
        assert_eq!(update_layout(&game).0, game.join("tu2"));
        fs::create_dir_all(game.join("update")).unwrap();
        fs::write(game.join("update").join("Default.xex"), b"x").unwrap();
        assert_eq!(update_layout(&game).0, game.join("update"), "the new name wins");

        let data = root.join("data");
        fs::create_dir_all(data.join("souls-of-the-reaper-tu2")).unwrap();
        let old = default_folders(Platform::Linux, &root, &data);
        assert!(old.user_data_root_update.ends_with("souls-of-the-reaper-tu2"));
        fs::create_dir_all(data.join("souls-of-the-reaper-update")).unwrap();
        let new = default_folders(Platform::Linux, &root, &data);
        assert!(new.user_data_root_update.ends_with("souls-of-the-reaper-update"));
        fs::create_dir_all(root.join("game-tu2")).unwrap();
        assert_eq!(default_folders(Platform::Linux, &root, &data).game_dir_update, root.join("game-tu2"));
    }

    #[test]
    fn plain_path_drops_the_verbatim_drive_prefix_only() {
        assert_eq!(
            plain_path(PathBuf::from(r"\\?\C:\Users\me\game")),
            PathBuf::from(r"C:\Users\me\game")
        );
        assert_eq!(
            plain_path(PathBuf::from(r"\\?\UNC\server\share")),
            PathBuf::from(r"\\?\UNC\server\share")
        );
        assert_eq!(plain_path(PathBuf::from("/home/me/game")), PathBuf::from("/home/me/game"));
    }

    #[test]
    fn update_uses_the_base_folder_unless_an_older_staged_copy_exists() {
        let root = scratch("tu2folder");
        let defaults = default_folders(Platform::Linux, &root, Path::new("/data"));
        let mut settings = Settings::default();
        // Overlay or nothing built yet: update shares the base folder.
        assert_eq!(game_folders(&settings, &defaults).1, root.join("game"));
        // A stale saved update folder without an executable is ignored.
        settings.game_dir_update = root.join("gone").display().to_string();
        assert_eq!(game_folders(&settings, &defaults).1, root.join("game"));
        // A saved folder that still holds an executable is honoured.
        let old = root.join("old-update");
        fs::create_dir_all(&old).unwrap();
        fs::write(old.join("Default.xex"), "x").unwrap();
        settings.game_dir_update = old.display().to_string();
        assert_eq!(game_folders(&settings, &defaults).1, old);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn update_overlay_mounts_its_folder_as_update_and_validates_there() {
        let game = scratch("overlay");
        let overlay = game.join("update");
        fs::create_dir_all(overlay.join("CPKs")).unwrap();
        // Without the overlay executable the folder is a plain staged copy.
        assert_eq!(update_layout(&game).0, game);
        fs::write(overlay.join("Default.xex"), "x").unwrap();
        assert_eq!(update_layout(&game).0, overlay);
        let args = launch_arguments(
            Platform::Linux,
            &build(true, false),
            &game,
            Path::new("/s"),
            &options(),
            -1,
        )
        .unwrap();
        assert!(args.contains(&format!("--update_data_root={}", overlay.display())));
        assert!(validate_game_dir(&build(true, false), &game)
            .unwrap_err()
            .contains("not the verified"));
        // One folder for both versions builds update as an overlay: no second folder is passed.
        let request = BuildRequest {
            iso: String::new(),
            title_update: String::new(),
            variants: vec!["update".into()],
            cmake: String::new(),
            download_sdk: false,
            download_sources: false,
        };
        let args = build_client_arguments(Platform::Linux, Path::new("/r"), &request, &game, &game).unwrap();
        assert!(!args.iter().any(|a| a.starts_with("--game-dir-update")));
        fs::remove_dir_all(game).unwrap();
    }

    #[test]
    fn update_uses_separate_folders_and_settings_override_defaults() {
        let defaults = default_folders(Platform::Linux, Path::new("/repo"), Path::new("/data"));
        let mut settings = Settings::default();
        let (game, user) = folders_for(&build(true, true), &settings, &defaults);
        assert_eq!(
            (game.as_path(), user.as_path()),
            (
                Path::new("/repo/game"),
                Path::new("/data/souls-of-the-reaper-update")
            )
        );
        settings.game_dir = " /custom ".into();
        let (game, user) = folders_for(&build(false, false), &settings, &defaults);
        assert_eq!(
            (game.as_path(), user.as_path()),
            (Path::new("/custom"), Path::new("/data/souls-of-the-reaper"))
        );
        let windows = default_folders(Platform::Windows, Path::new("/r"), Path::new("/Documents"));
        assert!(
            windows.user_data_root.ends_with("diablo3")
                && windows.user_data_root_update.ends_with("diablo3-update")
        );
    }
}
