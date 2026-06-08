"""Platform adapter ABC — all platform differences converge here."""
from __future__ import annotations

from abc import ABC, abstractmethod


class PlatformAdapter(ABC):
    """Platform abstraction — macOS / Windows implementations differ."""

    @abstractmethod
    def copy_to_clipboard(self, text: str) -> None:
        """Copy text to system clipboard."""
        ...

    @abstractmethod
    def read_clipboard_text(self) -> str | None:
        """Read text from system clipboard."""
        ...

    @abstractmethod
    def read_clipboard_image(self) -> bytes | None:
        """Read image data from system clipboard (for OCR)."""
        ...

    @abstractmethod
    def show_notification(self, title: str, body: str) -> None:
        """Show a desktop notification."""
        ...

    @abstractmethod
    def get_platform_name(self) -> str:
        """Return 'macos' or 'windows'."""
        ...


def create_adapter() -> PlatformAdapter:
    """Factory — returns the correct adapter for the current platform."""
    import sys

    if sys.platform == "darwin":
        from texada.platform.macos import MacOSAdapter
        return MacOSAdapter()
    elif sys.platform == "win32":
        from texada.platform.windows import WindowsAdapter
        return WindowsAdapter()
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")