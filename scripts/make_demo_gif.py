"""Generate the README demo GIF with Pillow.

Run: python scripts/make_demo_gif.py
Output: docs/demo.gif
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1000, 560
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
    draw.rounded_rectangle((24, 24, W - 24, H - 24), radius=14, fill=PANEL, outline=BORDER, width=2)
    draw.line((24, 68, W - 24, 68), fill=BORDER, width=1)
    for index, color in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        cx = 50 + index * 22
        draw.ellipse((cx, 38, cx + 12, 50), fill=color)
    draw.text((130, 34), title, font=font(16, True), fill=MUTED)


def draw_bar(draw, x, y, width, height, done, total):
    draw.rounded_rectangle((x, y, x + width, y + height), radius=height // 2, fill=(33, 38, 45))
    if total:
        filled = int(width * done / total)
        color = GREEN if done == total else (YELLOW if done else RED)
        if filled:
            draw.rounded_rectangle((x, y, x + filled, y + height), radius=height // 2, fill=color)


def frame_title() -> Image.Image:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    draw_window(draw, "waker-ai")
    draw.text((70, 150), "waker-ai", font=font(64, True), fill=TEXT)
    draw.text(
        (70, 240),
        "Never let your AI coding agent",
        font=font(30), fill=CYAN,
    )
    draw.text((70, 282), "sleep on the job again.", font=font(30), fill=CYAN)
    draw.text(
        (70, 370),
        "Agent claims. Waker verifies. The disk decides.",
        font=font(20), fill=MUTED,
    )
    draw_bar(draw, 70, 440, 420, 14, 0, 3)
    draw.text((70, 480), "github.com/khoacat12345/waker-ai", font=font(18), fill=GREEN)
    return image


def frame_command() -> Image.Image:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    draw_window(draw, "PowerShell - waker")
    lines = [
        (100, "[waker]  $  waker run --tasks .waker/tasks.yaml", TEXT),
        (140, "            --adapter opencode", TEXT),
        (180, '            --test "pytest -q" --max-kicks 5', TEXT),
        (220, "            --max-cost 0.50", TEXT),
        (300, "[waker]  run 7f3a started  ·  session ses_waker_7f3a", CYAN),
        (340, "[waker]  gates: git diff ∩ scope + verify exit 0", MUTED),
        (380, "[waker]  watchdog: TAMPER · FALSE_DONE · FROZEN · THRASH", MUTED),
        (420, "[waker]  every wake resumes the same session", MUTED),
    ]
    for y, text, color in lines:
        draw.text((70, y), text, font=font(19), fill=color)
    return image


def frame_status(done: int, kick: int, test: str, rows: list[tuple[str, str, str, str]]) -> Image.Image:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    draw_window(draw, f"waker · run 7f3a")

    percent = int(round(100 * done / 3))
    draw.text((60, 92), f"run 7f3a · {done}/3 — {percent}%", font=font(24, True), fill=TEXT)
    draw_bar(draw, 60, 132, 560, 16, done, 3)
    draw.text((650, 126), f"kick {kick}/5", font=font(18, True), fill=YELLOW)
    test_color = GREEN if test == "PASS" else RED
    draw.text((790, 126), f"test {test}", font=font(18, True), fill=test_color)

    header = (60, 190)
    draw.text(header, "   TASK                    EVIDENCE                    GATE", font=font(16, True), fill=MUTED)
    y = 226
    for mark, task, evidence, gate in rows:
        color = GREEN if mark == "[x]" else (RED if mark == "[!]" else MUTED)
        draw.text((60, y), mark, font=font(19, True), fill=color)
        draw.text((110, y), task, font=font(19), fill=TEXT)
        draw.text((430, y), evidence, font=font(18), fill=MUTED)
        gate_color = GREEN if gate == "pass" else (RED if gate == "fail" else MUTED)
        draw.text((770, y), gate, font=font(18, True), fill=gate_color)
        y += 42

    draw.line((60, 400, W - 60, 400), fill=BORDER, width=1)
    draw.text((60, 420), "diagnosis: DONE → report written" if done == 3 else "diagnosis: PARTIAL → wake the agent", font=font(19), fill=CYAN)
    draw.text((60, 460), "every claim is backed by a file and an exit code", font=font(17), fill=MUTED)
    return image


def frame_blind() -> Image.Image:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    draw_window(draw, "waker · blind evaluation")
    lines = [
        (100, "$ waker vault validate --vault 9f3a...", TEXT),
        (140, "OK   auth   tests=12   baseline=red   flaky=False", GREEN),
        (210, "worker sees : public_api + public smoke tests", CYAN),
        (250, "worker never: hidden suite / vault path / source", CYAN),
        (320, "DONE requires public smoke + hidden 12/12", TEXT),
        (370, "failure: hidden://auth/test_3: AssertionError: ...", YELLOW),
        (410, "no source · no paths · no locals", MUTED),
    ]
    for y, text, color in lines:
        draw.text((70, y), text, font=font(19), fill=color)
    return image


def frame_report() -> Image.Image:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    draw_window(draw, "report.md")
    lines = [
        (110, "# waker run 7f3a — DONE", TEXT),
        (160, "3/3 tasks with evidence on disk", GREEN),
        (200, "pytest exit 0 · tests unchanged (no TAMPER)", GREEN),
        (240, "2 kicks · $0.0030 · 45s", YELLOW),
        (300, "kick 0: PARTIAL   (agent stopped at 1/3)", MUTED),
        (340, "kick 1: FALSE_DONE (claimed done, tests red)", MUTED),
        (380, "kick 2: DONE", GREEN),
        (450, "github.com/khoacat12345/waker-ai", CYAN),
    ]
    for y, text, color in lines:
        draw.text((70, y), text, font=font(21), fill=color)
    return image


def main() -> None:
    frames = [
        frame_title(),
        frame_command(),
        frame_status(0, 0, "FAIL", [
            ("[ ]", "T1  Auth module", "— no diff", "fail"),
            ("[ ]", "T2  Payment webhook", "— no diff", "fail"),
            ("[ ]", "T3  API docs", "— no diff", "—"),
        ]),
        frame_status(1, 1, "FAIL", [
            ("[x]", "T1  Auth module", "src/auth/guard.py", "pass"),
            ("[!]", "T2  Payment webhook", "— no diff", "fail"),
            ("[ ]", "T3  API docs", "— no diff", "—"),
        ]),
        frame_status(2, 2, "FAIL", [
            ("[x]", "T1  Auth module", "src/auth/guard.py", "pass"),
            ("[x]", "T2  Payment webhook", "src/pay/api.py", "pass"),
            ("[!]", "T3  API docs", "— no diff", "fail"),
        ]),
        frame_status(3, 2, "PASS", [
            ("[x]", "T1  Auth module", "src/auth/guard.py", "pass"),
            ("[x]", "T2  Payment webhook", "src/pay/api.py", "pass"),
            ("[x]", "T3  API docs", "docs/README.md", "pass"),
        ]),
        frame_blind(),
        frame_report(),
    ]
    durations = [1600, 1600, 1400, 1400, 1400, 2400, 2000, 2200]
    out = Path("docs/demo.gif")
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
    )
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
