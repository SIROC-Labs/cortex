// Conductor.app: posts conductor's banners, and opens a banner's page when it is
// clicked. `Conductor notify <title> <text> <url> <sound>` posts one and quits;
// a click on a banner launches the app again, which opens the page and quits.

import AppKit
import UserNotifications

final class Conductor: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    func applicationWillFinishLaunching(_ notification: Notification) {
        UNUserNotificationCenter.current().delegate = self
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let args = CommandLine.arguments
        if args.count >= 5 && args[1] == "notify" {
            post(title: args[2], text: args[3], url: args[4], sound: args.count > 5 ? args[5] : "")
        } else {
            quit(after: 5)
        }
    }

    func post(title: String, text: String, url: String, sound: String) {
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound]) { allowed, _ in
            guard allowed else {
                DispatchQueue.main.async { NSSound(named: NSSound.Name(sound.isEmpty ? "Glass" : sound))?.play() }
                return self.quit(after: 2)
            }
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = text
            content.sound = sound.isEmpty ? .default
                : UNNotificationSound(named: UNNotificationSoundName(sound + ".aiff"))
            content.userInfo = ["url": url]
            let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
            center.add(request) { _ in self.quit(after: 1) }
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler done: @escaping () -> Void) {
        if let text = response.notification.request.content.userInfo["url"] as? String,
           let url = URL(string: text), !text.isEmpty {
            NSWorkspace.shared.open(url)
        }
        done()
        quit(after: 0.5)
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler done: @escaping (UNNotificationPresentationOptions) -> Void) {
        done([.banner, .sound])
    }

    func quit(after seconds: Double) {
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds) { NSApp.terminate(nil) }
    }
}

let app = NSApplication.shared
let conductor = Conductor()
app.delegate = conductor
app.setActivationPolicy(.accessory)
app.run()
