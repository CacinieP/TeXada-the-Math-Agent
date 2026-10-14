from html.parser import HTMLParser
from pathlib import Path


def test_settings_sections_remain_inside_settings_tab():
    class Tree(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.found = set()

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            key = attrs.get("data-i18n")
            if key in {"settings.dataTitle", "settings.shortcuts", "settings.about"}:
                assert "tab-settings" in self.stack, key
                self.found.add(key)
            if tag == "div":
                self.stack.append(attrs.get("id"))

        def handle_endtag(self, tag):
            if tag == "div" and self.stack:
                self.stack.pop()

    tree = Tree()
    tree.feed((Path(__file__).parents[1] / "tauri-shell/src/index.html").read_text())
    assert tree.found == {"settings.dataTitle", "settings.shortcuts", "settings.about"}
