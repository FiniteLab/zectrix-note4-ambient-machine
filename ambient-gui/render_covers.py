#!/usr/bin/env python3
import math
import random
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

S = 3
W, H = 400, 300
SIZE = (W * S, H * S)
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "covers"
OUT.mkdir(exist_ok=True)
NAMES = ("garden", "departures", "voices", "afternoon", "night-bus", "shoreline", "glass", "tides")


def font(size, latin=False):
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ] if latin else [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, round(size * S))
    return ImageFont.load_default(size=round(size * S))


def gradient(top, bottom, size=SIZE):
    ramp = Image.linear_gradient("L").resize(size)
    return Image.composite(Image.new("L", size, bottom), Image.new("L", size, top), ramp)


def bezier(a, b, c, d, count=48):
    points = []
    for i in range(count + 1):
        t = i / count
        u = 1 - t
        points.append(tuple(u ** 3 * a[j] + 3 * u * u * t * b[j] + 3 * u * t * t * c[j] + t ** 3 * d[j] for j in (0, 1)))
    return points


class Canvas:
    def __init__(self, top, bottom, seed):
        self.image = gradient(top, bottom)
        self.rng = random.Random(seed)
        self.draw = ImageDraw.Draw(self.image)

    def sync(self):
        self.draw = ImageDraw.Draw(self.image)

    def ellipse(self, box, fill=None, outline=None, width=1):
        self.draw.ellipse(tuple(round(v * S) for v in box), fill=fill, outline=outline, width=max(1, round(width * S)))

    def rectangle(self, box, fill=None, outline=None, width=1, radius=0):
        box = tuple(round(v * S) for v in box)
        if radius:
            self.draw.rounded_rectangle(box, radius=round(radius * S), fill=fill, outline=outline, width=max(1, round(width * S)))
        else:
            self.draw.rectangle(box, fill=fill, outline=outline, width=max(1, round(width * S)))

    def line(self, points, fill, width=1):
        self.draw.line([(round(x * S), round(y * S)) for x, y in points], fill=fill, width=max(1, round(width * S)), joint="curve")

    def polygon(self, points, fill):
        self.draw.polygon([(round(x * S), round(y * S)) for x, y in points], fill=fill)

    def arc(self, box, start, end, fill, width=1):
        self.draw.arc(tuple(round(v * S) for v in box), start, end, fill=fill, width=max(1, round(width * S)))

    def text(self, x, y, text, size, fill=230, latin=False, tracking=0):
        face = font(size, latin)
        if tracking:
            for char in text:
                self.draw.text((round(x * S), round(y * S)), char, font=face, fill=fill, anchor="lt")
                x += self.draw.textlength(char, font=face) / S + tracking
        else:
            self.draw.text((round(x * S), round(y * S)), text, font=face, fill=fill, anchor="lt")

    def light(self, x, y, radius, value, stretch=1):
        mask = Image.new("L", SIZE, 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse(((x - radius) * S, (y - radius * stretch) * S, (x + radius) * S, (y + radius * stretch) * S), fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(radius * S * 0.58))
        self.image = Image.composite(Image.new("L", SIZE, value), self.image, mask)
        self.sync()

    def soft_polygon(self, points, value, blur=4):
        mask = Image.new("L", SIZE, 0)
        ImageDraw.Draw(mask).polygon([(round(x * S), round(y * S)) for x, y in points], fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(blur * S))
        self.image = Image.composite(Image.new("L", SIZE, value), self.image, mask)
        self.sync()

    def soft_ellipse(self, box, value, blur=4):
        mask = Image.new("L", SIZE, 0)
        ImageDraw.Draw(mask).ellipse(tuple(round(v * S) for v in box), fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(blur * S))
        self.image = Image.composite(Image.new("L", SIZE, value), self.image, mask)
        self.sync()

    def facet(self, points, top, bottom):
        mask = Image.new("L", SIZE, 0)
        ImageDraw.Draw(mask).polygon([(round(x * S), round(y * S)) for x, y in points], fill=255)
        self.image.paste(gradient(top, bottom), (0, 0), mask)
        self.sync()

    def ridge(self, y, roughness, fill, step=14):
        knots = [(x, y + self.rng.uniform(-roughness, roughness)) for x in range(-step, W + 2 * step, step)]
        points = []
        for a, b in zip(knots, knots[1:]):
            for j in range(6):
                t = j / 6
                points.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * (1 - math.cos(t * math.pi)) / 2))
        self.polygon(points + [(W + step, H), (-step, H)], fill)

    def grain(self, amount=3):
        noise = Image.frombytes("L", (W, H), self.rng.randbytes(W * H)).resize(SIZE, Image.Resampling.BILINEAR)
        noise = noise.point(lambda p: round(128 + (p - 128) * amount / 128))
        self.image = ImageChops.add(self.image, noise, offset=-128)
        self.sync()

    def texture(self, amount=12, blur=3):
        small = Image.frombytes("L", (80, 60), self.rng.randbytes(80 * 60))
        noise = small.resize(SIZE, Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(blur * S))
        noise = noise.point(lambda p: round(128 + (p - 128) * amount / 128))
        self.image = ImageChops.add(self.image, noise, offset=-128)
        self.sync()

    def vignette(self, strength=24):
        mask = Image.radial_gradient("L").resize(SIZE).point(lambda p: round(p * strength / 255))
        self.image = Image.composite(Image.new("L", SIZE, 0), self.image, mask)
        self.sync()

    def label(self, name, title, number):
        night = name in {"departures", "voices", "night-bus", "shoreline"}
        shade = Image.new("L", SIZE, 0)
        top = Image.linear_gradient("L").resize((W * S, 84 * S)).point(lambda p: round((255 - p) * 0.64))
        shade.paste(top, (0, 0))
        self.image = Image.composite(Image.new("L", SIZE, 20 if night else 229), self.image, shade)
        self.sync()
        self.text(20, 16, name.upper(), 6.6, 185 if night else 108, True, 1.1)
        self.text(20, 31.8, title, 16, 238 if night else 48)
        self.line([(20, 59), (42, 59)], 199 if night else 113, 1.2)
        self.text(337, 17, f"{number:02d} / 08", 6.5, 177 if night else 105, True, 0.4)
        self.image = self.image.resize((W, H), Image.Resampling.LANCZOS)
        self.image.save(OUT / f"{name}.png", optimize=True)


def leaf(c, x, y, length, width, angle, fill, vein=None):
    dx, dy = math.cos(angle), math.sin(angle)
    nx, ny = -dy, dx
    left, right = [], []
    for i in range(13):
        t = i / 12
        bulge = math.sin(t * math.pi) ** 0.85 * width
        center = (x + dx * length * t, y + dy * length * t)
        left.append((center[0] + nx * bulge, center[1] + ny * bulge))
        right.append((center[0] - nx * bulge, center[1] - ny * bulge))
    c.polygon(left + right[::-1], fill)
    if vein:
        c.line([(x, y), (x + dx * length * 0.88, y + dy * length * 0.88)], vein, 0.35)


def plant(c, x, y, height, color, seed, spread=1):
    rng = random.Random(seed)
    sway = rng.uniform(-0.16, 0.16) * height
    stem = bezier((x, y), (x - sway * 0.3, y - height * 0.35), (x + sway * 0.5, y - height * 0.74), (x + sway, y - height), 30)
    c.line(stem, color + 24, max(0.5, height / 110))
    for i in range(3, 12):
        t = i / 13
        index = round(t * 30)
        sx, sy = stem[index]
        angle = rng.uniform(-0.8, -0.25) if i % 2 else rng.uniform(-2.9, -2.3)
        length = height * rng.uniform(0.18, 0.3) * spread * (1.1 - t * 0.45)
        shade = max(8, min(220, color + rng.randint(-14, 23)))
        leaf(c, sx, sy, length, length * rng.uniform(0.18, 0.28), angle, shade, min(220, shade + 28))


def tree(c, x, y, height, seed):
    rng = random.Random(seed)
    c.line(bezier((x, y), (x - 7, y - height * 0.35), (x + 7, y - height * 0.65), (x + 1, y - height)), 45, height / 16)
    for i in range(25):
        t = rng.uniform(0.35, 0.95)
        side = -1 if i % 2 else 1
        ex = x + side * rng.uniform(12, 35) * t
        ey = y - height * t - rng.uniform(0, 15)
        c.line([(x, y - height * t * 0.8), (x + side * 8, ey + 10), (ex, ey)], 48, max(0.6, height * (1 - t) / 25))
        for j in range(10):
            lx = ex + rng.uniform(-11, 11)
            ly = ey + rng.uniform(-7, 7)
            leaf(c, lx, ly, rng.uniform(3, 8), rng.uniform(1.2, 2.5), rng.uniform(-math.pi, math.pi), rng.randint(38, 72))


def cloud(c, x, y, width, height, seed, value=223):
    rng = random.Random(seed)
    mask = Image.new("L", SIZE, 0)
    draw = ImageDraw.Draw(mask)
    for i in range(19):
        cx = x + rng.uniform(0.05, 0.95) * width
        cy = y + rng.uniform(0.18, 0.72) * height
        rx = rng.uniform(0.12, 0.3) * width
        ry = rng.uniform(0.22, 0.5) * height
        draw.ellipse(((cx - rx) * S, (cy - ry) * S, (cx + rx) * S, (cy + ry) * S), fill=rng.randint(165, 255))
    mask = mask.filter(ImageFilter.GaussianBlur(height * S * 0.18))
    c.image = Image.composite(Image.new("L", SIZE, value), c.image, mask)
    c.sync()


def human(c, x, y, height, color=15):
    c.ellipse((x - height * 0.058, y - height, x + height * 0.058, y - height * 0.878), fill=color)
    c.polygon([(x - height * 0.075, y - height * 0.84), (x - height * 0.16, y - height * 0.69), (x - height * 0.12, y - height * 0.31), (x + height * 0.13, y - height * 0.31), (x + height * 0.15, y - height * 0.69), (x + height * 0.07, y - height * 0.84)], color)
    c.line([(x - height * 0.055, y - height * 0.33), (x - height * 0.06, y)], color, height * 0.045)
    c.line([(x + height * 0.055, y - height * 0.33), (x + height * 0.07, y)], color, height * 0.045)
    c.line([(x - height * 0.12, y - height * 0.7), (x - height * 0.18, y - height * 0.43)], color, height * 0.035)
    c.line([(x + height * 0.12, y - height * 0.7), (x + height * 0.18, y - height * 0.43)], color, height * 0.035)


def garden():
    c = Canvas(211, 157, 101)
    c.light(299, 76, 105, 248, 1.2)
    c.facet([(131, 109), (280, 109), (280, 234), (131, 234)], 238, 202)
    for x in (131, 168, 205, 242, 280):
        c.line([(x, 110), (x, 235)], 91, 1.5)
    for y in (110, 151, 192, 234):
        c.line([(131, y), (280, y)], 104, 1.2)
    c.soft_polygon([(283, 77), (318, 81), (226, 281), (115, 281)], 244, 8)
    c.soft_polygon([(293, 84), (301, 86), (284, 264), (237, 264)], 249, 3)
    roof = [(x, 212 - math.sqrt(max(0, 222 ** 2 - (x - 200) ** 2)) * 0.65) for x in range(-10, 411, 5)]
    c.line(roof, 82, 3.1)
    for x in (7, 55, 105, 156, 205, 254, 305, 352, 399):
        y = 212 - math.sqrt(max(0, 222 ** 2 - (x - 200) ** 2)) * 0.65
        c.line([(x, y), (x, 277)], 102, 1.5)
        c.line([(x + 2, y + 1), (x + 2, 277)], 203, 0.65)
    for offset in (0, 34, 68):
        c.line([(x, y + offset) for x, y in roof if y + offset < 239], 104, 1.2)
    c.facet([(0, 229), (400, 229), (400, 300), (0, 300)], 154, 117)
    for x in range(-150, 600, 48):
        c.line([(204, 215), (x, 300)], 91, 0.75)
    for y in (220, 240, 264, 290):
        c.line([(0, y), (400, y)], 96, 0.75)
    for i in range(20):
        x = 9 + i * 20 + c.rng.uniform(-4, 4)
        plant(c, x, 241 + c.rng.uniform(-4, 5), c.rng.uniform(28, 53), c.rng.randint(83, 119), 1000 + i)
    c.soft_ellipse((34, 211, 361, 247), 187, 10)
    for i, (x, y, height) in enumerate(((17, 293, 128), (60, 299, 87), (372, 298, 146), (329, 298, 100), (115, 293, 59), (288, 295, 62))):
        plant(c, x, y, height, 42 + i * 7, 1100 + i, 1.25)
    for k, x in enumerate((66, 329)):
        for j in range(5):
            y = 55 + j * 16
            leaf(c, x + math.sin(j * 1.6) * 3, y, 12, 3, 2.3 if j % 2 else 0.8, 65 + j * 4, 167)
    for i in range(75):
        x, y = c.rng.uniform(144, 317), c.rng.uniform(89, 249)
        c.ellipse((x, y, x + c.rng.uniform(0.4, 0.9), y + c.rng.uniform(0.4, 0.9)), fill=c.rng.randint(209, 248))
    c.texture(5, 4)
    c.grain(1.2)
    c.vignette(6)
    c.label("garden", "温室晨光", 1)


def departures():
    c = Canvas(65, 34, 202)
    c.light(230, 134, 105, 154, 0.65)
    c.polygon([(0, 0), (400, 0), (400, 107), (231, 132), (0, 67)], 22)
    for x in (-130, 0, 98, 360, 470):
        c.line([(x, 0), (230, 131)], 104, 2)
        c.line([(x + 5, 0), (233, 131)], 48, 3.5)
    for t in (0.08, 0.3, 0.51, 0.69, 0.83):
        x = 24 + (226 - 24) * t
        floor = 299 + (168 - 299) * t
        top = 34 + (124 - 34) * t
        width = 12 * (1 - t) + 2
        c.polygon([(x, top), (x + width, top + 2), (x + width, floor), (x - 1, floor)], 55)
        c.line([(x + 1, top), (x + 1, floor)], 143, 1)
        c.line([(x, top + 2), (230, 131)], 91, 1.3)
        c.soft_polygon([(x - 3, top + 12), (x + 29 * (1 - t), top + 22), (x + 29 * (1 - t), top + 25), (x - 3, top + 15)], 238, 0.9)
    c.facet([(0, 186), (230, 135), (230, 170), (111, 300), (0, 300)], 151, 99)
    c.line([(0, 186), (230, 135), (230, 170), (111, 300)], 220, 1.5)
    for i in range(16):
        t = i / 16
        y = 192 + t * 105
        x = (1 - t) * 226
        c.line([(0, y), (x, y - 5)], 111, 0.7)
    for x in (-120, -45, 24, 80, 135, 175):
        c.line([(230, 143), (x, 300)], 101, 0.8)
    c.polygon([(231, 161), (400, 202), (400, 300), (117, 300)], 43)
    for i in range(19):
        t = i / 18
        y = 167 + t ** 1.65 * 137
        left = 230 - t * 112
        right = 247 + t * 166
        c.line([(left, y), (right, y + 5)], 93, 1 + t * 2)
    c.line([(232, 164), (159, 300)], 204, 1.8)
    c.line([(245, 169), (287, 300)], 181, 1.8)
    c.polygon([(260, 114), (400, 104), (400, 191), (258, 164)], 133)
    c.line([(260, 114), (400, 104)], 201, 1.2)
    for i in range(6):
        x = 268 + i * 23
        c.facet([(x, 120 - i * 0.6), (x + 16, 119 - i * 0.6), (x + 16, 146 + i * 1.8), (x, 145 + i * 1.8)], 244, 193)
        c.line([(x + 3, 123), (x + 3, 142 + i)], 251, 0.7)
    c.light(259, 157, 15, 246, 0.65)
    c.ellipse((255, 154, 262, 160), fill=252)
    c.soft_polygon([(250, 167), (265, 169), (315, 298), (247, 298)], 145, 3)
    c.rectangle((76, 78, 188, 106), fill=26, outline=151, width=1, radius=1)
    c.text(84, 85, "23:48   04", 7, 236, True)
    c.text(84, 97, "NIGHT SERVICE  →", 3.5, 176, True, 0.5)
    c.line([(90, 78), (90, 64)], 97, 1.2)
    c.line([(174, 78), (174, 86)], 97, 1.2)
    c.rectangle((45, 176, 93, 181), fill=105, radius=1)
    for x in (51, 86):
        c.line([(x, 180), (x - 2, 195)], 68, 1.8)
    c.soft_ellipse((86, 270, 139, 284), 71, 2)
    c.rectangle((91, 221, 124, 263), fill=64, outline=177, width=1, radius=3)
    c.rectangle((95, 224, 120, 258), outline=110, width=0.7, radius=2)
    c.line([(102, 222), (102, 213), (114, 213), (114, 222)], 177, 1.5)
    c.line([(96, 227), (96, 256)], 205, 0.8)
    c.line([(100, 262), (100, 266)], 168, 1.2)
    c.line([(118, 262), (118, 266)], 168, 1.2)
    human(c, 188, 183, 34, 34)
    c.soft_ellipse((159, 177, 216, 197), 89, 5)
    for i in range(70):
        x, y = c.rng.uniform(242, 400), c.rng.uniform(80, 231)
        c.line([(x, y), (x - 1.2, y + c.rng.uniform(2, 8))], c.rng.randint(115, 177), 0.55)
    c.texture(3, 4)
    c.grain(0.7)
    c.vignette(12)
    c.label("departures", "夜间启程", 2)


def voices():
    c = Canvas(115, 52, 303)
    c.light(218, 122, 100, 205, 1.45)
    window = Image.new("L", SIZE, 0)
    draw = ImageDraw.Draw(window)
    draw.rectangle((147 * S, 107 * S, 277 * S, 216 * S), fill=255)
    draw.ellipse((147 * S, 40 * S, 277 * S, 174 * S), fill=255)
    c.image.paste(gradient(248, 183), (0, 0), window)
    c.sync()
    for x in (147, 178, 211, 244, 277):
        c.line([(x, 101), (x, 216)], 71, 2.2)
    for y in (110, 150, 187, 216):
        c.line([(147, y), (277, y)], 84, 1.6)
    c.arc((145, 39, 279, 175), 180, 360, 61, 3)
    c.arc((157, 56, 267, 166), 180, 360, 138, 1.2)
    for inset, shade in ((0, 35), (7, 87), (12, 48)):
        c.arc((123 - inset, 25 - inset, 301 + inset, 230 + inset), 180, 360, shade, 5)
    for x in (118, 284):
        c.facet([(x, 122), (x + 20, 122), (x + 24, 242), (x - 4, 242)], 105, 48)
        c.rectangle((x - 6, 120, x + 26, 128), fill=91)
        c.rectangle((x - 8, 234, x + 29, 243), fill=53)
        for dx in (4, 10, 16):
            c.line([(x + dx, 131), (x + dx, 232)], 66, 0.9)
    for x in (16, 69):
        c.facet([(x, 103), (x + 23, 103), (x + 28, 267), (x - 4, 267)], 68, 35)
        c.rectangle((x - 5, 104, x + 29, 112), fill=62)
        c.arc((x - 9, 24, 135, 194), 180, 316, 70, 5)
        c.arc((x - 4, 31, 130, 193), 180, 316, 39, 7)
    for x in (330, 375):
        c.line([(x, 94), (x + 3, 268)], 51, 10)
        c.arc((266, 24, x + 20, 202), 216, 360, 55, 5)
    c.facet([(0, 249), (207, 203), (400, 249), (400, 300), (0, 300)], 111, 63)
    for x in (-180, -70, 45, 133, 281, 365, 470, 570):
        c.line([(207, 199), (x, 300)], 77, 0.8)
    for y in (221, 242, 267, 296):
        c.line([(0, y), (400, y)], 80, 0.8)
    c.soft_polygon([(165, 120), (189, 123), (102, 294), (13, 294)], 229, 7)
    c.soft_polygon([(230, 115), (253, 118), (363, 294), (283, 294)], 214, 7)
    for side in (-1, 1):
        base = 146 if side == -1 else 277
        points = [(base, 71)]
        for y in range(71, 230, 9):
            points.append((base + side * (11 + math.sin(y * 0.063) * 5), y))
        points += [(base + side * 24, 230), (base + side * 21, 71)]
        c.soft_polygon(points, 177, 1.2)
    c.soft_ellipse((95, 194, 326, 245), 149, 13)
    c.soft_polygon([(201, 229), (219, 229), (227, 282), (190, 282)], 60, 2.5)
    human(c, 210, 229, 49, 28)
    c.line([(206, 199), (206, 222)], 72, 0.7)
    for i in range(80):
        x, y = c.rng.uniform(124, 290), c.rng.uniform(96, 243)
        c.ellipse((x, y, x + 0.55, y + 0.55), fill=c.rng.randint(184, 241))
    c.texture(4, 4)
    c.grain(0.8)
    c.vignette(16)
    c.label("voices", "远方人声", 3)


def afternoon():
    c = Canvas(237, 181, 404)
    c.light(320, 64, 111, 252, 1.1)
    cloud(c, 26, 68, 132, 26, 440, 246)
    cloud(c, 141, 51, 95, 19, 441, 239)
    cloud(c, 244, 106, 123, 16, 442, 220)
    c.ellipse((311, 53, 331, 73), fill=252)
    c.soft_polygon([(305, 74), (322, 75), (214, 247), (142, 247)], 232, 11)
    c.ridge(159, 10, 179, 23)
    c.ridge(179, 13, 142, 19)
    c.ridge(204, 11, 108, 16)
    for i in range(65):
        x = c.rng.uniform(0, 400)
        y = 185 + c.rng.uniform(-6, 8)
        c.ellipse((x, y, x + c.rng.uniform(2, 8), y + c.rng.uniform(2, 6)), fill=c.rng.randint(93, 128))
    c.facet([(0, 222), (90, 202), (191, 215), (302, 196), (400, 209), (400, 300), (0, 300)], 126, 72)
    path_left = bezier((227, 300), (191, 261), (236, 230), (231, 195), 40)
    path_right = bezier((292, 300), (226, 260), (246, 230), (235, 195), 40)
    c.polygon(path_left + path_right[::-1], 197)
    c.line(path_left, 229, 1)
    tree(c, 83, 221, 84, 450)
    for i in range(410):
        x = c.rng.uniform(-5, 405)
        y = c.rng.uniform(222, 306)
        height = c.rng.uniform(5, 28) * (y - 180) / 110
        sway = c.rng.uniform(-6, 6)
        color = c.rng.randint(66, 156)
        c.line([(x, y), (x + sway * 0.3, y - height * 0.6), (x + sway, y - height)], color, c.rng.uniform(0.45, 0.85))
        if i % 7 == 0:
            for j in range(4):
                c.ellipse((x + sway - 0.6, y - height + j * 1.4, x + sway + 1.1, y - height + j * 1.4 + 1), fill=min(225, color + 40))
        if i % 17 == 0:
            leaf(c, x, y - height * 0.35, 5, 1.2, -0.55, color + 15)
    for i in range(17):
        x, y = c.rng.uniform(12, 380), c.rng.uniform(242, 297)
        c.line([(x, y), (x + 1, y - 10)], 102, 0.7)
        for a in range(5):
            angle = a * math.tau / 5
            c.ellipse((x + math.cos(angle) * 1.5 - 0.7, y - 10 + math.sin(angle) * 1.5 - 0.7, x + math.cos(angle) * 1.5 + 0.7, y - 10 + math.sin(angle) * 1.5 + 0.7), fill=224)
    for x, y in ((174, 96), (190, 89), (203, 98)):
        c.arc((x - 5, y - 2, x, y + 3), 196, 349, 86, 0.9)
        c.arc((x, y - 2, x + 5, y + 3), 191, 344, 86, 0.9)
    c.texture(4, 4)
    c.grain(1)
    c.vignette(8)
    c.label("afternoon", "午后原野", 4)


def night_bus():
    c = Canvas(55, 28, 505)
    for i in range(10):
        x, width = i * 45 - 9, c.rng.randint(26, 51)
        top = c.rng.randint(52, 127)
        c.rectangle((x, top, x + width, 239), fill=c.rng.randint(48, 81))
        for wx in range(x + 5, x + width - 3, 9):
            for wy in range(top + 7, 210, 13):
                if c.rng.random() < 0.42:
                    c.rectangle((wx, wy, wx + 3, wy + 5), fill=c.rng.randint(140, 225))
    c.image = c.image.filter(ImageFilter.GaussianBlur(1.5 * S))
    c.sync()
    for i, (x, y, radius) in enumerate(((54, 142, 10), (103, 189, 7), (157, 113, 12), (208, 166, 9), (253, 98, 13), (313, 145, 11), (360, 181, 8), (34, 220, 8), (229, 218, 9))):
        c.light(x, y, radius * 2.1, 213 + i % 3 * 14, 0.85)
        c.soft_ellipse((x - radius * 0.37, y - radius * 0.37, x + radius * 0.37, y + radius * 0.37), 249, 1.4)
        c.soft_polygon([(x - 1, y + 6), (x + 2, y + 6), (x + 12, 246), (x - 9, 246)], 129, 2)
    c.soft_polygon([(0, 205), (263, 180), (265, 185), (0, 220)], 184, 2)
    c.facet([(0, 242), (400, 235), (400, 300), (0, 300)], 111, 79)
    c.rectangle((0, 49, 400, 63), fill=24)
    c.line([(0, 62), (400, 62)], 142, 1.2)
    c.line([(0, 53), (400, 53)], 71, 1.2)
    c.rectangle((266, 57, 282, 251), fill=25)
    c.line([(267, 65), (267, 242)], 143, 1.3)
    c.line([(280, 65), (280, 242)], 74, 1)
    for x, y in ((274, 73), (274, 233), (14, 57), (381, 57)):
        c.ellipse((x - 1.1, y - 1.1, x + 1.1, y + 1.1), fill=156)
        c.line([(x - 0.6, y), (x + 0.6, y)], 52, 0.5)
    for i in range(150):
        x, y = c.rng.uniform(5, 263), c.rng.uniform(69, 239)
        r = c.rng.uniform(0.45, 1.5)
        c.ellipse((x - r, y - r, x + r, y + r * 1.5), fill=c.rng.randint(68, 105))
        c.arc((x - r, y - r, x + r, y + r * 1.4), 160, 295, c.rng.randint(184, 245), 0.65)
        if i % 3 == 0:
            c.line([(x, y + r), (x - 0.5, y + r + c.rng.uniform(2, 13))], c.rng.randint(117, 177), 0.55)
    for x, y, length in ((24, 82, 63), (77, 105, 92), (130, 68, 46), (182, 143, 71), (223, 78, 85), (250, 162, 61)):
        path = bezier((x, y), (x - 2, y + length * 0.25), (x + 3, y + length * 0.66), (x + 1, y + length), 25)
        c.line(path, 132, 1)
        c.line([(px - 0.65, py) for px, py in path], 211, 0.5)
    c.rectangle((31, 254, 147, 259), fill=29, radius=2)
    c.line([(40, 254), (138, 254)], 161, 1.2)
    c.soft_ellipse((299, 151, 332, 188), 83, 1.3)
    c.polygon([(303, 160), (298, 169), (302, 184), (315, 190), (330, 180), (330, 159), (320, 151), (309, 152)], 27)
    c.line([(302, 164), (300, 170), (304, 173)], 108, 0.8)
    c.polygon([(306, 183), (330, 181), (348, 195), (373, 223), (400, 229), (400, 300), (283, 300), (284, 231)], 32)
    c.line([(310, 186), (324, 199), (330, 224)], 93, 1.4)
    c.facet([(334, 220), (400, 208), (400, 300), (325, 300)], 102, 70)
    c.line([(341, 229), (400, 219)], 144, 1.1)
    c.facet([(0, 251), (60, 245), (85, 300), (0, 300)], 105, 73)
    for i in range(70):
        x, y = c.rng.uniform(289, 399), c.rng.uniform(229, 299)
        c.line([(x, y), (x + 1.1, y + 0.4)], c.rng.randint(71, 109), 0.45)
    c.texture(3, 3)
    c.grain(0.8)
    c.vignette(10)
    c.label("night-bus", "雨夜巴士", 5)


def shoreline():
    c = Canvas(119, 61, 606)
    c.light(290, 63, 87, 184, 0.95)
    c.texture(7, 5)
    c.light(290, 63, 29, 239)
    c.ellipse((274, 47, 306, 79), fill=248)
    for x, y, r in ((284, 56, 3), (296, 66, 4), (288, 71, 2), (298, 55, 1.8)):
        c.soft_ellipse((x - r, y - r, x + r, y + r), 218, 1)
    cloud(c, 222, 69, 145, 11, 660, 96)
    c.facet([(0, 160), (400, 159), (400, 300), (0, 300)], 111, 59)
    c.line([(128, 160), (400, 159)], 158, 0.8)
    for i in range(1150):
        y = c.rng.uniform(164, 302)
        perspective = (y - 150) / 150
        x = c.rng.uniform(-10, 410)
        length = c.rng.uniform(1, 10) * (0.3 + perspective)
        value = c.rng.randint(107, 161)
        reflection_x = 290 + math.sin(y * 0.15) * 3
        if abs(x - reflection_x) < 4 + perspective * 38 and c.rng.random() < 0.8:
            value = c.rng.randint(186, 247)
        c.line([(x, y), (x + length * 0.48, y - perspective * 0.9), (x + length, y)], value, c.rng.uniform(0.45, 0.85))
    c.soft_polygon([(105, 115), (110, 116), (293, 77), (295, 88)], 174, 4)
    c.light(105, 115, 13, 238)
    c.polygon([(59, 170), (75, 158), (110, 157), (131, 179), (124, 192), (42, 191)], 64)
    c.facet([(91, 119), (110, 119), (117, 171), (85, 171)], 231, 157)
    for y in range(128, 166, 7):
        c.line([(90, y), (112, y)], 131, 0.65)
    c.rectangle((99, 144, 105, 151), fill=55)
    c.rectangle((89, 111, 114, 120), fill=48)
    c.rectangle((93, 107, 110, 114), fill=242)
    for x in (96, 103, 109):
        c.line([(x, 107), (x, 114)], 80, 0.8)
    c.polygon([(89, 107), (101, 98), (114, 107)], 57)
    c.line([(86, 120), (118, 120)], 169, 1.3)
    c.rectangle((68, 153, 88, 172), fill=117)
    c.polygon([(65, 153), (77, 142), (91, 153)], 54)
    c.rectangle((73, 158, 79, 166), fill=208)
    c.polygon([(0, 194), (24, 180), (50, 184), (65, 176), (91, 186), (104, 184), (124, 204), (119, 218), (143, 232), (119, 245), (144, 264), (111, 278), (126, 300), (0, 300)], 43)
    for points, value in (
        (((0, 208), (11, 198), (26, 194), (39, 201), (51, 208), (46, 219), (29, 230), (8, 226)), 67),
        (((48, 211), (57, 198), (76, 189), (91, 196), (103, 210), (91, 218), (73, 231), (55, 224)), 80),
        (((9, 249), (22, 235), (42, 229), (61, 238), (77, 250), (69, 266), (47, 276), (26, 270)), 57),
        (((82, 261), (94, 249), (110, 240), (124, 248), (130, 263), (118, 276), (99, 282)), 73),
    ):
        c.polygon(points, value)
    for points in (((18, 204), (27, 211), (22, 222)), ((72, 197), (79, 207), (69, 222)), ((36, 239), (45, 249), (37, 266)), ((107, 249), (111, 261), (101, 274))):
        c.line(points, 37, 1)
    for i in range(145):
        x, y = c.rng.uniform(0, 123), c.rng.uniform(191, 300)
        c.line([(x, y), (x + c.rng.uniform(2, 10), y - c.rng.uniform(1, 4))], c.rng.randint(72, 126), 0.6)
    for i in range(160):
        x = c.rng.gauss(122, 16)
        y = c.rng.gauss(224, 6)
        r = c.rng.uniform(0.3, 1.1)
        c.ellipse((x, y, x + r * 2.3, y + r), fill=c.rng.randint(149, 220))
    for x, y in ((181, 87), (195, 82), (207, 88)):
        c.arc((x - 3, y, x, y + 2), 190, 350, 47, 0.8)
        c.arc((x, y, x + 3, y + 2), 190, 350, 47, 0.8)
    c.grain(0.8)
    c.vignette(12)
    c.label("shoreline", "月下海岸", 6)


def prisms(c):
    c.facet([(84, 245), (93, 155), (113, 124), (139, 153), (150, 244), (119, 257)], 218, 137)
    c.facet([(113, 124), (121, 246), (119, 257), (150, 244), (139, 153)], 174, 77)
    c.facet([(93, 155), (113, 124), (121, 246), (84, 245)], 137, 55)
    c.facet([(271, 247), (280, 171), (301, 145), (320, 177), (331, 248), (303, 258)], 207, 126)
    c.facet([(301, 145), (306, 252), (331, 248), (320, 177)], 164, 72)
    c.facet([(280, 171), (301, 145), (306, 252), (271, 247)], 126, 54)
    c.facet([(158, 239), (151, 122), (178, 72), (214, 54), (244, 91), (257, 237), (215, 254), (182, 249)], 226, 138)
    c.facet([(178, 72), (214, 54), (225, 239), (190, 247)], 250, 181)
    c.facet([(214, 54), (244, 91), (257, 237), (225, 239)], 194, 103)
    c.facet([(151, 122), (178, 72), (190, 247), (158, 239)], 165, 78)
    c.facet([(190, 247), (225, 239), (257, 237), (215, 254), (182, 249)], 151, 83)
    for points, color, width in (((178, 72), (214, 54), (244, 91)), 253, 1), (((151, 122), (178, 72), (190, 247)), 231, 0.75), (((214, 54), (225, 239), (257, 237)), 238, 0.8), (((158, 239), (182, 249), (215, 254)), 209, 0.8), (((93, 155), (113, 124), (139, 153)), 243, 0.75), (((280, 171), (301, 145), (320, 177)), 239, 0.75):
        c.line(points, color, width)
    for i in range(14):
        t = i / 14
        c.line([(165 + t * 15, 130 + t * 4), (197 + t * 10, 234)], 104 + i * 7, 0.5)
    for i in range(9):
        y = 108 + i * 12
        c.line([(186, y), (218 + i * 0.8, y + 8)], 239 - i * 11, 0.6)
    for i in range(40):
        x, y = c.rng.uniform(163, 248), c.rng.uniform(101, 241)
        c.ellipse((x, y, x + 0.55, y + 0.55), fill=c.rng.randint(199, 251))


def glass():
    c = Canvas(202, 157, 707)
    c.light(235, 116, 108, 239, 1.15)
    c.facet([(0, 239), (400, 235), (400, 300), (0, 300)], 148, 105)
    c.line([(0, 239), (400, 235)], 104, 0.8)
    crystal = Canvas(0, 0, 770)
    prisms(crystal)
    reflection = crystal.image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).crop((0, 0, W * S, 107 * S))
    mask = reflection.point(lambda p: round(p * 0.28))
    c.image.paste(reflection, (0, 193 * S), mask)
    c.sync()
    c.soft_polygon([(182, 242), (189, 246), (41, 277), (11, 277)], 211, 1.6)
    c.soft_polygon([(226, 244), (235, 244), (385, 284), (357, 286)], 225, 1.3)
    c.soft_polygon([(206, 246), (210, 246), (266, 298), (238, 298)], 180, 2)
    mask = crystal.image.point(lambda p: 255 if p > 2 else 0).filter(ImageFilter.GaussianBlur(0.25 * S))
    c.image.paste(crystal.image, (0, 0), mask)
    c.sync()
    for i in range(62):
        x, y = c.rng.uniform(66, 339), c.rng.uniform(76, 260)
        if c.rng.random() < 0.8:
            c.ellipse((x, y, x + 0.5, y + 0.5), fill=c.rng.randint(137, 213))
        else:
            c.line([(x - 1.4, y), (x + 1.4, y)], 243, 0.6)
            c.line([(x, y - 1.4), (x, y + 1.4)], 243, 0.6)
    c.grain(0.7)
    c.vignette(7)
    c.label("glass", "玻璃棱镜", 7)


def tides():
    c = Canvas(218, 164, 808)
    c.light(312, 84, 129, 239, 0.6)
    c.texture(6, 5)
    left = bezier((238, 78), (200, 115), (90, 156), (145, 204), 40) + bezier((145, 204), (188, 237), (193, 263), (151, 310), 40)[1:]
    right = bezier((256, 78), (249, 116), (160, 159), (207, 201), 40) + bezier((207, 201), (261, 237), (330, 259), (371, 310), 40)[1:]
    c.soft_polygon(left + right[::-1], 67, 0.65)
    c.line(left, 226, 1.1)
    c.line(right, 147, 0.9)
    branch_left = bezier((157, 144), (103, 129), (54, 152), (-10, 125), 50)
    branch_right = bezier((247, 224), (295, 198), (345, 177), (411, 203), 50)
    for branch in (branch_left, branch_right):
        c.line(branch, 88, 12)
        c.line([(x, y - 5) for x, y in branch], 218, 0.8)
        c.line([(x, y - 1) for x, y in branch], 127, 1.2)
    for i in range(310):
        t = c.rng.uniform(0, len(left) - 1.001)
        index = int(t)
        lx, y = left[index]
        rx, _ = right[index]
        if rx - lx < 4:
            continue
        x = c.rng.uniform(lx + 3, rx - 3)
        length = c.rng.uniform(1, min(18, (rx - lx) * 0.35))
        c.line([(x, y), (x + length * 0.5, y - 0.4), (min(rx - 2, x + length), y + 0.2)], c.rng.randint(112, 179), c.rng.uniform(0.45, 0.8))
    for i in range(760):
        x, y = c.rng.uniform(-10, 410), c.rng.uniform(94, 311)
        nearest = min(range(0, len(left), 3), key=lambda j: abs(left[j][1] - y))
        lx, ly = left[nearest]
        rx, ry = right[nearest]
        if lx - 2 < x < rx + 2 and abs(ly - y) < 5:
            continue
        length = c.rng.uniform(2, 13) * (0.5 + y / 400)
        bend = math.sin(x * 0.022 + y * 0.018) * 3
        shade = c.rng.randint(111, 170)
        c.line([(x, y), (x + length * 0.45, y + bend - 1), (x + length, y + bend)], shade, c.rng.uniform(0.4, 0.7))
    c.soft_ellipse((-40, 83, 430, 116), 218, 12)
    c.soft_polygon([(0, 270), (43, 249), (68, 254), (30, 279)], 179, 3)
    for i in range(10):
        x, y = c.rng.uniform(178, 308), c.rng.uniform(110, 183)
        c.line([(x - 1.4, y), (x, y - 0.7), (x + 1.4, y)], 91, 0.65)
    c.grain(0.8)
    c.vignette(8)
    c.label("tides", "长潮呼吸", 8)


for renderer in (garden, departures, voices, afternoon, night_bus, shoreline, glass, tides):
    renderer()

sheet = Image.new("L", (888, 1308), 187)
for index, name in enumerate(NAMES):
    image = Image.open(OUT / f"{name}.png")
    assert image.size == (400, 300) and image.mode == "L"
    assert len(image.getcolors(256)) > 200, name
    sheet.paste(image, (24 + (index % 2) * 440, 24 + (index // 2) * 320))
sheet.save(OUT / "contact-sheet.png", optimize=True)
print("generated 8 detailed scene-specific continuous-grayscale NOTE4 covers")
