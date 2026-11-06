# Issue #64 — macOS insertion and application focus

## Observations

A local macOS arm64 candidate built from the tree merged as
`7567ebaf3c17404049441cbcb6846d8cd777030a` passed packaged API checks,
formula rendering, clarification/resubmission and manual clipboard copying.
An automated insertion attempt left the temporary TextEdit document unchanged.
The hidden candidate window could subsequently time out during accessibility
inspection.

A read-only `NSWorkspace.frontmostApplication` timeline from
2026-11-06 10:17:29.969Z to 10:18:29.977Z recorded 1200 samples at a requested
50ms interval. Every sample identified the candidate application as frontmost.
The existing insert path hid its window and then sent a global Cmd+V after
160ms. It carried no application-level hide or insertion-stage diagnostics.
The timeline establishes the observed foreground state. The exact click and
paste stages require their own evidence.

## Bounded change

The actual insertion command first writes the clipboard and hides its window.
On macOS it then hides the application through Tauri's `AppHandle::hide`.
Either hide error returns to the caller before a paste command can run.
Hiding the window explicitly keeps the visibility-based tray/shortcut toggle
consistent with application-level hiding.

Both the `show_window` command and the tray/shortcut display branch restore
the macOS application before showing and focusing the window. Tauri documents
application showing separately from automatic focus.

Insertion diagnostics record only a nonempty-text boolean, stage names and
the paste command's success boolean. Stages distinguish clipboard writing,
window hiding, application hiding and paste execution. A successful paste
command records its process outcome. Actual target text requires native
verification.

## Verification scope

Source-contract regressions inspect the production command, SDK calls,
platform guard, failure propagation, restoration entry points and diagnostic
arguments. Locked macOS Rust checks compile the actual platform path.
Windows compilation is covered by the existing CI matrix.

Native target-text insertion and tray/shortcut restoration after this patch
remain pending under #64 and #46. The observed automation attempt and its
foreground timeline are retained as evidence from the earlier candidate.
