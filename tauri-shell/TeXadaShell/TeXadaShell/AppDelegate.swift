import Cocoa
import WebKit

class AppDelegate: NSObject, NSApplicationDelegate {
    var statusItem: NSStatusItem!
    var panel: NSPanel!
    var webViewController: WebViewController!
    var eventMonitor: Any?

    // Drag state (JS-coordinated header drag)
    private var dragStartMouseLoc = NSPoint.zero
    private var dragStartPanelOrigin = NSPoint.zero
    private var dragLocalMonitor: Any?
    private var dragUpLocalMonitor: Any?

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
        let rect = NSRect(x: 0, y: 0, width: 520, height: 380)
        panel = NSPanel(
            contentRect: rect,
            styleMask: [.borderless, .closable],
            backing: .buffered,
            defer: false
        )
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.hasShadow = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.isMovableByWindowBackground = false
        panel.becomesKeyOnlyIfNeeded = false
        panel.delegate = self

        // WebView
        webViewController = WebViewController()
        webViewController.view.frame = panel.contentView!.bounds
        webViewController.view.autoresizingMask = [.width, .height]
        panel.contentView?.wantsLayer = true
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
            let loc = NSEvent.mouseLocation
            if self.panel.frame.contains(loc) { return }
            self.hidePanel()
        }
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
        NSApp.activate(ignoringOtherApps: true)
        panel.makeKeyAndOrderFront(nil)
        // Ensure the WebView can receive keyboard / mouse events before notifying JS.
        DispatchQueue.main.async { [weak self] in
            guard let self = self, let webView = self.webViewController.webView else { return }
            self.panel.makeFirstResponder(webView)
            webView.becomeFirstResponder()
            self.webViewController.onWindowShown()
        }
    }

    func hidePanel() {
        panel.orderOut(nil)
    }

    @objc func quit() {
        NSApp.terminate(nil)
    }

    // MARK: - JS-coordinated header drag
    func startWindowDrag() {
        guard panel.isVisible else { return }
        dragStartMouseLoc = NSEvent.mouseLocation
        dragStartPanelOrigin = panel.frame.origin

        dragLocalMonitor = NSEvent.addLocalMonitorForEvents(matching: .leftMouseDragged) { [weak self] event in
            guard let self = self else { return event }
            let loc = NSEvent.mouseLocation
            var newOrigin = NSPoint(
                x: self.dragStartPanelOrigin.x + (loc.x - self.dragStartMouseLoc.x),
                y: self.dragStartPanelOrigin.y + (loc.y - self.dragStartMouseLoc.y)
            )
            // Keep at least part of the header on screen
            if let screen = NSScreen.screens.first(where: { $0.frame.contains(loc) }) ?? NSScreen.main {
                let sf = screen.frame
                let w = self.panel.frame.width
                if newOrigin.x < sf.minX - w + 60 { newOrigin.x = sf.minX - w + 60 }
                if newOrigin.x > sf.maxX - 60 { newOrigin.x = sf.maxX - 60 }
                if newOrigin.y < sf.minY { newOrigin.y = sf.minY }
                if newOrigin.y > sf.maxY - 20 { newOrigin.y = sf.maxY - 20 }
            }
            self.panel.setFrameOrigin(newOrigin)
            return nil // consume event so WebView doesn't process it
        }

        dragUpLocalMonitor = NSEvent.addLocalMonitorForEvents(matching: .leftMouseUp) { [weak self] event in
            self?.endWindowDrag()
            return event
        }
    }

    func endWindowDrag() {
        if let monitor = dragLocalMonitor {
            NSEvent.removeMonitor(monitor)
            dragLocalMonitor = nil
        }
        if let monitor = dragUpLocalMonitor {
            NSEvent.removeMonitor(monitor)
            dragUpLocalMonitor = nil
        }
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
