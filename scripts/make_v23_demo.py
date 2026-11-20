"""Generate the waker v2.3 storyboard GIF.

Story: chatbox prompt -> Grill-Me -> phase plan -> copy command -> Cyber-Deck
with a moving border beam -> anti-slop attempt 2 -> DONE -> install CTA.

Run:
    python scripts/make_v23_demo.py
Output:
    docs/demo-v23.gif
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 700
BG = (8, 12, 18)
PANEL = (18, 24, 33)
PANEL_2 = (21, 29, 40)
PANEL_3 = (25, 34, 46)
BORDER = (48, 58, 73)
TEXT = (213, 222, 233)
MUTED = (139, 151, 168)
DIM = (92, 105, 122)
GREEN = (63, 185, 80)
RED = (248, 81, 73)
YELLOW = (210, 153, 34)
ORANGE = (255, 158, 100)
CYAN = (88, 166, 255)
NEON = (0, 220, 255)
MAGENTA = (188, 140, 255)

FONT_REG = "C:/Windows/Fonts/consola.ttf"
FONT_BOLD = "C:/Windows/Fonts/consolab.ttf"


@lru_cache(maxsize=64)
def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)
    except OSError:
        return ImageFont.load_default()


def text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: str,
    color: tuple[int, int, int] = TEXT,
    size: int = 16,
    bold: bool = False,
) -> None:
    draw.text(xy, value, font=font(size, bold), fill=color)


def wrap(
    draw: ImageDraw.ImageDraw,
    value: str,
    size: int,
    max_width: int,
    bold: bool = False,
) -> list[str]:
    words = value.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font(size, bold)) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def window_chrome(draw: ImageDraw.ImageDraw, title: str, subtitle: str = "") -> None:
    draw.rounded_rectangle((18, 16, W - 18, H - 16), radius=16, fill=PANEL, outline=BORDER, width=2)
    draw.rounded_rectangle((18, 16, W - 18, 72), radius=16, fill=PANEL_2, outline=BORDER, width=2)
    draw.rectangle((18, 58, W - 18, 74), fill=PANEL_2)
    for index, color in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        cx = 46 + index * 24
        draw.ellipse((cx, 35, cx + 13, 48), fill=color)
    text(draw, (135, 29), title, TEXT, 16, True)
    if subtitle:
        width = int(draw.textlength(subtitle, font=font(13)))
        text(draw, (W - 38 - width, 34), subtitle, MUTED, 13)


def panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    color: tuple[int, int, int] = BORDER,
    fill: tuple[int, int, int] = PANEL,
) -> None:
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=10, fill=fill, outline=color, width=2)
    draw.line((x0 + 12, y0 + 27, x1 - 12, y0 + 27), fill=color, width=1)
    text(draw, (x0 + 14, y0 + 7), title, color if color != BORDER else MUTED, 14, True)


def bubble(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    body: str,
    who: str,
    color: tuple[int, int, int],
) -> int:
    lines = wrap(draw, body, 17, width - 32)
    height = 22 + len(lines) * 25
    draw.rounded_rectangle((x, y, x + width, y + height), radius=12, fill=PANEL_3, outline=color, width=1)
    text(draw, (x + 16, y + 9), who, color, 13, True)
    for index, line in enumerate(lines):
        text(draw, (x + 16, y + 31 + index * 25), line, TEXT, 17)
    return y + height


def chat_frame(stage: int, click: bool = False, copied: bool = False) -> Image.Image:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    window_chrome(draw, "OpenCode  /  waker", "chatbox -> contract -> supervisor")
    panel(draw, (44, 90, W - 44, H - 40), "waker — chat", BORDER, PANEL)

    user_prompt = "build Auth JWT + Stripe payments, run overnight, include tests"
    y = 112
    y = bubble(draw, 690, y, 450, user_prompt, "you", CYAN) + 18

    if stage >= 1:
        question = (
            "Before I freeze the contract, I need 2 blocking answers:\n"
            "1. Scope: src/auth/** + src/payments/**?\n"
            "2. Verify: pytest tests/auth tests/payments -q?"
        )
        y = bubble(draw, 70, y + 18, 640, question, "waker · Grill-Me", ORANGE) + 18
    if stage >= 2:
        y = bubble(draw, 690, y, 450, "đúng rồi, ok", "you", CYAN) + 18
    if stage == 2:
        plan = (
            "Phase plan · profile overnight (8h)\n"
            "P1  Auth & JWT       45m\n"
            "P2  Stripe Payment   2h\n"
            "P3  E2E & Security   30m\n\n"
            "Gõ ok / 1 / chạy để bắt đầu."
        )
        panel(draw, (70, 430, W - 70, 640), "phase plan · human freeze", CYAN, PANEL_2)
        for index, line in enumerate(plan.splitlines()):
            color = GREEN if line.startswith("P") else (MUTED if index < 6 else TEXT)
            text(draw, (90, 460 + index * 18), line, color, 15, line.startswith("Phase"))
        text(draw, (70, 650), "Small task? silent-pass. Large task? phase plan + human freeze.", MUTED, 14)
    if stage >= 3:
        panel(draw, (70, 430, W - 70, 505), "waker is working", GREEN, PANEL_2)
        text(draw, (90, 447), "waker watch --repo . --run 7f3a", TEXT, 17, True)
        button = (950, 443, 1060, 479)
        draw.rounded_rectangle(button, radius=8, fill=(34, 48, 62), outline=CYAN, width=1)
        text(draw, (976, 451), "Copy", CYAN, 14, True)
        text(draw, (70, 525), "Contract frozen: P1 Auth · P2 Stripe · P3 E2E", MUTED, 14)
        if click:
            x, y0 = 1010, 486
            draw.polygon([(x, y0), (x, y0 + 15), (x + 4, y0 + 12), (x + 9, y0 + 20), (x + 14, y0 + 17), (x + 8, y0 + 10), (x + 14, y0 + 8)], fill=TEXT)
        if copied:
            draw.rounded_rectangle((850, 555, 1080, 590), radius=8, fill=(27, 46, 42), outline=GREEN, width=1)
            text(draw, (868, 563), "Copied to clipboard", GREEN, 15, True)
        text(draw, (70, 620), "Chatbox stays responsive; Waker runs in the background.", MUTED, 15)
    if stage < 2:
        text(draw, (70, 630), "Grill-Me only fires when blocking info is missing.", MUTED, 15)
    text(draw, (W - 38 - 410, H - 24), "waker-ai · never let an agent sleep on the job", DIM, 13)
    return image


def perimeter(x0: int, y0: int, x1: int, y1: int, step: int = 5) -> list[tuple[int, int]]:
    points: list[tuple[int, int]] = []
    for x in range(x0, x1, step):
        points.append((x, y0))
    for y in range(y0, y1, step):
        points.append((x1, y))
    for x in range(x1, x0, -step):
        points.append((x, y1))
    for y in range(y1, y0, -step):
        points.append((x0, y))
    return points


def draw_beam(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    frame: int,
    active: bool,
) -> None:
    x0, y0, x1, y1 = box
    draw.rectangle(box, outline=BORDER, width=2)
    if not active:
        draw.rectangle(box, outline=GREEN, width=2)
        return
    points = perimeter(x0, y0, x1, y1)
    phase = int(frame * 5) % len(points)
    for tail in range(13, -1, -1):
        px, py = points[(phase - tail) % len(points)]
        if tail == 0:
            color, radius = (255, 255, 255), 6
        elif tail == 1:
            color, radius = NEON, 5
        elif tail <= 4:
            color, radius = CYAN, 4
        elif tail <= 8:
            color, radius = (125, 207, 255), 3
        else:
            color, radius = (61, 89, 161), 2
        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=color)


def simple_bar(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, pct: float, color: tuple[int, int, int]) -> None:
    draw.rounded_rectangle((x, y, x + width, y + 10), radius=5, fill=(33, 40, 52))
    filled = int(width * max(0.0, min(1.0, pct)))
    if filled:
        draw.rounded_rectangle((x, y, x + filled, y + 10), radius=5, fill=color)


def deck_frame(frame: int, final: bool = False) -> Image.Image:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    window_chrome(draw, "PowerShell  /  waker watch", "waker · Cyber-Deck")
    deck = (34, 86, W - 34, H - 30)
    draw_beam(draw, deck, frame, active=not final)
    draw.rounded_rectangle((48, 100, W - 48, H - 44), radius=8, fill=PANEL, outline=BORDER, width=1)

    # Header and phase row.
    text(draw, (66, 112), "WAKER CYBER-DECK", CYAN, 17, True)
    text(draw, (265, 114), "v2.3  ·  run 7f3a  ·  02:31", MUTED, 13)
    text(draw, (W - 380, 114), "Agent: OpenCode · deepseek-v4.1-flash", MUTED, 13)
    text(draw, (66, 140), "Goal: build Auth JWT + Stripe payments", TEXT, 14)
    phase_pct = 0.62 + (0.2 * min(frame, 30) / 30)
    if final:
        phase_pct = 1.0
    phase_color = GREEN if phase_pct < 0.8 else YELLOW
    if final:
        phase_color = GREEN
    text(draw, (66, 168), "PHASE 2/3  Stripe Payment", phase_color, 15, True)
    text(draw, (330, 169), f"01:31:30 / 02:00:00", MUTED, 13)
    simple_bar(draw, 555, 170, 100, phase_pct, phase_color)
    text(draw, (675, 167), f"{int(phase_pct * 100)}%", phase_color, 13, True)

    # Task panel.
    panel(draw, (62, 200, 748, 362), "PIPELINE TASKS", BORDER, PANEL)
    rows = [
        ("[x]", "T1  Auth & JWT", "100%", "C", "0err · 2warn"),
        ("[x]" if final else "[~]", "T2  Stripe Payment", "100%" if final else "72%", "C" if final else "-", "0err · 8warn"),
        ("[x]" if final else "[ ]", "T3  E2E & Security", "100%" if final else "0%", "C" if final else "-", "0err · 1warn"),
    ]
    for index, (icon, name, pct, grade, warn) in enumerate(rows):
        y = 236 + index * 36
        color = GREEN if icon == "[x]" else (YELLOW if icon == "[~]" else MUTED)
        text(draw, (80, y), icon, color, 16, True)
        text(draw, (112, y), name, TEXT, 15)
        text(draw, (555, y), pct, GREEN if pct == "100%" else YELLOW, 14, True)
        text(draw, (625, y), grade, MUTED, 13)
        text(draw, (675, y), warn, YELLOW if "8warn" in warn else MUTED, 12)

    # Telemetry panel.
    panel(draw, (768, 200, W - 62, 362), "WATCHDOG TELEMETRY", BORDER, PANEL)
    score = 76 if final else 57
    score_color = GREEN if final else RED
    text(draw, (786, 235), "CLEANLINESS", MUTED, 12)
    simple_bar(draw, 910, 236, 110, score / 100, score_color)
    text(draw, (1030, 232), f"{score}/100 [C]", score_color, 13, True)
    text(draw, (786, 260), "KICKS", MUTED, 12)
    text(draw, (910, 258), "2/5" if final else "1/5", GREEN if final else YELLOW, 13)
    text(draw, (786, 284), "TEST SUITE", MUTED, 12)
    text(draw, (910, 282), "PASS · exit 0", GREEN, 13)
    text(draw, (786, 308), "COST", MUTED, 12)
    text(draw, (910, 306), "$0.0069" if final else "$0.0034", ORANGE, 13)
    text(draw, (786, 332), "STATUS", MUTED, 12)
    text(draw, (910, 330), "DONE" if final else "RUNNING", GREEN if final else CYAN, 13, True)
    text(draw, (786, 353), "ANTI-SLOP", MUTED, 12)
    text(draw, (910, 351), "TYPE006 x7 · TYPE012 x1", YELLOW, 12)

    # Event stream.
    panel(draw, (62, 380, W - 62, 588), "REALTIME EVENT STREAM", BORDER, PANEL)
    events = (
        [
            ("07:53:42", "SLOP", "kick 0 · TYPE002 x4 in store.py", RED),
            ("07:54:21", "SLOP", "kick 1 · TYPE001 remains in store.py", RED),
            ("07:55:02", "DONE", "attempt 2 · 0 errors · report.md committed", GREEN),
        ]
        if final
        else [
            ("07:53:42", "SLOP", "kick 0 · TYPE002 x4 in store.py", RED),
            ("07:54:21", "SLOP", "kick 1 · TYPE001 remains in store.py", RED),
            ("  ...   ", "WAIT", "evaluating next AST boundary", MUTED),
        ]
    )
    for index, (ts, label, message, color) in enumerate(events):
        y = 415 + index * 27
        text(draw, (80, y), ts, MUTED, 13)
        text(draw, (178, y), label, color, 13, True)
        text(draw, (250, y), message, TEXT, 13)
    if final:
        text(draw, (80, 510), "anti-slop: attempt 2 accepted · Grade C · 76/100", GREEN, 15, True)
    else:
        text(draw, (80, 510), "tests green is necessary, not sufficient", MUTED, 14)
    footer = "[q] Quit   [p] Pause   [v] Diff   [l] Full Log"
    text(draw, (80, 548), footer, MUTED, 13)
    text(draw, (W - 200, 548), "waker 2.3.0", DIM, 12)
    return image


def cta_frame() -> Image.Image:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    window_chrome(draw, "waker-ai v2.3.0", "release demo")
    text(draw, (84, 130), "Phase budgets.", CYAN, 42, True)
    text(draw, (84, 190), "Resume extend. Anti-slop.", GREEN, 36, True)
    text(draw, (84, 270), "Waker watches the disk, not the agent's words.", TEXT, 20)
    panel(draw, (84, 350, 970, 475), "INSTALL", GREEN, PANEL_2)
    text(draw, (110, 382), "pip install --upgrade waker-ai==2.3.0", GREEN, 20, True)
    text(draw, (110, 418), "waker plan --phases auto --profile overnight", CYAN, 16)
    text(draw, (110, 445), "waker watch --repo . --run <id>", MUTED, 16)
    text(draw, (84, 530), "github.com/khoacat12345/waker-ai", TEXT, 18, True)
    text(draw, (84, 562), "PyPI  ·  v2.3.0  ·  phase budget enforcement", YELLOW, 16)
    simple_bar(draw, 84, 620, 900, 1.0, GREEN)
    text(draw, (84, 646), "Agent claims. Waker verifies. The disk decides.", MUTED, 16)
    return image


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "docs" / "demo-v23.gif"
    output.parent.mkdir(parents=True, exist_ok=True)
    frames: list[Image.Image] = []
    durations: list[int] = []

    for stage, duration in ((0, 1200), (1, 1500), (2, 1800), (3, 1300)):
        frames.append(chat_frame(stage))
        durations.append(duration)
    frames.append(chat_frame(3, click=True))
    durations.append(350)
    frames.append(chat_frame(3, click=True, copied=True))
    durations.append(900)

    for index in range(48):
        frames.append(deck_frame(index, final=False))
        durations.append(100)
    for index in range(10):
        frames.append(deck_frame(index, final=True))
        durations.append(140)
    frames.append(cta_frame())
    durations.append(3000)

    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
    )
    print(f"wrote {output} ({output.stat().st_size} bytes, {len(frames)} frames)")


if __name__ == "__main__":
    main()
