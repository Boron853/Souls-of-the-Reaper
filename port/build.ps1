# build.ps1 - Configure and build the Diablo III port (recompiled code + ReXGlue runtime).
#
# Toolchain:
#   - Clang/Clang++ 22.1.7  : C:\Program Files\LLVM\bin   (target x86_64-pc-windows-msvc)
#   - Ninja + CMake 3.31    : bundled with Visual Studio 2022 Community
#   - MSVC 14.44 + WinSDK   : headers/runtime used by clang on Windows
#
# SDK modes:
#   (default) SOURCE      : builds the ReXGlue runtime from ..\rexglue-sdk.
#                           Full PDBs/symbols for the runtime -> debugging and patching.
#                           Slower on the first build; incremental afterwards.
#   -Precompiled          : uses the prebuilt binary in ..\sdk-bin\win-amd64.
#                           Fast, no runtime symbols.
#
# Usage:  pwsh -File build.ps1 [-Config Debug|Release|RelWithDebInfo] [-Precompiled] [-Clean]
param(
    [ValidateSet('Debug','Release','RelWithDebInfo')]
    [string]$Config = 'Debug',
    [switch]$Precompiled,   # use sdk-bin prebuilt instead of building from source
    [switch]$Clean          # wipe the build directory (force a clean reconfigure)
)
# Don't use 'Stop': cmake/clang write warnings to stderr and 'Stop' would abort.
# Real failures are caught by $LASTEXITCODE checks below.
$ErrorActionPreference = 'Continue'

$llvm   = 'C:\Program Files\LLVM\bin'
$vsCmake = 'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin'
$vsNinja = 'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja'
$sdkBin    = (Resolve-Path "$PSScriptRoot\..\sdk-bin\win-amd64").Path
$sdkSource = (Resolve-Path "$PSScriptRoot\..\rexglue-sdk").Path

$env:PATH = "$llvm;$vsCmake;$vsNinja;$env:PATH"

$presetMap = @{ 'Debug' = 'win-amd64-debug'; 'Release' = 'win-amd64-release'; 'RelWithDebInfo' = 'win-amd64-relwithdebinfo' }
$preset = $presetMap[$Config]
$buildDir = "$PSScriptRoot\out\build\$preset"

# If the SDK mode changes from the previous build, a clean reconfigure is required
# (find_package and add_subdirectory are not interchangeable in a warm cache).
$wantMode = if ($Precompiled) { 'precompiled' } else { 'source' }
$cacheFile = "$buildDir\CMakeCache.txt"
$prevMode = $null
if (Test-Path $cacheFile) {
    if (Select-String -Path $cacheFile -Pattern '^REXSDK_DIR:.+=.+\S' -Quiet) { $prevMode = 'source' } else { $prevMode = 'precompiled' }
}
if ($Clean -or ($prevMode -and $prevMode -ne $wantMode)) {
    if (Test-Path $buildDir) {
        Write-Host "==> Cleaning build dir (mode $prevMode -> $wantMode)" -ForegroundColor Yellow
        Remove-Item -Recurse -Force $buildDir
    }
}

if ($Precompiled) {
    Write-Host "==> Configuring ($preset) | PREBUILT SDK: $sdkBin" -ForegroundColor Cyan
    cmake --preset $preset -D "CMAKE_PREFIX_PATH=$sdkBin"
} else {
    Write-Host "==> Configuring ($preset) | SDK FROM SOURCE: $sdkSource" -ForegroundColor Cyan
    # REXGLUE_ENABLE_TRACY=OFF: Tracy's rpmalloc maps a 4MB host span per thread and
    # never returns it to the OS when the thread exits. With ~64 XAM tasks/sec (each
    # an ephemeral XThread) this leaks ~256MB/sec -> OOM in ~3 min.
    cmake --preset $preset -D "REXSDK_DIR=$sdkSource" -D "REXGLUE_ENABLE_TRACY=OFF"
}
if ($LASTEXITCODE -ne 0) { throw "cmake configure failed ($LASTEXITCODE)" }

Write-Host "==> Building target diablo3 ($preset)" -ForegroundColor Cyan
cmake --build $buildDir --target diablo3
if ($LASTEXITCODE -ne 0) { throw "build failed ($LASTEXITCODE)" }

Write-Host "==> OK. Binary at out\build\$preset\diablo3.exe" -ForegroundColor Green
