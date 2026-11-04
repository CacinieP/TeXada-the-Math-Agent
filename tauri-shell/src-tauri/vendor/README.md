# glib 0.18.5 security backport

Tauri 2's GTK3 dependencies require `glib ^0.18`. This local patch keeps the
published 0.18.5 package and API; it does not rename it to a fixed upstream release
or suppress the vulnerability advisory.

Upstream source:

- Published crate: <https://static.crates.io/crates/glib/glib-0.18.5.crate>
- Original crate SHA256: `233daaf6e83ae6a12a52055f568f9d7cf4671dabb78ff9560ab6da230ce00ee5`
- Original VCS commit: `42b9caf98e03ded086362d9653ca58fe94dc8658` (`glib/`).
- License and copyright: the crate's unchanged `LICENSE` and `COPYRIGHT` files.
- Advisory: <https://rustsec.org/advisories/RUSTSEC-2024-0429.html>
- Merged upstream fix: <https://github.com/gtk-rs/gtk-rs-core/pull/1343>.
- Byte-identical proposed 0.18 backport, closed without merging:
  <https://github.com/gtk-rs/gtk-rs-core/pull/2009>.
- Upstream declined a 0.18.6 release:
  <https://github.com/gtk-rs/gtk-rs-core/issues/2010>.

The complete published crate is retained. Its only source change is the attached
`glib-0.18.5-variant-str-iter.patch`: make the output pointer mutable and pass
`&mut p` to `g_variant_get_child` in `VariantStrIter::impl_get`. Passing `&p`
violates Rust's aliasing rules; optimized builds can discard the C function's
write and then dereference NULL. No dependency or public API in the crate is
changed.

The shell's `[patch.crates-io]` selects this path for the entire GTK3 dependency
graph. The dependency is currently Linux-only in the shell; the regression may
also run on other platforms with GLib development libraries installed.

From `tauri-shell/src-tauri`, verify the optimized upstream iterator tests:

```bash
cargo test --release --manifest-path vendor/glib-0.18.5/Cargo.toml --lib variant_iter
```

On Ubuntu, install `pkg-config` and `libglib2.0-dev` for this isolated test. It
does not require GTK/WebKit or launching the desktop application. Do not move
the resulting `target/` or generated test `Cargo.lock` into a source commit.

Compare this directory with a fresh extraction of the SHA256-verified crate to
audit the patch. When GTK3 can use an official fixed release, remove this
override and the vendor directory together, regenerate `Cargo.lock`, and rerun
the iterator tests. Version-based scanners may continue to report 0.18.5;
describe the backport explicitly instead of treating that as an upstream fix or
an automatically cleared alert.
