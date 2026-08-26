# Windows installation

The Windows collector is native. It does not use the Linux/X11 tracker.

It records:

- foreground window title
- process executable name
- focus duration
- aggregate key-release count, never raw key values
- AFK intervals based on `GetLastInputInfo`

Data is stored at:

```text
%LOCALAPPDATA%\ComputerActivityTracker\activity.sqlite3
```

The Desktop shortcut launches the collector through `pythonw.exe`, so no console window remains open. A named Windows mutex prevents duplicate tracker instances.

## Manual commands

From Command Prompt:

```bat
%USERPROFILE%\computer-activity-tracker\.venv\Scripts\python.exe %USERPROFILE%\computer-activity-tracker\windows\windows_activity_tracker.py --report
```

JSON export:

```bat
%USERPROFILE%\computer-activity-tracker\.venv\Scripts\python.exe %USERPROFILE%\computer-activity-tracker\windows\windows_activity_tracker.py --json
```

Run the deterministic storage self-test:

```bat
%USERPROFILE%\computer-activity-tracker\.venv\Scripts\python.exe %USERPROFILE%\computer-activity-tracker\windows\windows_activity_tracker.py --self-test --data-dir %USERPROFILE%\computer-activity-tracker\selftest-data
```

## Important

The tracker must be started by double-clicking the Desktop shortcut in the logged-in Windows session. Processes launched over SSH run in session 0 and cannot prove foreground-window capture for the interactive desktop.
