//! Keep the floating main window alive when the user closes its presentation.
//! Explicit application exit is handled separately by the Tauri event loop.

#[derive(Debug, PartialEq, Eq)]
pub(crate) enum WindowCloseResult<E> {
    Unhandled,
    Hidden,
    HideFailed(E),
}

pub(crate) fn handle_window_close<E>(
    label: &str,
    prevent_close: impl FnOnce(),
    hide: impl FnOnce() -> Result<(), E>,
) -> WindowCloseResult<E> {
    if label != "main" {
        return WindowCloseResult::Unhandled;
    }

    // A failed hide must leave a live window, not destroy the only window and
    // abort an owned backend download. Explicit Quit remains available.
    prevent_close();
    match hide() {
        Ok(()) => WindowCloseResult::Hidden,
        Err(error) => WindowCloseResult::HideFailed(error),
    }
}

#[cfg(test)]
mod tests {
    use super::{handle_window_close, WindowCloseResult};
    use std::cell::{Cell, RefCell};

    #[test]
    fn closing_main_prevents_destruction_before_hiding() {
        let calls = RefCell::new(Vec::new());
        let outcome = handle_window_close(
            "main",
            || calls.borrow_mut().push("prevent_close"),
            || {
                calls.borrow_mut().push("hide");
                Ok::<_, &str>(())
            },
        );
        assert_eq!(outcome, WindowCloseResult::Hidden);
        assert_eq!(*calls.borrow(), ["prevent_close", "hide"]);
    }

    #[test]
    fn a_hide_failure_still_keeps_the_main_window_alive_and_reports_the_error() {
        let prevented = Cell::new(false);
        let outcome = handle_window_close(
            "main",
            || prevented.set(true),
            || {
                assert!(prevented.get());
                Err("synthetic window error")
            },
        );
        assert!(prevented.get());
        assert_eq!(
            outcome,
            WindowCloseResult::HideFailed("synthetic window error")
        );
    }

    #[test]
    fn other_windows_retain_their_normal_close_behavior() {
        for label in ["settings", "main-secondary", ""] {
            assert_eq!(
                handle_window_close(
                    label,
                    || panic!("unrelated close must not be prevented"),
                    || -> Result<(), &str> { panic!("unrelated window must not be hidden") },
                ),
                WindowCloseResult::Unhandled,
            );
        }
    }
}
