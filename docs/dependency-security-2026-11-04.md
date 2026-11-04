# Dependency security maintenance — 2026-11-04

The starting default branch had **49 open Dependabot alerts** across six
packages. Updating `pyproject.toml` alone had left old versions in `uv.lock`;
CI could resolve a newer environment without updating the committed snapshot.

| Package | Previous lock | Updated dependency | Starting alerts |
| --- | --- | --- | --- |
| Pillow | 12.3.0 | 13.0.0 | 41 |
| certifi | 2026.5.20 | 2026.10.23 | 1 |
| setuptools | 83.0.0 | 84.2.1 | 1 |
| rustls | 0.23.41 | 0.23.46 | 4 |
| KaTeX | 0.17.0 | 0.18.2 | 1 |
| glib | 0.18.5 | Local source backport; see below | 1 |

## Locked builds and offline KaTeX

Python checks, dependency exports and PyInstaller builds now use `uv --locked`;
Rust checks use `cargo check --locked`. An outdated lock must fail instead of
being silently refreshed during validation. npm checks include low-severity
alerts, including the KaTeX [trust restriction advisory](https://github.com/advisories/GHSA-238p-pmpm-9mq7).
The contributor instructions export the actual project dependency tree for
`pip-audit`; auditing the tool's temporary environment does not audit TeXada.

The pinned KaTeX npm package, offline JavaScript/CSS and parser version contract
move together to 0.18.2. The Python wheel and packaged sidecar use the same
vendored JavaScript as the desktop UI. Strict structure comparisons retain the
node/field allowlist and rejection of unsupported representations. Historical
evaluation reports keep their original versions and results.

## glib compatibility boundary

The GTK3 dependency of Tauri uses the glib 0.18 series. The upstream fix for
[`VariantStrIter` unsoundness](https://github.com/advisories/GHSA-wrw7-89jp-8q8g)
is released in glib 0.20, which cannot replace the GTK3 dependency directly.
This checkout applies a source backport of the upstream iterator fix, without
claiming that glib 0.18.5 is an officially patched registry release. The patch
and its provenance must remain in the source checkout when building.
See the [vendored-source record](../tauri-shell/src-tauri/vendor/README.md)
for the original crate hash and the exact two-line upstream fix. The audit
workflow runs the upstream iterator tests in release mode on Linux with GLib
development headers, exercising the optimized code path implicated by the
advisory; macOS and Windows also check the locked desktop dependency graph.

Version-only scanners may still report the glib advisory. Do not dismiss it
as a false positive, forge a dependency version, or upgrade the incompatible
GTK API just to remove the alert. Revisit the backport when the desktop
framework offers a compatible maintained dependency path.

## Reproducing validation

Use the commands in [Contributing](../.github/CONTRIBUTING.md) for locked Python,
frontend and desktop checks. The dependency update does not invoke a real model
or establish formula accuracy. Existing published installers retain their old
dependencies until a separate desktop build and release is completed; merging
source fixes does not replace installed applications or existing release assets.

修复前共有 49 条告警。此记录区分锁定版本升级、离线资源同步和 glib 源码回移，
不把版本扫描的消失当作运行时修复证明，也不把源码合并当作安装包已更新。
