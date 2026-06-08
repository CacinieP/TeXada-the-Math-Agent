import Cocoa
import WebKit

class AppDelegate: NSObject, NSApplicationDelegate {
    var statusItem: NSStatusItem!
    var panel: NSPanel!
    var webViewController: WebViewController!
    var eventMonitor: Any?

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Status bar item
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.title = "𝑇"
            button.font = NSFont.systemFont(ofSize: 14, weight: .bold)
        }

        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "Show / Hide", action: #selector(togglePanel), keyEquivalent: ""))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Quit", action: #selector(quit), keyEquivalent: "q"))
        statusItem.menu = menu

        // Floating panel
        let rect = NSRect(x: 0, y: 0, width: 560, height: 420)
        panel = NSPanel(
            contentRect: rect,
            styleMask: [.nonactivatingPanel, .borderless, .closable],
            backing: .buffered,
            defer: false
        )
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.hasShadow = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.isMovableByWindowBackground = true
        panel.delegate = self

        // WebView
        webViewController = WebViewController()
        webViewController.view.frame = panel.contentView!.bounds
        webViewController.view.autoresizingMask = [.width, .height]
        panel.contentView?.addSubview(webViewController.view)

        // Global shortcut ⌥⌘T
        NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self = self else { return }
            if event.keyCode == 17 // 'T'
                && event.modifierFlags.contains(.option)
                && event.modifierFlags.contains(.command) {
                self.togglePanel()
            }
        }

        // Hide on click outside (optional)
        eventMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] event in
            guard let self = self, self.panel.isVisible else { return }
            if let window = event.window, window == self.panel { return }
            self.hidePanel()
        }

        // Check backend on startup
        webViewController.checkBackend()
    }

    @objc func togglePanel() {
        if panel.isVisible {
            hidePanel()
        } else {
            showPanel()
        }
    }

    func showPanel() {
        positionPanelNearCursor()
        panel.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        webViewController.onWindowShown()
    }

    func hidePanel() {
        panel.orderOut(nil)
    }

    @objc func quit() {
        NSApp.terminate(nil)
    }

    func positionPanelNearCursor() {
        let mouseLoc = NSEvent.mouseLocation
        let screen = NSScreen.screens.first {
            $0.frame.contains(mouseLoc)
        } ?? NSScreen.main ?? NSScreen.screens.first!

        let sf = screen.frame
        let w = panel.frame.width
        let h = panel.frame.height

        var x = mouseLoc.x - w / 2
        var y = mouseLoc.y + 16

        if x < sf.minX { x = sf.minX + 8 }
        if x + w > sf.maxX { x = sf.maxX - w - 8 }
        if y + h > sf.maxY { y = mouseLoc.y - h - 8 }
        if y < sf.minY { y = sf.minY + 8 }

        panel.setFrameOrigin(NSPoint(x: x, y: y))
    }
}

extension AppDelegate: NSWindowDelegate {
    func windowDidResignKey(_ notification: Notification) {
        hidePanel()
    }
}
