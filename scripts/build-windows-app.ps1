# Build the native Windows TeXada desktop app through Tauri.
# Run this script from a Windows host with Rust, Microsoft C++ Build Tools,
# WebView2 Runtime, and tauri-cli installed.

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$TauriDir = Join-Path $ProjectRoot "tauri-shell\src-tauri"

Write-Host "Building TeXada Windows app..."
Write-Host "   Project root: $ProjectRoot"

if (-not (Test-Path $TauriDir)) {
    throw "Tauri source directory not found: $TauriDir"
}

if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "Rust/Cargo was not found. Install Rust from https://rustup.rs/"
}

$tauriCheck = cargo tauri --version 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "tauri-cli was not found. Install it with: cargo install tauri-cli --version '^2' --locked"
}

Push-Location $TauriDir
try {
    cargo tauri build --bundles nsis
    if ($LASTEXITCODE -ne 0) {
        throw "cargo tauri build failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

$BundleDir = Join-Path $TauriDir "target\release\bundle\nsis"
Write-Host ""
Write-Host "Build complete. Windows installer output:"
Write-Host "   $BundleDir"
