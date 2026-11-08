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
NAMES = ("rain-street", "cafe", "city-voices", "midnight-road")


def font(size, latin=False):
    candidates = ["/System/Library/Fonts/Supplemental/Arial.ttf"] if latin else ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc"]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, round(size * S))
    return ImageFont.load_default(size=round(size * S))


def gradient(top, bottom):
    ramp = Image.linear_gradient("L").resize(SIZE)
    return Image.composite(Image.new("L", SIZE, bottom), Image.new("L", SIZE, top), ramp)


def bezier(a, b, c, d, count=40):
    points = []
    for i in range(count + 1):
        t = i / count
        u = 1 - t
        points.append(tuple(u ** 3 * a[j] + 3 * u * u * t * b[j] + 3 * u * t * t * c[j] + t ** 3 * d[j] for j in (0, 1)))
    return points


class Canvas:
    def __init__(self, top, bottom, seed):
        self.image = gradient(top, bottom)
        self.draw = ImageDraw.Draw(self.image)
        self.rng = random.Random(seed)

    def sync(self):
        self.draw = ImageDraw.Draw(self.image)

    def line(self, points, fill, width=1):
        self.draw.line([(round(x * S), round(y * S)) for x, y in points], fill=fill, width=max(1, round(width * S)), joint="curve")

    def polygon(self, points, fill):
        self.draw.polygon([(round(x * S), round(y * S)) for x, y in points], fill=fill)

    def rectangle(self, box, fill=None, outline=None, width=1, radius=0):
        box = tuple(round(v * S) for v in box)
        if radius:
            self.draw.rounded_rectangle(box, radius=round(radius * S), fill=fill, outline=outline, width=max(1, round(width * S)))
        else:
            self.draw.rectangle(box, fill=fill, outline=outline, width=max(1, round(width * S)))

    def ellipse(self, box, fill=None, outline=None, width=1):
        self.draw.ellipse(tuple(round(v * S) for v in box), fill=fill, outline=outline, width=max(1, round(width * S)))

    def arc(self, box, start, end, fill, width=1):
        self.draw.arc(tuple(round(v * S) for v in box), start, end, fill=fill, width=max(1, round(width * S)))

    def text(self, x, y, text, size, fill, latin=False, tracking=0):
        face = font(size, latin)
        for character in text:
            self.draw.text((round(x * S), round(y * S)), character, font=face, fill=fill, anchor="lt")
            x += self.draw.textlength(character, font=face) / S + tracking

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

    def light(self, x, y, radius, value, stretch=1):
        mask = Image.new("L", SIZE, 0)
        ImageDraw.Draw(mask).ellipse(((x-radius)*S, (y-radius*stretch)*S, (x+radius)*S, (y+radius*stretch)*S), fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(radius * S * .55))
        self.image = Image.composite(Image.new("L", SIZE, value), self.image, mask)
        self.sync()

    def texture(self, amount=5):
        noise = Image.frombytes("L", (80, 60), self.rng.randbytes(80 * 60)).resize(SIZE, Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(4 * S))
        noise = noise.point(lambda p: round(128 + (p - 128) * amount / 128))
        self.image = ImageChops.add(self.image, noise, offset=-128)
        self.sync()

    def label(self, name, title, number, night=False):
        shade = Image.new("L", SIZE, 0)
        top = Image.linear_gradient("L").resize((W * S, 82 * S)).point(lambda p: round((255 - p) * .64))
        shade.paste(top, (0, 0))
        self.image = Image.composite(Image.new("L", SIZE, 20 if night else 229), self.image, shade)
        self.sync()
        self.text(20, 15, f"FIELD / {name}", 6.4, 190 if night else 107, True, .65)
        self.text(20, 31, title, 16, 239 if night else 48)
        self.line([(20, 59), (43, 59)], 205 if night else 112, 1.2)
        self.text(337, 16, f"F{number:02d} / 04", 6.2, 183 if night else 105, True, .3)
        self.image = self.image.resize((W, H), Image.Resampling.LANCZOS)
        self.image.save(OUT / f"{name}.png", optimize=True)


def human(c, x, y, height, color=45):
    c.ellipse((x-height*.06, y-height, x+height*.06, y-height*.87), fill=color)
    c.polygon([(x-height*.08, y-height*.82), (x-height*.14, y-height*.57), (x-height*.1, y-height*.29), (x+height*.1, y-height*.29), (x+height*.14, y-height*.57), (x+height*.08, y-height*.82)], color)
    c.line([(x-height*.045, y-height*.3), (x-height*.07, y)], color, height*.045)
    c.line([(x+height*.045, y-height*.3), (x+height*.07, y)], color, height*.045)


def rain_street():
    c = Canvas(192, 133, 101)
    c.rectangle((0, 77, 105, 207), fill=105)
    c.rectangle((307, 91, 400, 205), fill=117)
    for x in range(12, 96, 21):
        for y in range(91, 184, 27):
            c.rectangle((x, y, x+10, y+13), fill=178 if (x+y)%3 else 211)
    for x in range(319, 400, 22):
        for y in range(103, 180, 25):
            c.rectangle((x, y, x+11, y+12), fill=194)
    c.polygon([(0, 188), (189, 154), (215, 154), (400, 191), (400, 300), (0, 300)], 110)
    c.facet([(103, 183), (189, 158), (215, 158), (332, 300), (34, 300)], 145, 72)
    c.line([(190, 160), (74, 300)], 196, 1.4)
    c.line([(212, 160), (307, 300)], 184, 1.4)
    for i in range(90):
        y = c.rng.uniform(177, 300)
        x = c.rng.uniform(15, 386)
        length = c.rng.uniform(3, 19) * (y-145)/155
        c.line([(x, y), (x+length, y-.5)], c.rng.randint(122, 190), c.rng.uniform(.45, .9))
    for x, y in ((169, 190), (251, 190)):
        c.soft_polygon([(x, y), (x+8, y), (x+26, 295), (x-10, 295)], 181, 5)
    c.polygon([(170, 169), (197, 165), (232, 167), (251, 181), (249, 190), (167, 188)], 66)
    c.rectangle((184, 166, 222, 176), fill=151, radius=2)
    for x in (176, 240):
        c.light(x, 182, 10, 244, .55)
        c.ellipse((x-3, 180, x+3, 185), fill=246)
    c.line([(80, 81), (80, 219)], 61, 3)
    c.arc((63, 64, 97, 102), 180, 360, 66, 2.4)
    c.light(80, 91, 27, 237, .8)
    c.rectangle((73, 84, 87, 94), fill=232, outline=80, width=1)
    c.polygon([(112, 185), (123, 173), (145, 165), (168, 171), (181, 185)], 54)
    c.arc((112, 164, 181, 206), 180, 360, 191, 1.1)
    for x in (123, 145, 168):
        c.line([(145, 166), (x, 184)], 125, .8)
    c.line([(145, 184), (145, 215)], 56, 1.5)
    human(c, 145, 229, 38, 48)
    for i in range(130):
        x, y = c.rng.uniform(-5, 405), c.rng.uniform(68, 298)
        c.line([(x, y), (x-1.7, y+c.rng.uniform(4, 10))], c.rng.randint(153, 220), c.rng.uniform(.45, .75))
    c.texture(4)
    c.label("rain-street", "雨中街道", 1)


def cafe():
    c = Canvas(199, 129, 202)
    c.rectangle((194, 68, 370, 211), fill=229, outline=94, width=2)
    c.facet([(201, 75), (363, 75), (363, 204), (201, 204)], 241, 184)
    for x in (228, 282, 336):
        c.line([(x, 73), (x, 209)], 105, 2)
    c.line([(197, 143), (368, 143)], 105, 2)
    c.soft_polygon([(225, 80), (243, 80), (165, 242), (99, 242)], 234, 5)
    for x in (66, 144):
        c.line([(x, 47), (x, 103)], 65, 1.5)
        c.polygon([(x-24, 111), (x-14, 94), (x+14, 94), (x+24, 111)], 58)
        c.light(x, 118, 32, 232, .7)
        c.line([(x-22, 111), (x+22, 111)], 203, 1.3)
    c.rectangle((13, 150, 173, 221), fill=143)
    c.line([(13, 151), (173, 151)], 73, 2)
    for x in (25, 63, 103, 145):
        c.line([(x, 158), (x, 213)], 124, 1)
    human(c, 83, 213, 55, 70)
    human(c, 136, 215, 50, 82)
    c.ellipse((60, 209, 157, 222), fill=83)
    c.line([(112, 217), (112, 248)], 67, 4)
    c.ellipse((87, 244, 137, 250), fill=69)
    for x, y in ((91, 200), (131, 202)):
        c.rectangle((x-4, y-6, x+4, y), fill=211, outline=85, width=.8, radius=1)
        c.arc((x+3, y-5, x+9, y-1), 270, 90, 85, .8)
    c.facet([(0, 244), (241, 226), (400, 247), (400, 300), (0, 300)], 111, 65)
    for i in range(16):
        y = 245 + i*3.3
        c.line([(0, y), (400, y+8)], 93, .55)
    c.ellipse((146, 237, 231, 254), fill=177, outline=71, width=1.2)
    c.ellipse((158, 218, 218, 250), fill=220, outline=65, width=1.4)
    c.ellipse((163, 218, 213, 228), fill=73)
    c.ellipse((168, 220, 208, 225), fill=115)
    c.arc((211, 224, 237, 244), 262, 93, 66, 3)
    for x in (174, 188, 201):
        c.line(bezier((x, 216), (x-9, 203), (x+9, 194), (x, 181)), 218, 1.4)
    c.rectangle((268, 224, 339, 233), fill=174, outline=85, width=1)
    c.rectangle((277, 208, 328, 225), fill=208, outline=91, width=1)
    c.line([(282, 214), (321, 214)], 122, 1)
    c.texture(4)
    c.label("cafe", "咖啡馆午后", 2)


def city_voices():
    c = Canvas(231, 178, 303)
    c.rectangle((0, 91, 400, 184), fill=167)
    for x, width in ((0, 74), (74, 91), (165, 75), (240, 91), (331, 69)):
        c.rectangle((x, 91, x+width, 184), fill=183 if (x//70)%2 else 196)
        c.rectangle((x-2, 88, x+width+2, 98), fill=119)
        for wx in range(x+10, x+width-5, 22):
            c.rectangle((wx, 108, wx+11, 129), fill=86)
            c.arc((wx, 102, wx+11, 116), 180, 360, 91, 1)
            c.line([(wx+5, 108), (wx+5, 129)], 159, .8)
            c.arc((wx-2, 143, wx+13, 176), 180, 360, 95, 1.6)
    c.rectangle((0, 179, 400, 239), fill=191)
    for x in range(-20, 430, 35):
        c.line([(205, 179), (x, 246)], 157, .7)
    for y in (192, 208, 229):
        c.line([(0, y), (400, y)], 161, .7)
    c.ellipse((143, 196, 268, 229), fill=114)
    c.ellipse((150, 192, 261, 221), fill=218, outline=99, width=1.2)
    c.rectangle((197, 169, 213, 204), fill=139)
    c.ellipse((190, 166, 220, 175), fill=217, outline=111, width=1)
    for x in (174, 192, 219, 237):
        c.line(bezier((205, 168), (x, 134), (x, 153), (x, 196)), 232, 1.5)
        c.ellipse((x-2, 194, x+2, 197), fill=238)
    for x, y, h in ((82, 218, 31), (113, 226, 34), (278, 222, 35), (311, 231, 30), (54, 232, 27), (342, 215, 25)):
        human(c, x, y, h, 65 if x%2 else 83)
    c.line([(39, 173), (43, 221)], 77, 4)
    for i in range(30):
        x = c.rng.gauss(42, 19); y = c.rng.gauss(145, 20)
        c.ellipse((x-7, y-4, x+7, y+4), fill=c.rng.randint(82, 128))
    for x, y in ((271, 112), (289, 105), (307, 114)):
        c.arc((x-5, y-2, x, y+3), 195, 345, 84, .9)
        c.arc((x, y-2, x+5, y+3), 195, 345, 84, .9)
    c.rectangle((0, 251, 400, 260), fill=62)
    for x in range(9, 400, 27):
        c.line([(x, 259), (x, 300)], 68, 3)
        c.ellipse((x-2, 247, x+2, 253), fill=89)
    c.line([(0, 278), (400, 278)], 78, 2)
    c.texture(3)
    c.label("city-voices", "街头人声", 3)


def midnight_road():
    c = Canvas(53, 20, 404)
    c.light(313, 87, 55, 136)
    c.ellipse((300, 74, 319, 93), fill=232)
    for i in range(38):
        x, y = c.rng.uniform(12, 394), c.rng.uniform(68, 141)
        c.ellipse((x, y, x+.55, y+.55), fill=c.rng.randint(130, 207))
    c.polygon([(0, 148), (53, 133), (102, 143), (154, 126), (207, 145), (263, 131), (325, 146), (400, 129), (400, 209), (0, 209)], 65)
    c.polygon([(0, 177), (63, 163), (126, 174), (196, 157), (274, 172), (341, 158), (400, 176), (400, 300), (0, 300)], 49)
    c.facet([(189, 167), (210, 167), (372, 300), (31, 300)], 64, 30)
    c.line([(189, 167), (31, 300)], 139, 1.3)
    c.line([(210, 167), (372, 300)], 139, 1.3)
    for i in range(9):
        t = i/8
        y = 174 + t*t*122
        left = 198 - t*8; right = 202 + t*8
        c.line([(left, y), (right, y+4+t*8)], 210, 1+t*2)
    for x in (53, 103, 306, 353):
        c.line([(x, 116), (x, 221)], 43, 2.2)
        c.line([(x-11, 128), (x+11, 128)], 50, 1.5)
    c.line(bezier((42, 128), (151, 153), (260, 143), (364, 128)), 61, .9)
    c.line(bezier((42, 133), (151, 158), (260, 148), (364, 133)), 55, .7)
    c.polygon([(176, 184), (187, 175), (212, 175), (226, 185), (227, 198), (174, 198)], 42)
    c.rectangle((187, 178, 211, 187), fill=107, radius=2)
    for x in (180, 218):
        c.light(x, 192, 22, 244, .6)
        c.ellipse((x-3, 190, x+3, 195), fill=250)
        c.soft_polygon([(x-2, 197), (x+2, 197), (x+21, 267), (x-15, 267)], 165, 5)
    for x, y in ((59, 228), (330, 235), (88, 198), (302, 199)):
        c.rectangle((x, y, x+3, y+15), fill=180)
        c.rectangle((x, y, x+3, y+4), fill=239)
    c.texture(2)
    c.label("midnight-road", "午夜公路", 4, True)


for renderer in (rain_street, cafe, city_voices, midnight_road):
    renderer()

sheet = Image.new("L", (888, 668), 187)
for index, name in enumerate(NAMES):
    image = Image.open(OUT / f"{name}.png")
    assert image.size == (400, 300) and image.mode == "L"
    assert len(image.getcolors(256)) > 200
    sheet.paste(image, (24 + index % 2 * 440, 24 + index // 2 * 320))
sheet.save(OUT / "contact-sheet.png", optimize=True)
print("generated 4 field-recording covers")
