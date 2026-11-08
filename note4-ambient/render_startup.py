from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
SCENES = (
    ("garden", "温室晨光", False),
    ("departures", "夜间启程", True),
    ("voices", "远方人声", True),
    ("afternoon", "午后原野", False),
    ("night-bus", "雨夜巴士", True),
    ("shoreline", "月下海岸", True),
    ("glass", "玻璃棱镜", False),
    ("tides", "长潮呼吸", False),
    ("rain-street", "雨中街道", False),
    ("cafe", "咖啡馆午后", False),
    ("city-voices", "街头人声", False),
    ("midnight-road", "午夜公路", True),
)
FONT = "/System/Library/Fonts/STHeiti Medium.ttc"
LATIN = ImageFont.truetype(FONT, 29)
CHINESE = ImageFont.truetype(FONT, 54)
SMALL = ImageFont.truetype(FONT, 27)


def render(name, title, subtitle, night):
    source = ROOT.parent / "ambient-gui/covers" / f"{name}.png"
    image = Image.open(source).convert("L").resize((1200, 900), Image.Resampling.LANCZOS)
    mask = Image.new("L", image.size, 0)
    pixels = mask.load()
    for y in range(570, 900):
        alpha = round(235 * (y - 570) / 330)
        for x in range(1200):
            pixels[x, y] = alpha
    image = Image.composite(Image.new("L", image.size, 20 if night else 215), image, mask)
    draw = ImageDraw.Draw(image)
    ink = 238 if night else 64
    for text, font, y, fill in (("A M B   A T E L I E R", LATIN, 666, 185 if night else 107), (title, CHINESE, 718, ink), (subtitle, SMALL, 795, 190 if night else 103)):
        width = draw.textlength(text, font=font)
        draw.text(((1200 - width) / 2, y), text, font=font, fill=fill)
    for i, height in enumerate((8, 15, 24, 34, 24, 15, 8)):
        x = 568 + i * 11
        draw.rounded_rectangle((x, 660 - height // 2, x + 4, 660 + height // 2), radius=2, fill=211 if night else 116)
    image = image.resize((400, 300), Image.Resampling.LANCZOS)
    assert image.size == (400, 300) and image.mode == "L"
    assert len(image.getcolors(256)) > 200
    return image


output = ROOT / "assets"
output.mkdir(exist_ok=True)
render("garden", "正在准备第一段音乐", "启动画面已就绪 · 音乐即将开始", False).save(output / "startup.png", optimize=True)
for name, title, night in SCENES:
    subtitle = "实地录音 · 准备完整长音轨" if name in {"rain-street", "cafe", "city-voices", "midnight-road"} else "新随机种子 · 准备好后自动播放"
    render(name, f"正在生成 · {title}", subtitle, night).save(output / f"loading-{name}.png", optimize=True)
print("generated startup and 12 preset loading screens")
