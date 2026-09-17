# Computer Activity Tracker

A local activity recorder with a browser dashboard. See which windows were in
focus, how much time each app had, and when you were away from the keyboard.
Search past days, export the history, or pause recording from the same screen.

![The dashboard during an isolated X11 test](docs/screenshots/overview.png)

*Actual app screenshot from a short, isolated X11 recording. The test window and
small totals are deliberate, not imported personal history.*

## Start here

Requires Python 3.10 or newer. Recording starts when you launch the app, not when
you install it. Only use it on a computer you own or have permission to monitor.

### Windows 10/11

1. Install Python with the Python launcher enabled if it is not already installed.
2. Extract or clone this repository, then run `install.cmd`.
3. Open the **Computer Activity Tracker** desktop shortcut, or run `launch.cmd`.

The shortcut opens the dashboard in your default browser. Launching it again
reopens the existing instance instead of starting a second recorder.

The installer, desktop shortcut, native window/key-count capture, and browser
controls have been exercised on a real Windows desktop with Python 3.11. The
same recording-to-dashboard path is tested on Linux/X11. See
[the Windows guide](windows/README-WINDOWS.md) and [verification scope](docs/VERIFICATION.md).

### Linux with an X11 desktop

On Debian or Ubuntu, install the system prerequisites:

```bash
sudo apt install python3-venv xinput
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python activity_tracker.py
```

Run that last command from your graphical desktop so it inherits the correct
`DISPLAY`. The app needs an EWMH window manager and the MIT-SCREEN-SAVER extension
for foreground windows and system idle time. Wayland and macOS recording are not
implemented; the dashboard explains that instead of reporting false activity.

You can also install the Python package from this checkout:

```bash
python -m pip install .
computer-activity-tracker
```

## What the app does

- **Overview:** active window time, AFK time, aggregate key-release counts, a daily
  activity chart, and time by application.
- **Timeline:** search window titles and app names, filter focused/AFK intervals,
  navigate dates and pages. Dates use your browser's timezone, including daylight
  saving changes.
- **Export:** download the selected date and current timeline filters as CSV or
  JSON. Exports include all matching rows, not just the visible page. CSV prefixes
  formula-like titles so opening them in a spreadsheet does not execute formulas.
- **Pause:** detach input monitoring and keep existing history readable. A paused
  state survives a restart until you explicitly resume.
- **Quit:** flush the current interval, detach monitoring, and stop the local
  server. Closing the browser tab alone does not quit the tracker.

The chart is a record of captured intervals, not a productivity score. A focused
window does not prove you were paying attention to it. Unobserved periods are
left blank, including long polling gaps caused by suspension or sleep.

## Storage and existing installations

No migration or database reset is required for the existing `focus` and `afk`
schema. The app adds indexes and appends new records; it does not rewrite history.

| Platform | Default location |
|---|---|
| Windows | `%LOCALAPPDATA%\ComputerActivityTracker\activity.sqlite3` |
| Linux source checkout with an existing `data/activity.sqlite3` | Keeps using that database |
| New Linux installation | `$XDG_DATA_HOME/computer-activity-tracker/activity.sqlite3`, normally `~/.local/share/computer-activity-tracker/activity.sqlite3` |

`--data-dir` or `CCA_HOME` selects another directory. When moving from the old
Linux CLI to an installed wheel, point at your existing directory explicitly:

```bash
computer-activity-tracker --data-dir /path/to/existing/data
```

Stop an older collector before switching. On Windows, the shared named mutex
prevents the new app and the old hidden collector from recording simultaneously.
The installer deliberately does not kill running processes or enable autostart.
Back up the database after quitting the old recorder; if using SQLite tools while
it is running, use SQLite's backup API rather than copying only the main file.

## Privacy

Recorded: focused window titles, app/process names, interval timestamps, key
**counts**, and idle intervals. Not recorded: the keys themselves, screenshots,
audio, clipboard contents, or document contents. A window title can still expose
sensitive information, including document names and page titles. Pause before
work you do not want in the log.

The dashboard binds only to `127.0.0.1`. A per-launch capability becomes an
HttpOnly, SameSite cookie; API routes reject cross-origin requests and unexpected
Host headers. No third-party scripts, fonts, telemetry, accounts, or uploads are
used. The local server is not designed to be published through a reverse proxy.

The database is not encrypted by the app. Use your OS account protection and
disk encryption. `runtime.json` contains a private launch URL: do not share it.
Treat exported files as personal data. Self-tests use disposable databases and
never reset the directory you use for real recording.

## Configuration

```bash
python activity_tracker.py --help
python activity_tracker.py --idle-timeout 300 --poll-interval 1
python activity_tracker.py --data-dir /path/to/data --port 43127
```

The default idle threshold is 180 seconds. The default checkpoint interval is one
second; allowed intervals are 0.1 to 10 seconds. `--no-browser` is for controlled
launches and testing. It does not make the API public or remove authentication.

The original CLI collectors remain available as `computer_activity_tracker.py`
(X11) and `windows/windows_activity_tracker.py` (Windows). Prefer the new
`activity_tracker.py` launcher for everyday use.

## Development and verification

```bash
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -v
python -m unittest discover -s windows -p 'test_*.py' -v
python -m unittest -v test_tracker.py
ruff check activity_app activity_tracker.py tests
python -m build
```

The default suite skips live desktop/browser tests. To exercise actual input,
SQLite, and browser interactions on an isolated X server:

```bash
sudo apt install xvfb openbox xterm xdotool xinput
python -m playwright install chromium
CCA_TEST_X11=1 CCA_TEST_BROWSER=1 xvfb-run -a \
  python -m unittest discover -s tests -v
```

All test databases are temporary. `CCA_EVIDENCE_DIR` saves screenshots from the
browser test. Set `CCA_AXE_JS` to a local `axe-core/axe.min.js` file to add WCAG
2.1 A/AA automated checks without adding axe to the shipped application.

See [verification notes](docs/VERIFICATION.md) for the boundary between tested
behavior and the outstanding Windows on-device check.

## Code layout

`activity_app/` contains recording lifecycle, native adapters, read-only reports,
exports, the loopback server, and the dashboard assets. `windows/` retains the
existing Win32 helpers and installer. `tests/` covers the new app, with live X11
and browser tests behind explicit opt-in flags. The project has no frontend build
step or runtime JavaScript dependencies.

MIT licensed. See [LICENSE](LICENSE).

