import Cocoa
import WebKit

class WebViewController: NSViewController, WKScriptMessageHandler, WKNavigationDelegate {
    var webView: WKWebView!
    let apiBase = WebViewController.resolveApiBase()
    var pendingRequests: [String: (Data) -> Void] = [:]
    private var isPageLoaded = false

    static func resolveApiBase() -> String {
        let env = ProcessInfo.processInfo.environment
        if let base = env["TEXADA_API_BASE"]?.trimmingCharacters(in: .whitespacesAndNewlines),
           !base.isEmpty {
            return String(base.dropLast(base.hasSuffix("/") ? 1 : 0))
        }
        let host = env["TEXADA_API_HOST"]?.trimmingCharacters(in: .whitespacesAndNewlines)
        let port = env["TEXADA_API_PORT"]?.trimmingCharacters(in: .whitespacesAndNewlines)
        return "http://\(host?.isEmpty == false ? host! : "127.0.0.1"):\(port?.isEmpty == false ? port! : "18732")"
    }

    override func loadView() {
        view = NSView()
    }

    override func viewDidLoad() {
        super.viewDidLoad()

        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")
        config.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        // Never cache local assets — always load the current main.js/style.css from disk
        config.websiteDataStore = WKWebsiteDataStore.nonPersistent()

        let userContent = config.userContentController
        userContent.add(self, name: "texada")

        webView = WKWebView(frame: .zero, configuration: config)
        webView.translatesAutoresizingMaskIntoConstraints = false
        webView.navigationDelegate = self
        webView.underPageBackgroundColor = .clear
        view.addSubview(webView)

        NSLayoutConstraint.activate([
            webView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            webView.topAnchor.constraint(equalTo: view.topAnchor),
            webView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        ])

        loadLocalHTML()
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        isPageLoaded = true
        checkBackend()
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        print("WebView failed to load: \(error.localizedDescription)")
    }

    func loadLocalHTML() {
        // Try assets subdirectory first, then fall back to same directory
        let fm = FileManager.default
        let execDir = Bundle.main.resourcePath ?? fm.currentDirectoryPath
        var htmlPath = (execDir as NSString).appendingPathComponent("assets/index.html")
        if !fm.fileExists(atPath: htmlPath) {
            htmlPath = (execDir as NSString).appendingPathComponent("index.html")
        }
        let url = URL(fileURLWithPath: htmlPath)
        webView.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
    }

    // MARK: - JS Bridge

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any],
              let cmd = body["cmd"] as? String else { return }

        let reqId = body["id"] as? String ?? ""

        switch cmd {
        case "get_api_base":
            sendToJS(id: reqId, result: ["ok": true, "text": apiBase])
        case "convert_text":
            if let text = body["text"] as? String {
                convertText(text, id: reqId)
            }
        case "get_status":
            getStatus(id: reqId)
        case "list_shorthands":
            listShorthands(id: reqId)
        case "get_backend_settings":
            getBackendSettings(id: reqId)
        case "save_backend_settings":
            if let settings = body["settings"] as? [String: Any] {
                saveBackendSettings(settings, id: reqId)
            }
        case "read_clipboard":
            let text = NSPasteboard.general.string(forType: .string) ?? ""
            sendToJS(id: reqId, result: ["ok": true, "text": text])
        case "write_clipboard":
            if let text = body["text"] as? String {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(text, forType: .string)
                sendToJS(id: reqId, result: ["ok": true])
            }
        case "hide_window":
            if let app = NSApp.delegate as? AppDelegate {
                DispatchQueue.main.async { app.hidePanel() }
            }
            sendToJS(id: reqId, result: ["ok": true])
        case "show_window":
            if let app = NSApp.delegate as? AppDelegate {
                DispatchQueue.main.async { app.showPanel() }
            }
            sendToJS(id: reqId, result: ["ok": true])
        case "start_window_drag":
            if let app = NSApp.delegate as? AppDelegate {
                DispatchQueue.main.async { app.startWindowDrag() }
            }
            sendToJS(id: reqId, result: ["ok": true])
        case "end_window_drag":
            if let app = NSApp.delegate as? AppDelegate {
                DispatchQueue.main.async { app.endWindowDrag() }
            }
            sendToJS(id: reqId, result: ["ok": true])
        default:
            break
        }
    }

    func sendToJS(id: String, result: Any) {
        guard isPageLoaded else { return }
        let data = try! JSONSerialization.data(withJSONObject: result)
        let json = String(data: data, encoding: .utf8)!
        let js = "window.texadaSwiftBridge.onResult('\(id)', \(json))"
        DispatchQueue.main.async {
            self.webView.evaluateJavaScript(js) { _, error in
                if let error = error {
                    print("JS evaluation error: \(error.localizedDescription)")
                }
            }
        }
    }

    // MARK: - HTTP API

    func convertText(_ text: String, id: String) {
        let url = URL(string: "\(apiBase)/api/convert")!
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body: [String: Any] = ["text": text, "render_mode": "katex"]
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)

        URLSession.shared.dataTask(with: req) { [weak self] data, response, error in
            guard let self = self else { return }
            if let error = error {
                self.sendToJS(id: id, result: ["ok": false, "error": error.localizedDescription])
                return
            }
            guard let data = data else {
                self.sendToJS(id: id, result: ["ok": false, "error": "No data"])
                return
            }
            do {
                let json = try JSONSerialization.jsonObject(with: data)
                self.sendToJS(id: id, result: ["ok": true, "data": json])
            } catch {
                self.sendToJS(id: id, result: ["ok": false, "error": "Parse error"])
            }
        }.resume()
    }

    func getStatus(id: String) {
        let url = URL(string: "\(apiBase)/api/status")!
        URLSession.shared.dataTask(with: url) { [weak self] data, _, error in
            guard let self = self else { return }
            if let error = error {
                self.sendToJS(id: id, result: ["ok": false, "error": error.localizedDescription])
                return
            }
            guard let data = data else {
                self.sendToJS(id: id, result: ["ok": false, "error": "No data"])
                return
            }
            do {
                let json = try JSONSerialization.jsonObject(with: data)
                self.sendToJS(id: id, result: ["ok": true, "data": json])
            } catch {
                self.sendToJS(id: id, result: ["ok": false, "error": "Parse error"])
            }
        }.resume()
    }

    func listShorthands(id: String) {
        let url = URL(string: "\(apiBase)/api/shorthands")!
        URLSession.shared.dataTask(with: url) { [weak self] data, _, error in
            guard let self = self else { return }
            if let error = error {
                self.sendToJS(id: id, result: ["ok": false, "error": error.localizedDescription])
                return
            }
            guard let data = data else {
                self.sendToJS(id: id, result: ["ok": false, "error": "No data"])
                return
            }
            do {
                let json = try JSONSerialization.jsonObject(with: data)
                self.sendToJS(id: id, result: ["ok": true, "data": json])
            } catch {
                self.sendToJS(id: id, result: ["ok": false, "error": "Parse error"])
            }
        }.resume()
    }

    func getBackendSettings(id: String) {
        let url = URL(string: "\(apiBase)/api/settings/backend")!
        URLSession.shared.dataTask(with: url) { [weak self] data, _, error in
            guard let self = self else { return }
            if let error = error {
                self.sendToJS(id: id, result: ["ok": false, "error": error.localizedDescription])
                return
            }
            guard let data = data else {
                self.sendToJS(id: id, result: ["ok": false, "error": "No data"])
                return
            }
            do {
                let json = try JSONSerialization.jsonObject(with: data)
                self.sendToJS(id: id, result: ["ok": true, "data": json])
            } catch {
                self.sendToJS(id: id, result: ["ok": false, "error": "Parse error"])
            }
        }.resume()
    }

    func saveBackendSettings(_ settings: [String: Any], id: String) {
        let url = URL(string: "\(apiBase)/api/settings/backend")!
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: settings)

        URLSession.shared.dataTask(with: req) { [weak self] data, response, error in
            guard let self = self else { return }
            if let error = error {
                self.sendToJS(id: id, result: ["ok": false, "error": error.localizedDescription])
                return
            }
            if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
                self.sendToJS(id: id, result: ["ok": false, "error": "HTTP \(http.statusCode)"])
                return
            }
            guard let data = data else {
                self.sendToJS(id: id, result: ["ok": false, "error": "No data"])
                return
            }
            do {
                let json = try JSONSerialization.jsonObject(with: data)
                self.sendToJS(id: id, result: ["ok": true, "data": json])
            } catch {
                self.sendToJS(id: id, result: ["ok": false, "error": "Parse error"])
            }
        }.resume()
    }

    func checkBackend() {
        getStatus(id: "startup-check")
    }

    func onWindowShown() {
        guard isPageLoaded else { return }
        webView.evaluateJavaScript("window.texadaSwiftBridge.onWindowShown()") { _, error in
            if let error = error {
                print("onWindowShown JS error: \(error.localizedDescription)")
            }
        }
    }
}
