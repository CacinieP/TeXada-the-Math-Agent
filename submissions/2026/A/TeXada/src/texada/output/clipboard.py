"""Clipboard adapter — platform-aware clipboard operations."""
from __future__ import annotations

from texada.platform.base import PlatformAdapter


class ClipboardAdapter:
    """Wraps PlatformAdapter for clipboard operations."""

    def __init__(self, platform: PlatformAdapter):
        self.platform = platform

    def copy(self, text: str) -> None:
        """Copy text to system clipboard."""
        self.platform.copy_to_clipboard(text)

    def read_text(self) -> str | None:
        """Read text from clipboard."""
        return self.platform.read_clipboard_text()

    def read_image(self) -> bytes | None:
        """Read image from clipboard (for OCR)."""
        return self.platform.read_clipboard_image()