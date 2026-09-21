import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    private let progressPath: String
    private let contentRoot: String
    private var window: NSWindow!
    private var overallField: NSTextField!
    private var overallRemainingField: NSTextField!
    private var roundRemainingField: NSTextField!
    private var processedField: NSTextField!
    private var errorsField: NSTextField!
    private var percentField: NSTextField!
    private var progressBar: NSProgressIndicator!
    private var timer: Timer?

    init(progressPath: String, contentRoot: String) {
        self.progressPath = progressPath
        self.contentRoot = contentRoot
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let contentRect = NSRect(x: 0, y: 0, width: 380, height: 300)
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
        percentField = NSTextField(labelWithString: "0%")
        percentField.font = .monospacedDigitSystemFont(ofSize: 14, weight: .regular)

        progressBar = NSProgressIndicator(frame: NSRect(x: 0, y: 0, width: 320, height: 20))
        progressBar.style = .bar
        progressBar.minValue = 0
        progressBar.maxValue = 100
        progressBar.doubleValue = 0

        let stack = NSStackView(views: [
            title,
            overallField,
            overallRemainingField,
            roundRemainingField,
            processedField,
            errorsField,
            percentField,
            progressBar,
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
}

let progressPath = CommandLine.arguments.count > 1
    ? CommandLine.arguments[1]
    : "/Users/shanfu/Desktop/palantir-blog-archive/data/translation_progress.json"
let contentRoot = CommandLine.arguments.count > 2
    ? CommandLine.arguments[2]
    : "/Users/shanfu/Desktop/palantir-blog-archive/content/docs"

let app = NSApplication.shared
let delegate = AppDelegate(progressPath: progressPath, contentRoot: contentRoot)
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
