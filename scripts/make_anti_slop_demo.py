"""Generate the Waker v2.0 anti-slop terminal demo GIF.

Data source: waker-smoke/.waker/runs/b81c627e
Run: python scripts/make_anti_slop_demo.py
Output: docs/anti-slop-demo.gif
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1180, 680
BG = (8, 12, 18)
PANEL = (18, 24, 33)
PANEL_2 = (22, 30, 41)
BORDER = (48, 58, 73)
TEXT = (213, 222, 233)
MUTED = (139, 151, 168)
DIM = (92, 105, 122)
GREEN = (63, 185, 80)
RED = (248, 81, 73)
YELLOW = (210, 153, 34)
CYAN = (88, 166, 255)
MAGENTA = (188, 140, 255)

FONT_REG = "C:/Windows/Fonts/consola.ttf"
FONT_BOLD = "C:/Windows/Fonts/consolab.ttf"


def font(size: int, bold: bool = False):
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)
    except OSError:
        return ImageFont.load_default()


def window(draw: ImageDraw.ImageDraw, subtitle: str) -> None:
    draw.rounded_rectangle((20, 18, W - 20, H - 18), radius=16, fill=PANEL, outline=BORDER, width=2)
    draw.rounded_rectangle((20, 18, W - 20, 75), radius=16, fill=PANEL_2, outline=BORDER, width=2)
    draw.rectangle((20, 62, W - 20, 78), fill=PANEL_2)
    for index, color in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        cx = 48 + index * 25
        draw.ellipse((cx, 37, cx + 14, 51), fill=color)
    draw.text((140, 32), "waker v2.0.0  |  anti-slop watchdog", font=font(17, True), fill=TEXT)
    draw.text((W - 32 - draw.textlength(subtitle, font=font(14)), 38), subtitle, font=font(14), fill=MUTED)


def line(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, color=TEXT, size=17, bold=False) -> None:
    draw.text((x, y), text, font=font(size, bold), fill=color)


def section(draw: ImageDraw.ImageDraw, y: int, title: str, color=CYAN) -> None:
    draw.text((64, y), title, font=font(15, True), fill=color)
    draw.line((64, y + 24, W - 64, y + 24), fill=BORDER, width=1)


def pill(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, color: tuple[int, int, int]) -> None:
    width = int(draw.textlength(text, font=font(14, True))) + 24
    draw.rounded_rectangle((x, y, x + width, y + 27), radius=13, fill=(23, 32, 43), outline=color, width=1)
    draw.text((x + 12, y + 5), text, font=font(14, True), fill=color)


def header(draw: ImageDraw.ImageDraw, kick: str, status: str, color: tuple[int, int, int], score: str, grade: str) -> None:
    line(draw, 64, 98, f"RUN b81c627e", MUTED, 15, True)
    line(draw, W - 64 - draw.textlength("waker-smoke  |  T1 Todo CLI", font=font(15)), 98, "waker-smoke  |  T1 Todo CLI", MUTED, 15)
    line(draw, 64, 134, f"KICK {kick}/5", TEXT, 25, True)
    pill(draw, 230, 133, status, color)
    line(draw, 390, 137, f"pytest PASS", GREEN, 17, True)
    line(draw, W - 64 - draw.textlength(f"anti-slop  {score}/100  Grade {grade}", font=font(17, True)), 137, f"anti-slop  {score}/100  Grade {grade}", color, 17, True)
    draw.line((64, 178, W - 64, 178), fill=BORDER, width=1)


def base(subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    window(draw, subtitle)
    return image, draw


def frame_intro() -> Image.Image:
    image, draw = base("run b81c627e")
    line(draw, 64, 112, "A tests-green turn is not enough.", TEXT, 30, True)
    line(draw, 64, 154, "The AST watchdog is watching the diff.", CYAN, 22)
    section(draw, 212, "TERMINAL  |  waker-smoke")
    line(draw, 64, 252, "$ waker run --tasks .waker/tasks.yaml", GREEN, 18)
    line(draw, 64, 282, '        --test "python -m pytest -q" --max-kicks 5', GREEN, 18)
    line(draw, 64, 330, "T1  Implement a Todo CLI in src/todo", TEXT, 18)
    line(draw, 64, 360, "    scope: __init__.py  __main__.py  cli.py  store.py", MUTED, 17)
    line(draw, 64, 390, "    verify: python -m pytest -q", MUTED, 17)
    pill(draw, 64, 442, "DEFAULT-ON", GREEN)
    pill(draw, 176, 442, "stdlib only", CYAN)
    pill(draw, 286, 442, "no LLM judge", MAGENTA)
    line(draw, 64, 510, "Watch the next three turns:", MUTED, 18)
    line(draw, 64, 548, "kick 0  SLOP", RED, 22, True)
    line(draw, 225, 548, "->", DIM, 22, True)
    line(draw, 272, 548, "kick 1  SLOP", RED, 22, True)
    line(draw, 433, 548, "->", DIM, 22, True)
    line(draw, 480, 548, "kick 2  DONE", GREEN, 22, True)
    line(draw, 64, 610, "Agent claims. Waker verifies. The AST decides.", MUTED, 16)
    return image


def findings_block(
    draw: ImageDraw.ImageDraw,
    y: int,
    lines: list[tuple[str, str]],
) -> int:
    for rule, text in lines:
        color = RED if rule.startswith("ERROR") else YELLOW
        line(draw, 64, y, rule, color, 16, True)
        line(draw, 244, y, text, TEXT, 16)
        y += 27
    return y


def frame_slop_0() -> Image.Image:
    image, draw = base("kick 0  |  tests pass, slop blocks DONE")
    header(draw, "0", "SLOP", RED, "57", "F")
    line(draw, 64, 198, "agent: \"All tasks completed.\"  pytest: PASS", GREEN, 18)
    line(draw, 64, 226, "anti-slop: 4 errors, 1 warning", RED, 18, True)
    section(draw, 258, "BLOCKING FINDINGS", RED)
    y = findings_block(
        draw,
        294,
        [
            ("ERROR  TYPE002", "src/todo/store.py:22   _load returns Any/object"),
            ("ERROR  TYPE002", "src/todo/store.py:40   add returns Any/object"),
            ("ERROR  TYPE002", "src/todo/store.py:53   list returns Any/object"),
            ("ERROR  TYPE002", "src/todo/store.py:57   complete returns Any/object"),
            ("WARNING TYPE006", "src/todo/store.py:29   ad-hoc isinstance narrowing"),
        ],
    )
    line(draw, 64, y + 12, "=> Diagnosis.SLOP   DONE denied", RED, 20, True)
    line(draw, 64, y + 44, "wake prompt queued with rule IDs, file:line, message, recipe", MUTED, 16)
    return image


def frame_slop_1() -> Image.Image:
    image, draw = base("kick 1  |  fewer errors, still blocking")
    header(draw, "1", "SLOP", RED, "66", "D")
    line(draw, 64, 198, "agent fixed 4 TYPE002 returns; pytest still PASS", GREEN, 18)
    line(draw, 64, 226, "anti-slop: 1 error, 8 warnings", RED, 18, True)
    section(draw, 258, "BLOCKING FINDINGS", RED)
    y = findings_block(
        draw,
        294,
        [
            ("ERROR  TYPE001", "src/todo/store.py:20   raw uses evidence-free `object`"),
            ("WARNING TYPE006", "src/todo/store.py:22   manual isinstance type switch"),
            ("WARNING TYPE012", "src/todo/store.py:22   6 isinstance checks, no union"),
            ("WARNING TYPE006", "src/todo/store.py:30   ad-hoc narrowing"),
        ],
    )
    line(draw, 64, y + 12, "=> Diagnosis.SLOP   not DONE yet", RED, 20, True)
    line(draw, 64, y + 44, "next wake prompt targets the remaining evidence hole", MUTED, 16)
    return image


def frame_done() -> Image.Image:
    image, draw = base("kick 2  |  fix accepted")
    header(draw, "2", "DONE", GREEN, "76", "C")
    line(draw, 64, 198, "agent removed the blocking evidence holes", GREEN, 18)
    line(draw, 64, 226, "anti-slop: 0 errors, 8 advisory warnings", GREEN, 18, True)
    section(draw, 258, "RESULT", GREEN)
    line(draw, 64, 296, "[OK]  T1 Todo CLI complete", GREEN, 19, True)
    line(draw, 64, 326, "      evidence: 4 files in scope + verify exit 0", MUTED, 17)
    line(draw, 64, 356, "[OK]  pytest PASS", GREEN, 19, True)
    line(draw, 64, 386, "[OK]  anti-slop 76/100  Grade C  0 errors", GREEN, 19, True)
    pill(draw, 64, 438, "DONE", GREEN)
    line(draw, 170, 443, "report.md committed   |   2 kicks   |   $0.0069", TEXT, 17, True)
    section(draw, 500, "WHY THIS DEMO MATTERS", CYAN)
    line(draw, 64, 538, "Tests green is necessary, not sufficient.", TEXT, 20)
    line(draw, 64, 572, "The watchdog rejects fake completion and wakes the same session.", MUTED, 17)
    line(draw, 64, 602, "Every fix is tied to an AST fact, not a model's opinion.", MUTED, 17)
    line(draw, W - 64 - draw.textlength("github.com/khoacat12345/waker-ai", font=font(15)), 620, "github.com/khoacat12345/waker-ai", GREEN, 15)
    return image


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "docs" / "demo.gif"
    output.parent.mkdir(parents=True, exist_ok=True)
    frames = [frame_intro(), frame_slop_0(), frame_slop_1(), frame_done()]
    durations = [2200, 2800, 2800, 3800]
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(output)


if __name__ == "__main__":
    main()
