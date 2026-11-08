# 60-second demo video (for Agensi / launch)

The demo is **deterministic and free**: it uses `tests/fake_agent.py` in `lazy`
mode (0 tokens). The agent does task 1, stops, gets kicked, then finishes.

## Record (Windows, no install)

Xbox Game Bar is built in:

1. Open Windows Terminal (or PowerShell), font size 16+, dark theme.
2. Focus the terminal.
3. Press **Win+Alt+R** to start recording (Win+G opens the overlay).
4. Run:

```powershell
cd C:\Users\tuank\waker-ai
.venv\Scripts\python.exe scripts\demo_session.py --pause
```

5. Press **Enter** at each `>>>` prompt. The script runs:
   - plan (prompt -> tasks.yaml)
   - lint
   - run with the lazy fake agent: `PARTIAL` -> kick -> `DONE` (2/2)
   - report + status
6. Press **Win+Alt+R** again to stop. The MP4 is in `Videos\Captures`.

Optional tools:

```powershell
winget install --id OBSProject.OBSStudio -e   # more control
winget install --id ShareX.ShareX -e          # screen -> MP4/GIF
```

Or record with **Loom** (browser/desktop) if you want a shareable URL without
uploading to YouTube.

## Voiceover / captions (45–60s)

| Time | Say / show |
|---|---|
| 0:00–0:06 | "AI coding agents stop early, or claim they're done while tests are red." |
| 0:06–0:15 | Show `waker plan` -> `tasks.yaml`, then `waker lint` |
| 0:15–0:30 | Show the run: agent stops at Task 1; waker says `PARTIAL`, wakes it; 2/2 `DONE` |
| 0:30–0:42 | Show `waker report`: evidence on disk, `kick 0: PARTIAL`, `kick 1: DONE` |
| 0:42–0:50 | "One install: `pip install waker-ai`. Blind hidden tests optional." |
| 0:50–0:60 | GitHub + PyPI URLs, slogan |

Keep the terminal font large; cut dead time; show the **red -> green** transition
because that is the product.

## Upload

- YouTube: **Unlisted**, title `waker-ai — 60s demo`, paste the URL into Agensi's
  "Demo video URL".
- Or Loom: record and copy the share link.
- Agensi screenshots can keep the static PNGs; the video is the moving proof.

## Notes

- The demo repo is created in `%TEMP%`; nothing in your real projects is touched.
- No model/API cost: the fake agent is a local script.
- If you want a pure slideshow fallback, `docs/demo.gif` can be converted to MP4
  with ffmpeg (`winget install Gyan.FFmpeg -e`), but a real terminal recording
  converts better.
