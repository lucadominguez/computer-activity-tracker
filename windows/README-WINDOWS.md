# Windows: Passage adaptation

Run `install.cmd`, then open the **Passage** desktop shortcut. The previous
**Computer Activity Tracker** shortcut still opens the same application.

Python 3.10+ is required; the native Windows path is exercised with Python 3.11.
The installer creates `.venv`, installs pinned Windows capture/OCR dependencies,
runs an isolated storage smoke test, and creates the two shortcuts. It does not
automatically enable screenshots, autostart, or stop a running older recorder.

**Settings → Save screenshots and OCR** enables the new memory recorder. Windows
OCR uses your installed recognizer language; install a supported language in
Windows Settings if none is available. No OCR model is downloaded from an AI
provider. Common password/private-window exclusions are only a safety net: pause
before sensitive work. Closing the window does not stop recording; use **Quit
app** in Settings.

The native GUI launch uses Chrome or Edge app-window mode when available, falling
back to the default browser. Duplicate launches reopen the running server.

Data stays at `%LOCALAPPDATA%\ComputerActivityTracker`. The old
`activity.sqlite3` and `focus`/`afk` schema remain intact. New encrypted payloads
live under `passage`; its DPAPI-protected key depends on your Windows account.
Earlier activity is available from Settings. Back up before upgrading, after
quitting the old recorder. Do not delete or regenerate the vault key.

For remote installation, an SSH process is in Session 0. Start the shortcut in
the logged-in interactive session, not directly from SSH. A bounded interactive
Task Scheduler task must explicitly permit running on battery and must produce
a fresh on-desktop capture receipt. A scheduler success code alone proves nothing.

See the [main README](../README.md) for exact privacy boundaries, limitations,
upstream differences, and test commands. This is not a Windows build of Sid's
Swift/SQLCipher/CoreML application.
