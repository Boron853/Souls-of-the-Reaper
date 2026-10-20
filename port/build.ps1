# build.ps1 - Build the Diablo III port against the pinned ReXGlue SDK (0.10.0).
#
# Toolchain:
#   - LLVM Clang 22+        : C:\Program Files\LLVM\bin   (target x86_64-pc-windows-msvc)
#   - Ninja + CMake 3.25+   : bundled with Visual Studio 2022 Community
#   - MSVC 14.44 + WinSDK   : headers/runtime used by clang on Windows
#   - Git                   : to clone the SDK
#
# Steps (each can be skipped once done):
#   1. -BuildSdk   : clone the SDK at the commit in rexglue.lock.json into ..\rexglue-sdk, apply
#                    the patches in ..\patches, then build and install it (~10 min the first time).
#   2. codegen     : check the disc's Default.xex, recompile it into generated\default (~12 min)
#                    and re-apply the hand patches (apply_generated_patches.ps1).
#                    -SkipCodegen reuses the generated sources.
#   3. game        : build diablo3.exe into out\build\win-amd64-relwithdebinfo.
#
# Usage:  pwsh -File build.ps1 [-BuildSdk] [-GameDir ..\game] [-SkipCodegen] [-Clean] [-Jobs N]
param(
    [switch]$BuildSdk,      # clone (if needed), patch, build and install the pinned SDK
    [string]$GameDir = "$PSScriptRoot\..\game",  # extracted disc: Default.xex + CPKs\
    [switch]$SkipCodegen,   # reuse generated\default from an earlier run
    [switch]$Clean,         # wipe the game build directory (force a clean reconfigure)
    [int]$Jobs = [Environment]::ProcessorCount
)
# Don't use 'Stop': cmake/clang write warnings to stderr and 'Stop' would abort.
# Real failures are caught by $LASTEXITCODE checks below.
$ErrorActionPreference = 'Continue'

$root       = (Resolve-Path "$PSScriptRoot\..").Path
$lock       = Get-Content -Raw -LiteralPath "$PSScriptRoot\rexglue.lock.json" | ConvertFrom-Json
$sdkSource  = Join-Path $root 'rexglue-sdk'
$sdkBuild   = Join-Path $sdkSource 'out\build\win-amd64'
$sdkInstall = Join-Path $sdkSource 'out\install\win-amd64'
$codegenExe = Join-Path $sdkSource 'out\win-amd64\RelWithDebInfo\rexgluerd.exe'
$buildDir   = "$PSScriptRoot\out\build\win-amd64-relwithdebinfo"
# SHA-256 of the unmodified USA Ultimate Evil Edition Default.xex. The codegen
# config (config\*.toml) and the hand patches use this executable's addresses.
$discSha256 = 'cc918a70940517f974d0fd60d4936c8236e8dc21130cf4a8b8ae915451c289ef'

# Applied in this order on top of the pinned SDK. patches\systemlink holds whole
# new source files (it mirrors the SDK tree) and is copied in first, because
# rexglue-systemlink-net.patch refers to them.
$sdkPatches = @(
    'rexglue-registration.patch',     # codegen: register the leaf functions in config\
    'rexglue-object-reference.patch', # kernel: ObReferenceObject keeps objects alive
    'rexglue-keyboard.patch',         # keyboard layout and menu keystrokes
    'rexglue-username.patch',         # player name from SOTR_USERNAME
    'rexglue-systemlink-net.patch',   # System Link (LAN play)
    'rexglue-sdk.patch'               # the port's Windows/D3D12 runtime changes
)

function Invoke-Step([string]$What, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$What failed ($LASTEXITCODE)" }
}

# Use the usual install locations when the tools aren't already on PATH.
$vsIde = 'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake'
foreach ($tool in @(
        @{ exe = 'clang';  dir = 'C:\Program Files\LLVM\bin' },
        @{ exe = 'cmake';  dir = "$vsIde\CMake\bin" },
        @{ exe = 'ninja';  dir = "$vsIde\Ninja" })) {
    if (-not (Get-Command $tool.exe -ErrorAction SilentlyContinue) -and (Test-Path $tool.dir)) {
        $env:PATH = "$($tool.dir);$env:PATH"
    }
}
$missing = @('git', 'clang', 'clang++', 'cmake', 'ninja') | Where-Object { -not (Get-Command $_ -ErrorAction SilentlyContinue) }
if ($missing) {
    throw "Not found on PATH: $($missing -join ', '). Install Visual Studio 2022 with the C++ and CMake workloads, LLVM Clang 22+ and Git."
}

# Applies $sdkPatches to the SDK checkout. Some patches change the same lines,
# so "already applied" can't be checked patch by patch: a stamp file records the
# hash of the patch set last applied. When the patches changed since then, the
# SDK's tracked files are restored to the pinned commit first - rexglue-sdk\ is
# managed by this script, so keep your own SDK experiments elsewhere.
function Apply-SdkPatches {
    $paths = @($sdkPatches | ForEach-Object { Join-Path $root "patches\$_" }) +
        @(Get-ChildItem -LiteralPath "$root\patches\systemlink" -Recurse -File | Sort-Object FullName | ForEach-Object FullName)
    $hashes = ($paths | ForEach-Object { (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash }) -join "`n"
    $stamp = Join-Path $sdkSource '.sotr-patches'
    if ((Test-Path -LiteralPath $stamp) -and (Get-Content -Raw -LiteralPath $stamp).Trim() -eq $hashes) {
        Write-Host "    patches already applied" -ForegroundColor DarkGray
        return
    }
    if (git -C $sdkSource status --porcelain --untracked-files=no) {
        Write-Host "    restoring the SDK's files before applying the current patches" -ForegroundColor Yellow
        Invoke-Step 'git checkout' { git -C $sdkSource checkout -- . }
    }
    Remove-Item -LiteralPath $stamp -ErrorAction SilentlyContinue
    Copy-Item -Path "$root\patches\systemlink\*" -Destination $sdkSource -Recurse -Force
    foreach ($patch in $sdkPatches) {
        Invoke-Step "Applying $patch" { git -C $sdkSource apply (Join-Path $root "patches\$patch") }
        Write-Host "    $patch`: applied" -ForegroundColor Green
    }
    Set-Content -LiteralPath $stamp -Value $hashes -Encoding ascii
}

if ($BuildSdk) {
    if (-not (Test-Path $sdkSource)) {
        Write-Host "==> Cloning ReXGlue SDK $($lock.commit)" -ForegroundColor Cyan
        Invoke-Step 'git clone' { git -c core.autocrlf=false clone --no-checkout $lock.repository $sdkSource }
        Invoke-Step 'git config' { git -C $sdkSource config core.autocrlf false }
        Invoke-Step 'git checkout' { git -C $sdkSource checkout --detach $lock.commit }
    }
    $actual = (git -C $sdkSource rev-parse HEAD).Trim()
    if ($actual -ne $lock.commit) {
        throw "rexglue-sdk is at $actual; expected $($lock.commit) (see rexglue.lock.json)"
    }
    Invoke-Step 'git submodule update' { git -C $sdkSource submodule update --init --recursive }

    # Git checks symlinks out as small text files on Windows; replace them with
    # copies of their targets so libmspack's headers resolve.
    $mspack = Join-Path $sdkSource 'thirdparty\libmspack'
    foreach ($line in (git -C $mspack ls-files -s)) {
        $mode, $null, $null, $name = $line -split '\s+', 4
        if ($mode -ne '120000') { continue }
        $link = Join-Path $mspack $name
        $target = Join-Path (Split-Path -Parent $link) (Get-Content -Raw -LiteralPath $link).Trim()
        if ((Test-Path -LiteralPath $target -PathType Leaf) -and (Get-Item -LiteralPath $link).Length -lt 260) {
            Copy-Item -LiteralPath $target -Destination $link -Force
        }
    }

    Write-Host "==> Patching the SDK" -ForegroundColor Cyan
    Apply-SdkPatches
    Copy-Item -LiteralPath "$root\patches\d3d_screenshot.cpp" -Destination "$sdkSource\src\graphics\d3d12\" -Force

    Write-Host "==> Building the SDK" -ForegroundColor Cyan
    Push-Location $sdkSource
    try {
        # REXGLUE_ENABLE_TRACY=OFF: Tracy's rpmalloc maps a 4MB host span per thread and
        # never returns it to the OS when the thread exits. With ~64 XAM tasks/sec (each
        # an ephemeral XThread) this leaks ~256MB/sec -> OOM in ~3 min.
        Invoke-Step 'SDK configure' { cmake --preset win-amd64 -DREXGLUE_ENABLE_TRACY=OFF -DREXGLUE_BUILD_TESTS=OFF -DREXGLUE_USE_D3D12=ON }
    } finally { Pop-Location }
    Invoke-Step 'SDK build' { cmake --build $sdkBuild --config RelWithDebInfo --parallel $Jobs }
    Invoke-Step 'SDK install' { cmake --install $sdkBuild --config RelWithDebInfo --prefix $sdkInstall }
}

if (-not (Test-Path "$sdkInstall\lib\cmake\rexglue") -or -not (Test-Path $codegenExe)) {
    throw "The SDK isn't built yet; run build.ps1 -BuildSdk"
}

if (-not $SkipCodegen) {
    $GameDir = (Resolve-Path $GameDir -ErrorAction SilentlyContinue).Path
    $xex = if ($GameDir) { Join-Path $GameDir 'Default.xex' }
    if (-not $xex -or -not (Test-Path -LiteralPath $xex)) {
        throw "Default.xex not found in the game folder; pass -GameDir with the extracted disc"
    }
    if ((Get-FileHash -LiteralPath $xex -Algorithm SHA256).Hash -ne $discSha256) {
        throw "$xex is not the unmodified USA Ultimate Evil Edition executable (SHA-256 mismatch)"
    }

    # Codegen resolves paths relative to the manifest, so write a copy that
    # points at the chosen game folder.
    $gamePath = $GameDir -replace '\\', '/'
    $manifest = Get-Content -Raw -LiteralPath "$PSScriptRoot\diablo3_manifest.toml"
    $manifest = $manifest.Replace('"../game/Default.xex"', (ConvertTo-Json "$gamePath/Default.xex"))
    $manifest = $manifest.Replace('"../game"', (ConvertTo-Json $gamePath))
    $localManifest = "$PSScriptRoot\local_manifest.toml"
    # WriteAllText writes UTF-8 without a byte order mark.
    [System.IO.File]::WriteAllText($localManifest, $manifest)

    Write-Host "==> Codegen (generated\default)" -ForegroundColor Cyan
    Invoke-Step 'codegen' { & $codegenExe codegen $localManifest }
    # Throws if a hand patch can't be applied.
    & "$PSScriptRoot\apply_generated_patches.ps1"
}

if ($Clean -and (Test-Path $buildDir)) {
    Write-Host "==> Cleaning $buildDir" -ForegroundColor Yellow
    Remove-Item -Recurse -Force $buildDir
}

Write-Host "==> Configuring the game | SDK: $sdkInstall" -ForegroundColor Cyan
Invoke-Step 'cmake configure' {
    cmake -S $PSScriptRoot -B $buildDir -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo `
        -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ `
        -DCMAKE_C_FLAGS=-march=x86-64-v2 -DCMAKE_CXX_FLAGS=-march=x86-64-v2 `
        "-DCMAKE_PREFIX_PATH=$sdkInstall"
}

Write-Host "==> Building target diablo3" -ForegroundColor Cyan
Invoke-Step 'build' { cmake --build $buildDir --target diablo3 --parallel $Jobs }

Write-Host "==> OK. Binary at out\build\win-amd64-relwithdebinfo\diablo3.exe" -ForegroundColor Green
