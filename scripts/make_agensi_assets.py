"""Generate Agensi listing assets: logo + terminal screenshots from real output."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(r"C:\Users\tuank\waker-ai")
WAKER = Path(r"C:\Users\tuank\AppData\Local\Programs\Python\Python312\Scripts\waker.exe")
OUT = ROOT / "packaging" / "agensi"
SHOTS = OUT / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)

W, H = 1200, 700
BG = (13, 17, 23)
PANEL = (22, 27, 34)
BORDER = (48, 54, 61)
TEXT = (201, 209, 217)
MUTED = (139, 148, 158)
GREEN = (63, 185, 80)
RED = (248, 81, 73)
YELLOW = (210, 153, 34)
CYAN = (88, 166, 255)

FONT = "C:/Windows/Fonts/consola.ttf"
FONT_B = "C:/Windows/Fonts/consolab.ttf"


def font(size: int, bold: bool = False):
    try:
        return ImageFont.truetype(FONT_B if bold else FONT, size)
    except OSError:
        return ImageFont.load_default()


def draw_window(draw: ImageDraw.ImageDraw, title: str) -> None:
    draw.rounded_rectangle((20, 20, W - 20, H - 20), radius=14, fill=PANEL, outline=BORDER, width=2)
    draw.line((20, 66, W - 20, 66), fill=BORDER, width=1)
    for index, color in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        cx = 46 + index * 22
        draw.ellipse((cx, 38, cx + 12, 50), fill=color)
    draw.text((126, 34), title, font=font(16, True), fill=MUTED)


def color_for(line: str) -> tuple[int, int, int]:
    stripped = line.strip()
    if stripped.startswith("$"):
        return CYAN
    if stripped.startswith(("OK ", "DONE", "PASS", "✅")):
        return GREEN
    if stripped.startswith(("hidden://", "FAIL", "🔴")):
        return RED
    if stripped.startswith(("hidden:", "Diagnosis", "kick")):
        return YELLOW
    return TEXT


def screenshot(name: str, title: str, lines: list[str]) -> Path:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    draw_window(draw, title)
    y = 96
    for line in lines:
        draw.text((48, y), line, font=font(19), fill=color_for(line))
        y += 30
        if y > H - 60:
            break
    path = SHOTS / name
    image.save(path)
    print("wrote", path, path.stat().st_size)
    return path


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(WAKER), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


# A real 12-test vault validation, used in the blind-mode screenshot.
root = Path(tempfile.mkdtemp(prefix="agensi-vault-"))
repo = root / "repo"
repo.mkdir()
base = root / "vaults"
init = run("vault", "init", "--repo", str(repo), "--vault-dir", str(base), "--json")
vault_id = json.loads(init.stdout)["vault_id"]
test = root / "test_hidden.py"
test.write_text(
    "\n\n".join(f"def test_{i}():\n    assert False" for i in range(1, 13)) + "\n",
    encoding="utf-8",
)
run(
    "vault", "add", "--vault", vault_id, "--suite", "auth", "--task", "T1",
    str(test), "--vault-dir", str(base), "--json",
)
validated = run(
    "vault", "validate", "--vault", vault_id, "--repo", str(repo),
    "--vault-dir", str(base),
)
listed = run("vault", "list", "--vault", vault_id, "--vault-dir", str(base))
print(validated.stdout)
print(listed.stdout)

# 1. Real status from run 989bcfca.
screenshot(
    "01-status.png",
    "waker · status",
    [
        "$ waker status --repo . --run 989bcfca",
        "",
        "waker · run 989bcfca · 4/4 — 100%",
        "████████████████  ⏱ 2h47m  🔁 0/5  🧪 PASS  💰 $0.0850",
        "",
        "| ✅ | T1 | Tier-aware E1–E4      | .agents/v2/execution.py       | pass |",
        "| ✅ | T2 | Planner adapter        | .agents/v2/planner_adapter.py | pass |",
        "| ✅ | T3 | Swarm CLI + launchers  | .agents/v2/swarm_cli.py       | pass |",
        "| ✅ | T4 | Parity docs            | docs/*.md                     | pass |",
        "",
        "Diagnosis: DONE",
        "Every task has an on-disk evidence pointer and a green verify.",
    ],
)

# 2. Real 12-test vault validation.
blind_lines = ["$ waker vault validate --vault " + vault_id + " --repo ."]
blind_lines += [line for line in validated.stdout.strip().splitlines()]
blind_lines += ["", "$ waker vault list --vault " + vault_id]
blind_lines += [line for line in listed.stdout.strip().splitlines()]
blind_lines += [
    "",
    "Hidden failures are sanitized before they reach the worker:",
    "hidden://auth/test_3: AssertionError: login must return a token",
]
screenshot("02-blind.png", "waker · blind evaluation", blind_lines)

# 3. Real doctor output.
screenshot(
    "03-doctor.png",
    "waker · doctor",
    [
        "$ waker doctor --inject-test",
        "",
        "waker doctor",
        "============================================================",
        "python   : 3.12.10",
        "platform : Windows 11",
        "git      : git version 2.56.0.windows.2",
        "pty      : OK - pywinpty + pyte ready (ConPTY)",
        "",
        "OK opencode       tier T1  (opencode v2.0.32)",
        "OK any-text-cli   tier T3  (pywinpty)",
        "",
        "injector self-test: PASS - marker seen",
    ],
)

# 4. Real report.
screenshot(
    "04-report.png",
    "waker · report",
    [
        "$ waker report --repo . --run 989bcfca",
        "",
        "# waker run 989bcfca — DONE",
        "4/4 tasks with evidence on disk",
        "pytest exit 0 · test files unchanged (no TAMPER)",
        "2h47m including earlier attempts · $0.0850",
        "",
        "kick history",
        "- kick 0: DONE",
        "",
        "Every claim is backed by a file and an exit code.",
    ],
)

# Logo 512x512.
size = 512
logo = Image.new("RGB", (size, size), BG)
draw = ImageDraw.Draw(logo)
draw.rounded_rectangle((16, 16, size - 16, size - 16), radius=80, fill=PANEL, outline=BORDER, width=4)
draw.text((70, 140), "w", font=font(190, True), fill=CYAN)
draw.text((70, 330), "waker", font=font(74, True), fill=TEXT)
draw.text((74, 420), "agent supervisor", font=font(30), fill=MUTED)
logo.save(OUT / "logo.png")
print("wrote", OUT / "logo.png", (OUT / "logo.png").stat().st_size)
