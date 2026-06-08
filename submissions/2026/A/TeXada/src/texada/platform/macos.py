"""macOS platform adapter — pbcopy, NSPasteboard, osascript."""
import subprocess

from texada.platform.base import PlatformAdapter


class MacOSAdapter(PlatformAdapter):

    def copy_to_clipboard(self, text: str) -> None:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)

    def read_clipboard_text(self) -> str | None:
        result = subprocess.run(["pbpaste"], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout:
            return result.stdout
        return None

    def read_clipboard_image(self) -> bytes | None:
        """Read PNG image from macOS clipboard via pngpaste."""
        try:
            result = subprocess.run(
                ["pngpaste", "-"], capture_output=True, timeout=3
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout
        except FileNotFoundError:
            # pngpaste not installed — try osascript + temporary file
            pass
        return None

    def show_notification(self, title: str, body: str) -> None:
        # Escape double quotes to prevent AppleScript injection
        safe_title = title.replace('"', '\\"')
        safe_body = body.replace('"', '\\"')
        script = f'display notification "{safe_body}" with title "{safe_title}"'
        subprocess.run(["osascript", "-e", script], timeout=5)

    def get_platform_name(self) -> str:
        return "macos"