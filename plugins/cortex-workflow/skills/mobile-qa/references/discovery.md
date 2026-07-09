# SUT Discovery

Identify **four things** before investigation: the **platform**, the **device**, the **app**, and the **build command**.

## Step 1: Resolve Platform

### 1a: Check project structure

Look for platform signals in the project:

| Signal | Platform |
|---|---|
| `.xcodeproj` / `.xcworkspace` / `*.swift` / `Podfile` | **iOS** |
| `build.gradle*` / `AndroidManifest.xml` / `androidApp/` | **Android** |
| Both iOS + Android signals, or `app.json` / `pubspec.yaml` / `shared/` with `build.gradle.kts` | **Multi-platform** |

- **Single platform detected** → use it.
- **Multi-platform detected** → ask the operator:
  > "This is a multi-platform project. Which platform should I QA — iOS, Android, or both?"

### 1b: Check operator input

If `$ARGUMENTS` specifies "iOS", "Android", a bundle ID (`com.company.AppName`), or a package name (`com.company.appname`), the platform is known.

### Both platforms

When the operator chooses **both**, run the full QA flow on each platform sequentially — same steps, same assertions. Report findings per platform.

## Step 2: Resolve Device

Call `mobile_list_available_devices`.

- **One matching device running** → use it, confirm with operator.
- **Multiple running** → ask which one.
- **None running but available** → boot the most appropriate one:
  - iOS: `xcrun simctl boot "<device_name>" && open -a Simulator`
  - Android: `emulator -avd <avd_name> &`
  - If multiple available, ask which to boot.
- **None available** → tell operator to install simulator runtimes (Xcode → Settings → Platforms) or create an AVD (Android Studio → Device Manager).

After booting, call `mobile_list_available_devices` again to confirm.

## Step 3: Resolve App

Check in order:

1. **`$ARGUMENTS`** — bundle ID or package name if provided.
2. **Project files:**
   - iOS: `Info.plist` → `CFBundleIdentifier`, or `.pbxproj` → `PRODUCT_BUNDLE_IDENTIFIER`
   - Android: `build.gradle*` → `applicationId`, or `AndroidManifest.xml` → `package`
   - React Native / Expo: `app.json` → `ios.bundleIdentifier` / `android.package`
   - Flutter: `ios/Runner/Info.plist` and `android/app/build.gradle`
   - KMP: `iosApp/` project for iOS, `androidApp/build.gradle.kts` for Android
3. **CLAUDE.md** — app identifiers or build instructions.
4. **Installed apps** — `mobile_list_apps` on the target device.

## Step 4: Build and Deploy

The app on the device must match the current source code. **Always build and deploy before investigation** — the installed app may be stale from previous work.

### Resolve build command

Check in order:

1. **CLAUDE.md** — look for build/run commands (e.g., `xcodebuild`, `./gradlew installDebug`, `npx expo run:ios`).
2. **Project conventions:**
   - iOS (Xcode): `xcodebuild -project <proj>.xcodeproj -scheme <scheme> -destination 'platform=iOS Simulator,name=<device>' build` then `xcrun simctl install booted <path-to-.app>`
   - iOS (workspace/CocoaPods): `xcodebuild -workspace <ws>.xcworkspace -scheme <scheme> -destination 'platform=iOS Simulator,name=<device>' build`
   - Android (Gradle): `./gradlew <module>:installDebug`
   - React Native: `npx react-native run-ios` / `npx react-native run-android`
   - Flutter: `flutter run -d <device>`
   - KMP: check `iosApp/` and `androidApp/` modules for their respective build commands
3. **Ask the operator** if no build command can be resolved.

Run the build command. If it fails, report the error and ask the operator for help. **Blocking** — cannot proceed with stale code.

### Deploy

Some build commands auto-install (e.g., `./gradlew installDebug`, `flutter run`). If the build produces an artifact without installing:

- iOS: `xcrun simctl install booted /path/to/App.app`
- Android: `adb install /path/to/app.apk`

## Step 5: Reset and Launch

Reset app to clean state after deploy (see `tooling.md` → App State Reset), unless operator asks to preserve state.

Launch with `mobile_launch_app`. Take a screenshot to confirm the app is running.

## Confirmation

Present findings and confirm before proceeding:

> "I found `com.example.app` targeting iOS. iPhone 16 Pro simulator is running. I'll build with `xcodebuild ...` and deploy. Should I proceed?"

**SUT is blocking** — cannot investigate without a freshly built, running app on a reachable device.
