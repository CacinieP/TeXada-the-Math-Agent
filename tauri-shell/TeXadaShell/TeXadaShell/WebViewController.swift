import Cocoa
import WebKit

class WebViewController: NSViewController, WKScriptMessageHandler {
    var webView: WKWebView!
    let apiBase = "http://127.0.0.1:18732"
    var pendingRequests: [String: (Data) -> Void] = [:]

    override func loadView() {
        view = NSView()
    }

    override func viewDidLoad() {
        super.viewDidLoad()

        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")
        config.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")

        let userContent = config.userContentController
        userContent.add(self, name: "texada")

        webView = WKWebView(frame: .zero, configuration: config)
        webView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(webView)

        NSLayoutConstraint.activate([
            webView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            webView.topAnchor.constraint(equalTo: view.topAnchor),
            webView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        ])

        loadLocalHTML()
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
        case "convert_text":
            if let text = body["text"] as? String {
                convertText(text, id: reqId)
            }
        case "get_status":
            getStatus(id: reqId)
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
        default:
            break
        }
    }

    func sendToJS(id: String, result: Any) {
        let data = try! JSONSerialization.data(withJSONObject: result)
        let json = String(data: data, encoding: .utf8)!
        let js = "window.texadaSwiftBridge.onResult('\(id)', \(json))"
        DispatchQueue.main.async {
            self.webView.evaluateJavaScript(js, completionHandler: nil)
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

    func checkBackend() {
        getStatus(id: "startup-check")
    }

    func onWindowShown() {
        webView.evaluateJavaScript("window.texadaSwiftBridge.onWindowShown()", completionHandler: nil)
    }
}
