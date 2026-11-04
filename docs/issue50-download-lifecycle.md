# Issue #50: window and download recovery

The v0.4.2 cold-download observations recorded two temporary macOS GUI
processes returning exit code 0. The second session ended before another
download began. These records do not identify who requested exit, and do not
establish an HF failure, V8 crash, or automatic desktop timeout. The original
observations and partial-download evidence remain in [#50].

## Confirmed behavior and changes

The main window was closable and its close request was not intercepted.
Tauri's last-window close can therefore end the application normally, after
which the existing exit handler kills the owned backend. That explains a
possible `desktop=0` / `backend=SIGKILL` sequence, without proving that it
caused either historical exit.

Closing the main window now prevents its destruction and hides it instead.
The existing tray and shortcut can show the same window again. Other windows
retain their close behavior, and explicit application Quit remains available.
Lifecycle logs record window-close handling, exit requests and codes, and the
owned backend PID and termination; they do not log formula input or credentials.

Separately, reproducible download recovery defects are fixed:

- A transport interruption or short response keeps its received `.part`
  prefix for the next Range request. A final model is still published only
  after the pinned SHA256 passes. Invalid ranges, overlong bodies and bad
  final hashes do not become resumable trusted data.
- The NDJSON stream ends with exactly one `{"all_done":true,"success":true}`
  event after every role succeeds, including cached files. The first error
  produces a failure terminal and stops the sequence. Cancellation propagates
  without manufacturing a successful terminal.
- The UI requires a successful terminal before showing overall completion.
  An incomplete or malformed stream reports an interruption and permits retry.
  Repeated clicks cannot open concurrent streams; reader and button state are
  released after success or failure. Progress and transfer-rate baselines reset
  for each file, and progress text uses the real translation parameters.

The added terminal is separate from file events. Consumers should inspect
`all_done` before accessing a file-event field; EOF alone is not successful
completion.

## Verification and remaining native check

Automated checks cover the production Rust close policy and its SDK wiring,
real HTTPX interruption/Range recovery, integrity rejection, cancellation and
terminal events, plus WHATWG ReadableStream parsing in Node, retry and
translated UI progress. CI runs the close-policy regressions on macOS and
Windows. These checks do not stand in for native window interaction.

Native close/reopen/Quit was not rerun for this change because the user was
using the isolated desktop and explicitly requested that it not be operated.
When that window is available, verify with a separate isolated installation:

1. Launch normally and record the desktop/backend PIDs and API reachability.
2. During a cold download, close the main window. It should hide while the
   same backend and download continue; restore it through the tray/shortcut.
3. Explicitly Quit and check the exit-request/exit/backend-stop log sequence.
4. Repeat with direct executable startup to distinguish launch-environment
   effects. Preserve any differing outcome and the original failure records.

Until those observations are complete, #50 remains open and the historical
exit cause remains unknown. This patch does not change the existing release
artifacts or the recorded model evaluation references and results.

[#50]: https://github.com/CacinieP/TeXada-the-Math-Agent/issues/50
