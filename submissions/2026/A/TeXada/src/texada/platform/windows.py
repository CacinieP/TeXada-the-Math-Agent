"""Windows platform adapter — pystray, win32clipboard, tkinter."""
import subprocess

from texada.platform.base import PlatformAdapter


class WindowsAdapter(PlatformAdapter):

    @property
    def platform_name(self) -> str:
        return "windows"

    def copy_to_clipboard(self, text: str) -> None:
        try:
            import win32clipboard
            import win32con
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            win32clipboard.CloseClipboard()
        except ImportError:
            # Fallback: use subprocess
            subprocess.run(["clip"], input=text.encode("utf-16le"), check=True)

    def read_clipboard_text(self) -> str | None:
        try:
            import win32clipboard
            import win32con
            win32clipboard.OpenClipboard()
            data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()
            return data
        except ImportError:
            return None

    def read_clipboard_image(self) -> bytes | None:
        try:
            from PIL import ImageGrab
            img = ImageGrab.grabclipboard()
            if img is not None:
                import io
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                return buf.getvalue()
        except ImportError:
            pass
        return None

    def show_notification(self, title: str, body: str) -> None:
        try:
            from win10toast import ToastNotifier
            toaster = ToastNotifier()
            toaster.show_toast(title, body, duration=3)
        except ImportError:
            subprocess.run(
                ["powershell", "-command",
                 f"New-BurntToastNotification -Text '{title}', '{body}'"],
                timeout=5,
            )

    def get_hotkey_manager(self):
        from texada.platform.hotkey_win import WindowsHotkeyManager
        return WindowsHotkeyManager()

    def get_shell_provider(self):
        from texada.platform.shell_win import WindowsShellProvider
        return WindowsShellProvider()