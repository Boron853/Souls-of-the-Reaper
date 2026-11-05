//! Detects the tools the Build panel needs before scripts/build_client.py runs,
//! so a machine without Python or a compiler gets download links instead of a
//! failed build. Kept free of Tauri like launch.rs. Windows has no Python by
//! default, so none of this can live in the build scripts.

use crate::launch::Platform;
use serde::Serialize;
use std::{
    ffi::OsString,
    fs,
    path::{Path, PathBuf},
    process::{Command, Stdio},
};

const MIN_CMAKE: (u32, u32) = (3, 25);
/// Oldest Clang the SDK and port build with (docs/building-the-game.md).
const MIN_CLANG_LINUX: u32 = 18;
const MIN_CLANG_WINDOWS: u32 = 22;
/// Free space a first build wants: SDK, two variants and codegen, with headroom
/// (scripts/build_client.py computes the exact need and stops if it is short).
const WARN_FREE_BYTES: u64 = 15 << 30;
const VS_COMPONENT: &str = "Microsoft.VisualStudio.Component.VC.Tools.x86.x64";
/// Set on every Python child: on Windows it otherwise writes piped output in
/// the ANSI code page, and the launcher reads UTF-8 (paths with accents).
pub const PYTHON_UTF8: [(&str, &str); 2] = [("PYTHONUTF8", "1"), ("PYTHONIOENCODING", "utf-8")];

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Tool {
    pub id: &'static str,
    pub label: String,
    pub found: bool,
    pub path: String,
    /// Where to download it; empty when the system package manager is the way.
    pub url: &'static str,
    pub note: String,
    /// winget package that installs it (Windows); empty when there is none.
    pub winget: &'static str,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Sdk {
    /// Built from the pinned commit and patches, so the build can use it.
    pub installed: bool,
    /// Built, but from another commit or patch set; a rebuild is needed.
    pub stale: bool,
    pub repository: String,
    pub commit: String,
}

/// Repository sources a launcher outside a checkout still has to download.
#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Sources {
    pub repository: String,
    pub commit: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ToolReport {
    pub tools: Vec<Tool>,
    pub sdk: Sdk,
    /// Set by the host when the sources are missing; detect() leaves it empty.
    pub sources: Option<Sources>,
    /// Problems that do not block Build but may make it fail later.
    pub warnings: Vec<String>,
    /// Every required tool was found.
    pub ready: bool,
    /// winget can install the missing tools (Windows 10 1809+ with App Installer).
    pub winget: bool,
    /// Folders of tools found off PATH (Visual Studio's CMake, LLVM); the build
    /// script's PATH needs them too.
    #[serde(skip)]
    pub path_dirs: Vec<PathBuf>,
}

fn exe(name: &str, platform: Platform) -> String {
    match platform {
        Platform::Windows => format!("{name}.exe"),
        Platform::Linux => name.to_string(),
    }
}

/// First `name` found in `dirs`.
pub fn find_program(name: &str, platform: Platform, dirs: &[PathBuf]) -> Option<PathBuf> {
    let file = exe(name, platform);
    dirs.iter().map(|d| d.join(&file)).find(|p| p.is_file())
}

/// Stdout of `program args`, or None when it cannot run or fails (this also
/// rejects the Microsoft Store `python.exe` stub on Windows). Python and the
/// `py` launcher are run through here, so the UTF-8 settings go on every call.
fn output_of(program: &Path, args: &[&str]) -> Option<String> {
    let mut command = Command::new(program);
    command
        .args(args)
        .envs(PYTHON_UTF8)
        .stdin(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let output = command.output().ok()?;
    output
        .status
        .success()
        .then(|| String::from_utf8_lossy(&output.stdout).into_owned())
}

/// "cmake version 3.31.6" -> (3, 31).
pub fn parse_version(text: &str) -> Option<(u32, u32)> {
    let digits = text.split(|c: char| !(c.is_ascii_digit() || c == '.'));
    digits.filter(|w| w.contains('.')).find_map(|word| {
        let mut parts = word.split('.');
        Some((parts.next()?.parse().ok()?, parts.next()?.parse().ok()?))
    })
}

/// Python 3: the first interpreter in `dirs` that runs and reports 3.x (the
/// Microsoft Store `python.exe` stub on Windows does not), else on Windows the
/// interpreter the `py` launcher picks, which needs no PATH entry.
fn find_python(platform: Platform, dirs: &[PathBuf]) -> Option<PathBuf> {
    let is_python3 = |p: &Path| {
        output_of(p, &["--version"])
            .and_then(|v| parse_version(&v))
            .is_some_and(|v| v.0 >= 3)
    };
    let name = exe(if platform == Platform::Windows { "python" } else { "python3" }, platform);
    let on_path = dirs.iter().map(|d| d.join(&name)).find(|p| p.is_file() && is_python3(p));
    on_path.or_else(|| {
        let py = find_program("py", platform, dirs).filter(|_| platform == Platform::Windows)?;
        let found = output_of(&py, &["-3", "-c", "import sys; print(sys.executable)"])?;
        Some(PathBuf::from(found.trim())).filter(|p| p.is_file() && is_python3(p))
    })
}

/// Visual Studio install that has the C++ x64 tools, via vswhere.
fn visual_studio() -> Option<PathBuf> {
    let files = std::env::var_os("ProgramFiles(x86)").map(PathBuf::from)?;
    let vswhere = files.join("Microsoft Visual Studio/Installer/vswhere.exe");
    let found = output_of(
        &vswhere,
        &["-latest", "-products", "*", "-requires", VS_COMPONENT, "-property", "installationPath"],
    )?;
    let path = PathBuf::from(found.trim());
    (!found.trim().is_empty() && path.is_dir()).then_some(path)
}

fn tool(id: &'static str, label: &str, path: Option<&Path>, url: &'static str, note: &str) -> Tool {
    Tool {
        id,
        label: label.into(),
        found: path.is_some(),
        path: path.map(|p| p.display().to_string()).unwrap_or_default(),
        url,
        note: note.into(),
        winget: "",
    }
}

/// Visual Studio Build Tools with the C++ workload; --includeRecommended adds the
/// Windows SDK. --passive shows the Visual Studio installer's progress window.
const VS_BUILD_TOOLS_OVERRIDE: &str =
    "--wait --passive --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended";
/// The Python installer leaves PATH alone unless asked; per-user needs no admin.
const PYTHON_OVERRIDE: &str = "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1";
/// CMake 4 rejects projects that ask for a minimum below 3.5, which older
/// third-party code in the SDK may do; the builds so far used 3.31.
const CMAKE_VERSION: &str = "3.31.8";

/// winget package for each build tool.
pub fn winget_package(id: &str) -> &'static str {
    match id {
        "python" => "Python.Python.3.13",
        "git" => "Git.Git",
        "msvc" => "Microsoft.VisualStudio.2022.BuildTools",
        "clang" => "LLVM.LLVM",
        "cmake" => "Kitware.CMake",
        "ninja" => "Ninja-build.Ninja",
        _ => "",
    }
}

/// Arguments for `winget` to install `package` without questions. Only used
/// after the user pressed the Build panel's install button, which says that it
/// accepts the packages' license agreements.
pub fn winget_arguments(package: &str) -> Vec<String> {
    let mut args: Vec<String> = [
        "install",
        "--id",
        package,
        "--exact",
        "--source",
        "winget",
        "--silent",
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--disable-interactivity",
    ]
    .map(String::from)
    .into();
    let installer = match package {
        "Microsoft.VisualStudio.2022.BuildTools" => Some(VS_BUILD_TOOLS_OVERRIDE),
        "Python.Python.3.13" => Some(PYTHON_OVERRIDE),
        _ => None,
    };
    if let Some(value) = installer {
        args.extend(["--override".into(), value.into()]);
    }
    if package == "Kitware.CMake" {
        args.extend(["--version".into(), CMAKE_VERSION.into()]);
    }
    args
}

/// winget is installed and runs (it is an app alias, so a file check is not enough).
fn winget_available() -> bool {
    output_of(Path::new("winget"), &["--version"]).is_some()
}

/// Missing tools in the order to install them: Visual Studio last, since it is
/// by far the largest.
pub fn install_order(report: &ToolReport) -> Vec<&Tool> {
    let mut missing: Vec<&Tool> = report.tools.iter().filter(|t| !t.found && !t.winget.is_empty()).collect();
    missing.sort_by_key(|t| t.id == "msvc");
    missing
}

/// One line of winget output for the log: progress redraws with carriage
/// returns, so only the last state of a line is kept, and spinner frames and
/// progress bars are dropped.
pub fn clean_winget_line(line: &str) -> Option<String> {
    let last = line.rsplit('\r').map(str::trim).find(|s| !s.is_empty())?;
    let noise = |c: char| c.is_whitespace() || "-\\|/\u{2588}\u{2592}".contains(c);
    // Bars end in a size or percentage, e.g. "███▒▒▒  12.0 MB / 40.0 MB".
    let bar = last.starts_with(['\u{2588}', '\u{2592}']);
    (last.chars().any(|c| !noise(c)) && !bar).then(|| last.to_string())
}

/// Folders in the user and machine PATH as saved in the registry. Installers
/// change those, not the PATH this process started with, so tools installed
/// while the launcher is open are only found this way.
#[cfg(windows)]
fn registry_path() -> Vec<PathBuf> {
    let keys = [r"HKCU\Environment", r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment"];
    keys.iter()
        .filter_map(|key| output_of(Path::new("reg"), &["query", key, "/v", "Path"]))
        .filter_map(|text| parse_reg_value(&text))
        .flat_map(|value| std::env::split_paths(&expand_env(&value)).collect::<Vec<_>>())
        .filter(|d| !d.as_os_str().is_empty())
        .collect()
}

#[cfg(not(windows))]
fn registry_path() -> Vec<PathBuf> {
    Vec::new()
}

/// The data of a `reg query /v` line: "    Path    REG_EXPAND_SZ    C:\a;%X%".
fn parse_reg_value(text: &str) -> Option<String> {
    text.lines().find_map(|line| {
        let (_, rest) = line.split_once("REG_EXPAND_SZ").or_else(|| line.split_once("REG_SZ"))?;
        Some(rest.trim().to_string())
    })
}

/// Replaces %NAME% with the environment variable; unknown names stay as written.
fn expand_env(text: &str) -> String {
    let mut out = String::new();
    let mut rest = text;
    while let Some(start) = rest.find('%') {
        out.push_str(&rest[..start]);
        let after = &rest[start + 1..];
        let Some(end) = after.find('%') else {
            out.push_str(&rest[start..]);
            return out;
        };
        let name = &after[..end];
        match std::env::var(name).ok().filter(|_| !name.is_empty()) {
            Some(value) => out.push_str(&value),
            None => out.push_str(&format!("%{name}%")),
        }
        rest = &after[end + 1..];
    }
    out.push_str(rest);
    out
}

fn package_hint(packages: &str) -> String {
    format!("Install it with your package manager (for example: {packages}).")
}

/// Status of every tool a build needs. `cmake_choice` is the Build panel's
/// CMake field (blank = look it up).
pub fn detect(platform: Platform, repo: &Path, cmake_choice: &str) -> ToolReport {
    // The PATH the build script inherits, then the registry's (tools installed
    // since the launcher started).
    let inherited: Vec<PathBuf> = std::env::var_os("PATH")
        .map(|p| std::env::split_paths(&p).collect())
        .unwrap_or_default();
    let mut dirs = inherited.clone();
    if platform == Platform::Windows {
        for dir in registry_path() {
            if !dirs.contains(&dir) {
                dirs.push(dir);
            }
        }
    }
    let mut extra = Vec::new();
    let studio = (platform == Platform::Windows).then(visual_studio).flatten();
    if platform == Platform::Windows {
        let program_files = std::env::var_os("ProgramFiles")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from(r"C:\Program Files"));
        extra.push(program_files.join("LLVM/bin"));
        // Where the winget packages install when they leave PATH alone.
        extra.push(program_files.join("CMake/bin"));
        extra.push(program_files.join("Git/cmd"));
        if let Some(local) = std::env::var_os("LOCALAPPDATA") {
            extra.push(PathBuf::from(local).join("Microsoft/WinGet/Links"));
        }
        let mut roots = vec![program_files.join("Microsoft Visual Studio/2022/Community")];
        roots.extend(studio.clone());
        for root in roots {
            let cmake_dir = root.join("Common7/IDE/CommonExtensions/Microsoft/CMake");
            extra.push(cmake_dir.join("CMake/bin"));
            extra.push(cmake_dir.join("Ninja"));
        }
    }
    let lookup = |name: &str| {
        find_program(name, platform, &dirs).or_else(|| find_program(name, platform, &extra))
    };

    let python = find_python(platform, &dirs);
    let git = lookup("git");
    let min_clang = if platform == Platform::Windows { MIN_CLANG_WINDOWS } else { MIN_CLANG_LINUX };
    let clang_found = lookup("clang").zip(lookup("clang++")).map(|(_, plus)| plus);
    let clang_version = clang_found
        .as_deref()
        .and_then(|p| output_of(p, &["--version"]))
        .and_then(|v| parse_version(&v));
    // A clang whose version cannot be read is let through; the build reports it.
    let clang = clang_found.filter(|_| clang_version.is_none_or(|(major, _)| major >= min_clang));
    let cmake = match cmake_choice.trim() {
        "" => lookup("cmake"),
        chosen => Some(PathBuf::from(chosen)).filter(|p| p.is_file()),
    };
    let cmake_ok = cmake
        .as_deref()
        .filter(|p| output_of(p, &["--version"]).and_then(|v| parse_version(&v)).is_some_and(|v| v >= MIN_CMAKE));
    let ninja = lookup("ninja");

    let linux = platform == Platform::Linux;
    let mut tools = vec![
        tool(
            "python",
            "Python 3",
            python.as_deref(),
            "https://www.python.org/downloads/",
            if linux {
                "Runs the build scripts."
            } else {
                "Runs the build scripts. Tick 'Add python.exe to PATH' in the installer."
            },
        ),
        tool(
            "git",
            "Git",
            git.as_deref(),
            "https://git-scm.com/downloads",
            "Fetches the ReXGlue SDK and the update patch tool.",
        ),
    ];
    if platform == Platform::Windows {
        tools.push(tool(
            "msvc",
            "Visual Studio 2022 C++ tools",
            studio.as_deref(),
            "https://visualstudio.microsoft.com/downloads/",
            "Free Build Tools or Community edition with the 'Desktop development with C++' workload.",
        ));
    }
    tools.push(tool(
        "clang",
        if linux { "Clang 18+" } else { "LLVM Clang 22+" },
        clang.as_deref(),
        if linux { "" } else { "https://github.com/llvm/llvm-project/releases/latest" },
        &match (clang_version, clang.is_some()) {
            (Some((major, _)), false) => format!("Found Clang {major}, which is older than {min_clang}."),
            _ if linux => package_hint("apt install clang, pacman -S clang"),
            _ => "Installer: LLVM-<version>-win64.exe.".into(),
        },
    ));
    let cmake_note = match (&cmake, &cmake_ok) {
        (Some(_), None) => "Found, but older than CMake 3.25.".to_string(),
        _ if linux => package_hint("apt install cmake, pacman -S cmake"),
        _ => "Also included with the Visual Studio 'C++ CMake tools' component.".into(),
    };
    tools.push(tool(
        "cmake",
        "CMake 3.25+",
        cmake_ok,
        "https://cmake.org/download/",
        &cmake_note,
    ));
    tools.push(tool(
        "ninja",
        "Ninja",
        ninja.as_deref(),
        "https://github.com/ninja-build/ninja/releases/latest",
        &if linux { package_hint("apt install ninja-build, pacman -S ninja") } else { "Also included with the Visual Studio 'C++ CMake tools' component.".into() },
    ));

    if platform == Platform::Windows {
        for t in &mut tools {
            t.winget = winget_package(t.id);
        }
    }

    // Only folders the inherited PATH lacks need adding for the build script,
    // which runs git and the compilers by name.
    let mut path_dirs = Vec::new();
    for found in [&python, &git, &clang, &cmake, &ninja].into_iter().flatten() {
        if let Some(dir) = found.parent() {
            if !inherited.iter().any(|d| d == dir) && !path_dirs.iter().any(|d: &PathBuf| d == dir) {
                path_dirs.push(dir.to_path_buf());
            }
        }
    }

    let mut warnings = Vec::new();
    if linux {
        warnings.extend(linux_warnings(Path::new("/usr/share/vulkan/icd.d"), Path::new("/etc/vulkan/icd.d"), &dirs));
    }
    if let Some(free) = free_bytes(repo).filter(|free| *free < WARN_FREE_BYTES) {
        warnings.push(format!(
            "Only {:.1} GiB is free where the build runs; a first build wants about 15 GiB.",
            free as f64 / (1u64 << 30) as f64
        ));
    }

    let ready = tools.iter().all(|t| t.found);
    ToolReport {
        warnings,
        ready,
        winget: platform == Platform::Windows && !ready && winget_available(),
        tools,
        sdk: python
            .as_deref()
            .and_then(|p| sdk_status_from_script(p, repo))
            .unwrap_or_else(|| sdk_status(platform, repo)),
        sources: None,
        path_dirs,
    }
}

/// Stops `pid` and the processes it started (CMake and the compilers under the
/// build script, git's transport helpers under git): its process group on Unix,
/// where the child must lead one (`process_group(0)`), its process tree on Windows.
pub fn kill_tree(pid: u32) {
    #[cfg(unix)]
    unsafe {
        libc::kill(-(pid as i32), libc::SIGTERM);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        let _ = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .creation_flags(0x0800_0000) // CREATE_NO_WINDOW
            .status();
    }
}

/// `PATH` for the build script: `extra` ahead of the inherited one.
pub fn path_with(extra: &[PathBuf]) -> Option<OsString> {
    if extra.is_empty() {
        return None;
    }
    let inherited = std::env::var_os("PATH").unwrap_or_default();
    let all = extra.iter().cloned().chain(std::env::split_paths(&inherited));
    std::env::join_paths(all).ok()
}

/// Linux packages the tool list cannot see. SDL builds for X11 or Wayland and
/// needs their development files; playing needs a Vulkan driver (an ICD file).
fn linux_warnings(icd_dir: &Path, etc_icd_dir: &Path, path: &[PathBuf]) -> Vec<String> {
    let mut warnings = Vec::new();
    let has_icd = |dir: &Path| fs::read_dir(dir).is_ok_and(|mut d| d.next().is_some());
    if !has_icd(icd_dir) && !has_icd(etc_icd_dir) {
        warnings.push("No Vulkan driver was found (no files in /usr/share/vulkan/icd.d). The game needs one to run.".into());
    }
    let pkg_config = find_program("pkg-config", Platform::Linux, path);
    let exists = |module: &str| {
        pkg_config.as_deref().is_some_and(|p| {
            Command::new(p)
                .args(["--exists", module])
                .stdin(Stdio::null())
                .stderr(Stdio::null())
                .status()
                .is_ok_and(|s| s.success())
        })
    };
    if !exists("x11") && !exists("wayland-client") {
        warnings.push(
            "X11 or Wayland development packages were not found (pkg-config x11 / wayland-client); \
             building the SDK may fail. See docs/building-the-game.md."
                .into(),
        );
    }
    warnings
}

/// Free bytes on the volume holding `path` (or its nearest existing parent).
#[cfg(unix)]
fn free_bytes(path: &Path) -> Option<u64> {
    use std::os::unix::ffi::OsStrExt;
    let existing = path.ancestors().find(|p| p.exists())?;
    let c_path = std::ffi::CString::new(existing.as_os_str().as_bytes()).ok()?;
    let mut stat: libc::statvfs = unsafe { std::mem::zeroed() };
    // SAFETY: c_path is a valid NUL-terminated string and stat a valid out-pointer.
    (unsafe { libc::statvfs(c_path.as_ptr(), &mut stat) } == 0)
        .then(|| stat.f_bavail as u64 * stat.f_frsize as u64)
}

#[cfg(windows)]
fn free_bytes(path: &Path) -> Option<u64> {
    use std::os::windows::ffi::OsStrExt;
    #[link(name = "kernel32")]
    extern "system" {
        fn GetDiskFreeSpaceExW(dir: *const u16, free_to_caller: *mut u64, total: *mut u64, total_free: *mut u64) -> i32;
    }
    let existing = path.ancestors().find(|p| p.exists())?;
    let wide: Vec<u16> = existing.as_os_str().encode_wide().chain(Some(0)).collect();
    let mut free = 0u64;
    // SAFETY: wide is NUL-terminated and free a valid out-pointer; the others may be null.
    (unsafe { GetDiskFreeSpaceExW(wide.as_ptr(), &mut free, std::ptr::null_mut(), std::ptr::null_mut()) } != 0)
        .then_some(free)
}

/// Asks scripts/build_client.py, which owns the install paths and the stamp of
/// the commit and patches an SDK was built from. None when it cannot be run.
pub fn sdk_status_from_script(python: &Path, repo: &Path) -> Option<Sdk> {
    let script = repo.join("scripts/build_client.py");
    if !script.is_file() {
        return None;
    }
    let mut command = Command::new(python);
    command
        .arg(script)
        .arg("--print-sdk-status")
        .current_dir(repo)
        .envs(PYTHON_UTF8)
        .stdin(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let output = command.output().ok().filter(|o| o.status.success())?;
    parse_sdk_status(&String::from_utf8_lossy(&output.stdout))
}

fn parse_sdk_status(text: &str) -> Option<Sdk> {
    let status: serde_json::Value = serde_json::from_str(text.trim()).ok()?;
    let state = status["state"].as_str()?;
    let text = |key: &str| status[key].as_str().unwrap_or_default().to_string();
    Some(Sdk {
        installed: state == "current",
        stale: state == "stale",
        repository: text("repository"),
        commit: text("commit"),
    })
}

/// Whether the patched SDK is built where scripts/build_client.py looks for it
/// (tools/rexglue-install-* and, on Windows, its codegen tool), and the pinned
/// revision it would fetch otherwise (port/base/rexglue.lock.json).
pub fn sdk_status(platform: Platform, repo: &Path) -> Sdk {
    let lock: serde_json::Value = fs::read(repo.join("port/base/rexglue.lock.json"))
        .ok()
        .and_then(|d| serde_json::from_slice(&d).ok())
        .unwrap_or_default();
    let text = |key: &str| lock[key].as_str().unwrap_or_default().to_string();
    let tools = repo.join("tools");
    let installed = match platform {
        Platform::Windows => {
            tools.join("rexglue-install-win/lib/cmake/rexglue").is_dir()
                && tools.join("rexglue-sdk-win/out/win-amd64/RelWithDebInfo/rexgluerd.exe").is_file()
        }
        Platform::Linux => tools.join("rexglue-install-linux/bin/rexglue").is_file(),
    };
    Sdk {
        installed,
        stale: false,
        repository: text("repository"),
        commit: text("commit"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("sotr-tools-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn parses_tool_versions() {
        assert_eq!(parse_version("cmake version 3.31.6\n\nCMake suite"), Some((3, 31)));
        assert_eq!(parse_version("Python 3.12.1"), Some((3, 12)));
        assert_eq!(parse_version("clang version 22.1.0"), Some((22, 1)));
        assert_eq!(parse_version("no digits"), None);
        assert!((3, 31) >= MIN_CMAKE && (3, 24) < MIN_CMAKE);
    }

    #[test]
    fn finds_programs_with_the_platform_suffix() {
        let dir = scratch("find");
        fs::write(dir.join("ninja"), "").unwrap();
        fs::write(dir.join("cmake.exe"), "").unwrap();
        let dirs = [dir.clone()];
        assert_eq!(find_program("ninja", Platform::Linux, &dirs), Some(dir.join("ninja")));
        assert_eq!(find_program("cmake", Platform::Windows, &dirs), Some(dir.join("cmake.exe")));
        assert_eq!(find_program("cmake", Platform::Linux, &dirs), None);
    }

    #[test]
    fn sdk_status_reads_the_pinned_revision_and_install_state() {
        let repo = scratch("sdk");
        fs::create_dir_all(repo.join("port/base")).unwrap();
        fs::write(
            repo.join("port/base/rexglue.lock.json"),
            r#"{"repository":"https://example.test/sdk.git","commit":"abc123"}"#,
        )
        .unwrap();
        let sdk = sdk_status(Platform::Linux, &repo);
        assert!(!sdk.installed);
        assert_eq!((sdk.repository.as_str(), sdk.commit.as_str()), ("https://example.test/sdk.git", "abc123"));
        fs::create_dir_all(repo.join("tools/rexglue-install-linux/bin")).unwrap();
        fs::write(repo.join("tools/rexglue-install-linux/bin/rexglue"), "").unwrap();
        assert!(sdk_status(Platform::Linux, &repo).installed);
        assert!(!sdk_status(Platform::Windows, &repo).installed);
    }

    #[test]
    fn free_space_is_read_for_missing_folders_too() {
        let dir = scratch("free");
        assert!(free_bytes(&dir.join("not/created/yet")).is_some_and(|b| b > 0));
    }

    #[test]
    fn linux_warnings_flag_a_missing_vulkan_driver() {
        let dir = scratch("icd");
        let none = linux_warnings(&dir.join("a"), &dir.join("b"), &[]);
        assert!(none.iter().any(|w| w.contains("Vulkan driver")));
        fs::write(dir.join("radeon.json"), "{}").unwrap();
        let some = linux_warnings(&dir, &dir.join("b"), &[]);
        assert!(!some.iter().any(|w| w.contains("Vulkan driver")));
        // Without pkg-config the windowing libraries cannot be confirmed.
        assert!(some.iter().any(|w| w.contains("X11 or Wayland")));
    }

    #[test]
    fn script_sdk_status_maps_its_state() {
        let line = r#"{"state": "stale", "repository": "r", "commit": "c"}"#;
        let sdk = parse_sdk_status(line).unwrap();
        assert!(!sdk.installed && sdk.stale);
        assert_eq!((sdk.repository.as_str(), sdk.commit.as_str()), ("r", "c"));
        assert!(parse_sdk_status(r#"{"state": "current"}"#).unwrap().installed);
        assert!(!parse_sdk_status(r#"{"state": "missing"}"#).unwrap().stale);
        assert!(parse_sdk_status("not json").is_none());
    }

    #[test]
    fn report_lists_the_platform_tools_and_links_the_missing_ones() {
        let repo = scratch("report");
        let linux = detect(Platform::Linux, &repo, "/no/such/cmake");
        let ids: Vec<_> = linux.tools.iter().map(|t| t.id).collect();
        assert_eq!(ids, ["python", "git", "clang", "cmake", "ninja"]);
        let cmake = linux.tools.iter().find(|t| t.id == "cmake").unwrap();
        assert!(!cmake.found && !cmake.url.is_empty());
        assert!(!linux.ready);
        let windows = detect(Platform::Windows, &repo, "");
        assert!(windows.tools.iter().any(|t| t.id == "msvc" && t.url.starts_with("https://")));
    }

    #[test]
    fn winget_installs_quietly_with_installer_overrides() {
        let git = winget_arguments("Git.Git");
        assert_eq!(&git[..4], ["install", "--id", "Git.Git", "--exact"]);
        assert!(git.iter().any(|a| a == "--accept-package-agreements"));
        assert!(!git.iter().any(|a| a == "--override"));
        let vs = winget_arguments(winget_package("msvc"));
        let value = &vs[vs.iter().position(|a| a == "--override").unwrap() + 1];
        assert!(value.contains("Microsoft.VisualStudio.Workload.VCTools") && value.contains("--includeRecommended"));
        let python = winget_arguments(winget_package("python"));
        assert!(python.last().unwrap().contains("PrependPath=1"));
        assert!(winget_arguments(winget_package("cmake")).ends_with(&["--version".into(), "3.31.8".into()]));
    }

    #[test]
    fn missing_tools_install_with_visual_studio_last() {
        let repo = scratch("order");
        let mut report = detect(Platform::Windows, &repo, "/no/such/cmake");
        for t in &mut report.tools {
            t.found = !matches!(t.id, "msvc" | "cmake" | "git");
        }
        let ids: Vec<_> = install_order(&report).iter().map(|t| t.id).collect();
        assert_eq!(ids, ["git", "cmake", "msvc"]);
        assert!(detect(Platform::Linux, &repo, "").tools.iter().all(|t| t.winget.is_empty()));
    }

    #[test]
    fn winget_progress_is_reduced_to_readable_lines() {
        let found = "Found Git [Git.Git] Version 2.51.0";
        assert_eq!(clean_winget_line(found).as_deref(), Some(found));
        assert_eq!(clean_winget_line("  -\r  \\\r  |\r  /"), None);
        assert_eq!(clean_winget_line("\u{2588}\u{2588}\u{2592}\u{2592}  1.00 MB / 64.0 MB"), None);
        assert_eq!(clean_winget_line("  -\r  Successfully installed").as_deref(), Some("Successfully installed"));
        assert_eq!(clean_winget_line(""), None);
    }

    #[test]
    fn registry_path_values_are_parsed_and_expanded() {
        let text = "\r\nHKEY_CURRENT_USER\\Environment\r\n    Path    REG_EXPAND_SZ    %SOTR_TEST_HOME%\\bin;C:\\x\r\n\r\n";
        let value = parse_reg_value(text).unwrap();
        assert_eq!(value, r"%SOTR_TEST_HOME%\bin;C:\x");
        std::env::set_var("SOTR_TEST_HOME", r"D:\home");
        assert_eq!(expand_env(&value), r"D:\home\bin;C:\x");
        assert_eq!(expand_env("%SOTR_NOT_SET_ANYWHERE%;50%"), "%SOTR_NOT_SET_ANYWHERE%;50%");
        assert_eq!(parse_reg_value("ERROR: not found"), None);
    }

    #[test]
    fn extra_folders_go_ahead_of_path() {
        assert!(path_with(&[]).is_none());
        let joined = path_with(&[PathBuf::from("/opt/llvm/bin")]).unwrap();
        assert_eq!(std::env::split_paths(&joined).next(), Some(PathBuf::from("/opt/llvm/bin")));
    }
}
