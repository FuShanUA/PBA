import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    private let progressPath: String
    private let nodeEventsPath: String
    private let requestEventsPath: String
    private let contentRoot: String
    private var window: NSWindow!
    private var overallField: NSTextField!
    private var overallRemainingField: NSTextField!
    private var roundRemainingField: NSTextField!
    private var processedField: NSTextField!
    private var errorsField: NSTextField!
    private var percentField: NSTextField!
    private var progressBar: NSProgressIndicator!
    private var nodeField: NSTextField!
    private var requestStatusField: NSTextField!
    private var recentLabel: NSTextField!
    private var eventTextView: NSTextView!
    private var timer: Timer?

    init(progressPath: String, nodeEventsPath: String, requestEventsPath: String, contentRoot: String) {
        self.progressPath = progressPath
        self.nodeEventsPath = nodeEventsPath
        self.requestEventsPath = requestEventsPath
        self.contentRoot = contentRoot
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let contentRect = NSRect(x: 0, y: 0, width: 460, height: 560)
        window = NSWindow(
            contentRect: contentRect,
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "翻译进度"
        window.center()
        window.isReleasedWhenClosed = false

        let title = NSTextField(labelWithString: "Palantir 文档翻译")
        title.font = .boldSystemFont(ofSize: 16)

        overallField = NSTextField(labelWithString: "总进度：0 / 0")
        overallField.font = .boldSystemFont(ofSize: 14)
        overallRemainingField = NSTextField(labelWithString: "全库剩余：0")
        roundRemainingField = NSTextField(labelWithString: "本轮剩余：0")
        processedField = NSTextField(labelWithString: "本轮已处理：0")
        errorsField = NSTextField(labelWithString: "本轮未完成：0")
        nodeField = NSTextField(labelWithString: "节点进度：0 / 0")
        requestStatusField = NSTextField(labelWithString: "请求状态：进行 0 / 成功 0 / 失败 0")
        requestStatusField.font = .monospacedDigitSystemFont(ofSize: 12, weight: .regular)
        percentField = NSTextField(labelWithString: "0%")
        percentField.font = .monospacedDigitSystemFont(ofSize: 14, weight: .regular)

        progressBar = NSProgressIndicator(frame: NSRect(x: 0, y: 0, width: 320, height: 20))
        progressBar.style = .bar
        progressBar.minValue = 0
        progressBar.maxValue = 100
        progressBar.doubleValue = 0

        recentLabel = NSTextField(labelWithString: "最近请求与节点")
        recentLabel.font = .boldSystemFont(ofSize: 13)

        eventTextView = NSTextView()
        eventTextView.isEditable = false
        eventTextView.isRichText = false
        eventTextView.isSelectable = true
        eventTextView.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
        eventTextView.backgroundColor = .textBackgroundColor
        eventTextView.textColor = .textColor
        eventTextView.autoresizingMask = [.width]
        eventTextView.textContainer?.widthTracksTextView = true

        let scrollView = NSScrollView()
        scrollView.documentView = eventTextView
        scrollView.hasVerticalScroller = true
        scrollView.hasHorizontalScroller = false
        scrollView.autohidesScrollers = true
        scrollView.borderType = .bezelBorder
        scrollView.translatesAutoresizingMaskIntoConstraints = false
        scrollView.heightAnchor.constraint(equalToConstant: 260).isActive = true

        let stack = NSStackView(views: [
            title,
            overallField,
            overallRemainingField,
            roundRemainingField,
            processedField,
            errorsField,
            nodeField,
            requestStatusField,
            percentField,
            progressBar,
            recentLabel,
            scrollView,
        ])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 10
        stack.translatesAutoresizingMaskIntoConstraints = false

        let contentView = window.contentView!
        contentView.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 20),
            stack.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -20),
            stack.topAnchor.constraint(equalTo: contentView.topAnchor, constant: 20),
            stack.bottomAnchor.constraint(lessThanOrEqualTo: contentView.bottomAnchor, constant: -20),
            progressBar.widthAnchor.constraint(equalToConstant: 340),
            scrollView.widthAnchor.constraint(equalTo: stack.widthAnchor),
        ])

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        update()
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            self?.update()
        }
    }

    private func update() {
        let counts = overallCounts()
        overallField.stringValue = "总进度：\(counts.done) / \(counts.total)"
        overallRemainingField.stringValue = "全库剩余：\(counts.missing)"

        var roundProcessed = 0
        var roundErrors = 0
        if let data = FileManager.default.contents(atPath: progressPath),
           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let completed = json["completed"] as? Int,
           let errors = json["errors"] as? Int {
            roundProcessed = (json["processed"] as? Int) ?? (completed + errors)
            roundErrors = errors
        }
        processedField.stringValue = "本轮已处理：\(roundProcessed)"
        errorsField.stringValue = "本轮失败：\(roundErrors)"
        if let data = FileManager.default.contents(atPath: progressPath),
           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let remaining = json["remaining"] as? Int {
            roundRemainingField.stringValue = "本轮剩余：\(remaining)"
        } else {
            roundRemainingField.stringValue = "本轮剩余：0"
        }

        let percent = counts.total > 0 ? Double(counts.done) / Double(counts.total) * 100 : 0
        percentField.stringValue = String(format: "%.1f%%", percent)
        progressBar.doubleValue = percent

        let nodeCounts = nodeProgress()
        nodeField.stringValue = "节点进度：\(nodeCounts.done) / \(nodeCounts.total)"
        let requestStatus = requestStatusCounts()
        requestStatusField.stringValue = "请求状态：进行 \(requestStatus.active) / 成功 \(requestStatus.success) / 失败 \(requestStatus.failed)，超时 \(requestStatus.timeouts)，缓存 \(requestStatus.cachedNodes) 节点"
        let recentText = recentLogText()
        eventTextView.string = recentText
        if !recentText.isEmpty {
            let length = (recentText as NSString).length
            eventTextView.scrollRangeToVisible(NSRange(location: length, length: 0))
        }
    }

    private func overallCounts() -> (total: Int, done: Int, missing: Int) {
        let fileManager = FileManager.default
        guard let entries = try? fileManager.contentsOfDirectory(atPath: contentRoot) else {
            return (0, 0, 0)
        }

        var total = 0
        var done = 0
        for entry in entries {
            let directory = (contentRoot as NSString).appendingPathComponent(entry)
            let english = directory + "/page.html"
            let chinese = directory + "/page_zh.html"
            guard fileManager.fileExists(atPath: english) else { continue }
            total += 1
            if let attributes = try? fileManager.attributesOfItem(atPath: chinese),
               let size = attributes[.size] as? Int, size > 200 {
                done += 1
            }
        }
        return (total, done, total - done)
    }

    private func nodeProgress() -> (done: Int, total: Int, recentText: String) {
        var total = 0
        if let data = FileManager.default.contents(atPath: progressPath),
           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let nodeTotal = json["node_total"] as? Int {
            total = nodeTotal
        }

        guard let contents = try? String(contentsOfFile: nodeEventsPath, encoding: .utf8) else {
            return (0, total, "")
        }

        let lines = contents.split(separator: "\n", omittingEmptySubsequences: true)
        let done = lines.count
        let recentLines = lines.suffix(40).map { line -> String in
            guard let data = String(line).data(using: .utf8),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let slug = json["slug"] as? String,
                  let source = json["source"] as? String,
                  let translation = json["translation"] as? String else {
                return String(line)
            }

            let at = (json["at"] as? String) ?? ""
            let time = at.count >= 19 ? String(at.dropFirst(11).prefix(8)) : at
            return "\(time)  \(clip(slug, 34))  \(clip(source, 48)) -> \(clip(translation, 48))"
        }

        return (done, total, recentLines.joined(separator: "\n"))
    }

    private func requestStatusCounts() -> (active: Int, success: Int, failed: Int, timeouts: Int, cachedNodes: Int) {
        guard let contents = try? String(contentsOfFile: requestEventsPath, encoding: .utf8) else {
            return (0, 0, 0, 0, 0)
        }

        var started = Set<Int>()
        var success = Set<Int>()
        var failed = Set<Int>()
        var timeouts = 0
        var cachedNodes = 0

        for rawLine in contents.split(separator: "\n", omittingEmptySubsequences: true) {
            guard let data = String(rawLine).data(using: .utf8),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let status = json["status"] as? String,
                  let requestID = json["request_id"] as? Int else {
                continue
            }

            switch status {
            case "cache":
                cachedNodes += (json["cached"] as? Int) ?? 0
            case "start":
                started.insert(requestID)
            case "success":
                success.insert(requestID)
            case "error":
                failed.insert(requestID)
            case "timeout":
                timeouts += 1
            default:
                break
            }
        }

        let active = started.subtracting(success).subtracting(failed).count
        return (active, success.count, failed.count, timeouts, cachedNodes)
    }

    private func recentLogText() -> String {
        var records: [(at: String, line: String)] = []

        if let contents = try? String(contentsOfFile: requestEventsPath, encoding: .utf8) {
            for rawLine in contents.split(separator: "\n", omittingEmptySubsequences: true) {
                guard let data = String(rawLine).data(using: .utf8),
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let at = json["at"] as? String,
                      let status = json["status"] as? String,
                      let slug = json["slug"] as? String else {
                    continue
                }

                let time = at.count >= 19 ? String(at.dropFirst(11).prefix(8)) : at
                let line: String
                switch status {
                case "cache":
                    let nodes = (json["nodes"] as? Int) ?? 0
                    let cached = (json["cached"] as? Int) ?? 0
                    let requests = (json["requests"] as? Int) ?? 0
                    line = "\(time)  [缓存] \(clip(slug, 34))  \(cached)/\(nodes) 节点，\(requests) 个请求"
                case "start":
                    let items = (json["items"] as? Int) ?? 0
                    let words = (json["words"] as? Int) ?? 0
                    line = "\(time)  [请求] 开始 \(clip(slug, 34))  \(items) 节点 / \(words) 词"
                case "waiting":
                    let elapsed = (json["elapsed"] as? Double) ?? 0
                    let phase = (json["phase"] as? String) ?? "等待 API"
                    line = "\(time)  [请求] 等待 \(clip(slug, 34))  \(String(format: "%.0f", elapsed)) 秒  \(clip(phase, 48))"
                case "timeout":
                    let elapsed = (json["elapsed"] as? Double) ?? 0
                    let error = (json["error"] as? String) ?? ""
                    line = "\(time)  [请求] 超时 \(clip(slug, 34))  \(String(format: "%.0f", elapsed)) 秒  \(clip(error, 48))"
                case "success":
                    let elapsed = (json["elapsed"] as? Double) ?? 0
                    let output = (json["output_chars"] as? Int) ?? 0
                    line = "\(time)  [请求] 成功 \(clip(slug, 34))  \(String(format: "%.0f", elapsed)) 秒 / \(output) 字符"
                case "retry":
                    let elapsed = (json["elapsed"] as? Double) ?? 0
                    let error = (json["error"] as? String) ?? ""
                    line = "\(time)  [请求] 重试 \(clip(slug, 34))  \(String(format: "%.0f", elapsed)) 秒  \(clip(error, 48))"
                case "error":
                    let elapsed = (json["elapsed"] as? Double) ?? 0
                    let error = (json["error"] as? String) ?? ""
                    line = "\(time)  [请求] 失败 \(clip(slug, 34))  \(String(format: "%.0f", elapsed)) 秒  \(clip(error, 48))"
                default:
                    line = "\(time)  [请求] \(status) \(clip(slug, 34))"
                }
                records.append((at, line))
            }
        }

        if let contents = try? String(contentsOfFile: nodeEventsPath, encoding: .utf8) {
            for rawLine in contents.split(separator: "\n", omittingEmptySubsequences: true) {
                guard let data = String(rawLine).data(using: .utf8),
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let at = json["at"] as? String,
                      let slug = json["slug"] as? String,
                      let source = json["source"] as? String,
                      let translation = json["translation"] as? String else {
                    continue
                }
                let time = at.count >= 19 ? String(at.dropFirst(11).prefix(8)) : at
                let line = "\(time)  [节点] \(clip(slug, 30))  \(clip(source, 38)) -> \(clip(translation, 38))"
                records.append((at, line))
            }
        }

        return records
            .sorted { $0.at < $1.at }
            .suffix(60)
            .map { $0.line }
            .joined(separator: "\n")
    }

    private func clip(_ text: String, _ limit: Int) -> String {
        if text.count <= limit {
            return text
        }
        return String(text.prefix(limit)) + "..."
    }
}

let rawArguments = CommandLine.arguments
let progressPath = rawArguments.count > 1
    ? rawArguments[1]
    : "/Users/shanfu/Desktop/palantir-blog-archive/data/translation_progress.json"
let nodeEventsPath = rawArguments.count > 2
    ? rawArguments[2]
    : "/Users/shanfu/Desktop/palantir-blog-archive/data/translation_node_events.jsonl"
let legacyThreeArgumentLaunch = rawArguments.count == 4
let requestEventsPath = rawArguments.count > 3 && !legacyThreeArgumentLaunch
    ? rawArguments[3]
    : "/Users/shanfu/Desktop/palantir-blog-archive/data/translation_request_events.jsonl"
let contentRoot = rawArguments.count > 4
    ? rawArguments[4]
    : (legacyThreeArgumentLaunch ? rawArguments[3] : "/Users/shanfu/Desktop/palantir-blog-archive/content/docs")

let app = NSApplication.shared
let delegate = AppDelegate(
    progressPath: progressPath,
    nodeEventsPath: nodeEventsPath,
    requestEventsPath: requestEventsPath,
    contentRoot: contentRoot
)
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
