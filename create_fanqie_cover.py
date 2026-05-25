from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops
import math, random, os

random.seed(20260520)
OUT_DIR = r"E:\GptChat\001"
S = 3
W, H = 600*S, 800*S

def sc(v):
    return int(round(v*S))

def color_lerp(a, b, t):
    return tuple(int(a[i] + (b[i]-a[i])*t) for i in range(3))

# ---------- Background: deep space gradient ----------
img = Image.new('RGBA', (W, H), (0,0,0,255))
pix = img.load()
top = (3, 6, 27)
mid = (18, 12, 65)
bot = (5, 34, 63)
for y in range(H):
    t = y/(H-1)
    if t < 0.55:
        c = color_lerp(top, mid, t/0.55)
    else:
        c = color_lerp(mid, bot, (t-0.55)/0.45)
    for x in range(W):
        # slight radial darkening at corners
        dx = (x-W/2)/(W/2)
        dy = (y-H/2)/(H/2)
        vign = min(0.48, (dx*dx + dy*dy)*0.12)
        pix[x,y] = (max(0,int(c[0]*(1-vign))), max(0,int(c[1]*(1-vign))), max(0,int(c[2]*(1-vign))), 255)

# Nebula color clouds
for _ in range(22):
    layer = Image.new('RGBA', (W,H), (0,0,0,0))
    d = ImageDraw.Draw(layer, 'RGBA')
    cx = random.randint(sc(-80), sc(680))
    cy = random.randint(sc(60), sc(720))
    rw = random.randint(sc(80), sc(260))
    rh = random.randint(sc(40), sc(180))
    palette = random.choice([(84,45,180,28), (0,180,220,20), (255,92,36,16), (126,40,120,22)])
    d.ellipse((cx-rw, cy-rh, cx+rw, cy+rh), fill=palette)
    layer = layer.filter(ImageFilter.GaussianBlur(random.randint(sc(18), sc(48))))
    img.alpha_composite(layer)

# Star field
stars = Image.new('RGBA', (W,H), (0,0,0,0))
d = ImageDraw.Draw(stars, 'RGBA')
for i in range(900):
    x = random.randrange(W)
    y = random.randrange(sc(20), sc(730))
    brightness = random.randint(90, 240)
    r = random.choice([1,1,1,2,2,3])
    if r == 1:
        d.point((x,y), fill=(brightness, brightness, min(255, brightness+20), random.randint(90,210)))
    else:
        d.ellipse((x-r, y-r, x+r, y+r), fill=(brightness, brightness, min(255, brightness+35), random.randint(35,95)))
# a few cross stars
for i in range(28):
    x = random.randrange(sc(20), sc(580)); y = random.randrange(sc(20), sc(650))
    a = random.randint(90,170); l = random.randint(sc(3), sc(9))
    d.line((x-l,y,x+l,y), fill=(160,220,255,a), width=1)
    d.line((x,y-l,x,y+l), fill=(160,220,255,a), width=1)
img.alpha_composite(stars)

# ---------- Shockwave / orbital energy rings ----------
ring = Image.new('RGBA', (W,H), (0,0,0,0))
d = ImageDraw.Draw(ring, 'RGBA')
pcx, pcy, pr = sc(300), sc(465), sc(176)
# Back rings
for offset, col, width in [(-18,(36,210,255,70),2), (12,(255,142,57,66),3), (38,(118,80,255,44),2)]:
    bbox = (pcx-sc(235+offset), pcy-sc(78+offset*0.18), pcx+sc(235+offset), pcy+sc(78+offset*0.18))
    d.arc(bbox, 186, 356, fill=col, width=sc(width))
    d.arc((bbox[0]+sc(18),bbox[1]+sc(8),bbox[2]-sc(18),bbox[3]-sc(8)), 12, 168, fill=(col[0],col[1],col[2],max(20,col[3]-22)), width=sc(1))
ring = ring.filter(ImageFilter.GaussianBlur(sc(0.3)))
img.alpha_composite(ring)

# ---------- Planet sphere ----------
planet = Image.new('RGBA', (W,H), (0,0,0,0))
mask = Image.new('L', (W,H), 0)
md = ImageDraw.Draw(mask)
md.ellipse((pcx-pr, pcy-pr, pcx+pr, pcy+pr), fill=255)
pp = planet.load(); mp = mask.load()
light = (-0.55, -0.42, 0.72)
for yy in range(pcy-pr, pcy+pr+1):
    if yy < 0 or yy >= H: continue
    for xx in range(pcx-pr, pcx+pr+1):
        if xx < 0 or xx >= W: continue
        nx = (xx-pcx)/pr; ny = (yy-pcy)/pr
        rr = nx*nx + ny*ny
        if rr <= 1:
            nz = math.sqrt(max(0, 1-rr))
            dot = max(0, nx*light[0] + ny*light[1] + nz*light[2])
            rim = (1 - nz)
            tex = 0.5 + 0.5*math.sin(9*nx + 4*math.sin(7*ny)) * math.sin(6*ny+2.2)
            # bluish crust with purple lowlands
            r = int(18 + 42*dot + 18*tex - 16*rim)
            g = int(36 + 74*dot + 22*tex - 22*rim)
            b = int(78 + 116*dot + 45*tex - 20*rim)
            # night side violet
            if nx > 0.18 or ny > 0.25:
                r += int(28*(nx+0.25))
                b += int(12*(nx+0.2))
            # atmospheric edge
            edge = max(0, (math.sqrt(rr)-0.82)/0.18)
            g = int(g*(1-edge) + 78*edge)
            b = int(b*(1-edge) + 150*edge)
            pp[xx,yy] = (max(0,min(255,r)), max(0,min(255,g)), max(0,min(255,b)), 255)

# Planet edge glow
edge_layer = Image.new('RGBA', (W,H), (0,0,0,0))
ed = ImageDraw.Draw(edge_layer, 'RGBA')
ed.ellipse((pcx-pr-sc(4),pcy-pr-sc(4),pcx+pr+sc(4),pcy+pr+sc(4)), outline=(52,230,255,155), width=sc(3))
edge_layer = edge_layer.filter(ImageFilter.GaussianBlur(sc(3)))
img.alpha_composite(edge_layer)

# Lava cracks and explosion point
cracks = Image.new('RGBA', (W,H), (0,0,0,0))
cd = ImageDraw.Draw(cracks, 'RGBA')
ex, ey = pcx + sc(66), pcy - sc(42)
# helper for jagged line
def jagged_path(start, angle, length, steps=7, jitter=16):
    pts=[start]
    x,y=start
    for i in range(1, steps+1):
        t=i/steps
        nx = start[0] + math.cos(angle)*length*t + random.randint(-sc(jitter), sc(jitter))
        ny = start[1] + math.sin(angle)*length*t + random.randint(-sc(jitter), sc(jitter))
        pts.append((int(nx), int(ny)))
    return pts

main_angles = [-2.45, -1.85, -1.1, -0.52, 0.08, 0.62, 1.12, 1.72, 2.4]
for ang in main_angles:
    length = random.randint(sc(80), sc(190))
    pts = jagged_path((ex,ey), ang, length, steps=random.randint(5,8), jitter=random.randint(5,13))
    # glow underneath
    cd.line(pts, fill=(255,72,14,112), width=sc(random.randint(7,11)), joint='curve')
    cd.line(pts, fill=(255,186,58,210), width=sc(random.randint(2,4)), joint='curve')
    cd.line(pts, fill=(255,245,196,230), width=sc(1), joint='curve')
    # branches
    if random.random() < 0.75:
        bstart = random.choice(pts[2:-1])
        bang = ang + random.choice([-1,1])*random.uniform(0.55,1.05)
        bpts = jagged_path(bstart, bang, random.randint(sc(35), sc(84)), steps=4, jitter=8)
        cd.line(bpts, fill=(255,91,22,92), width=sc(5), joint='curve')
        cd.line(bpts, fill=(255,213,99,190), width=sc(2), joint='curve')

# Clip cracks to planet mask
alpha = cracks.getchannel('A')
cracks.putalpha(ImageChops.multiply(alpha, mask))
cracks_glow = cracks.filter(ImageFilter.GaussianBlur(sc(2)))
img.alpha_composite(planet)
img.alpha_composite(cracks_glow)
img.alpha_composite(cracks)

# Explosion bloom on the sphere
bloom = Image.new('RGBA', (W,H), (0,0,0,0))
bd = ImageDraw.Draw(bloom, 'RGBA')
for rad, col in [(72,(255,83,20,70)), (42,(255,150,35,130)), (20,(255,232,141,235)), (8,(255,255,245,255))]:
    bd.ellipse((ex-sc(rad),ey-sc(rad),ex+sc(rad),ey+sc(rad)), fill=col)
# rays
for i in range(24):
    a = random.random()*math.tau
    l = random.randint(sc(70), sc(180))
    bd.line((ex,ey,ex+math.cos(a)*l,ey+math.sin(a)*l), fill=(255,118,36,random.randint(35,95)), width=random.randint(sc(1),sc(3)))
bloom_blur = bloom.filter(ImageFilter.GaussianBlur(sc(10)))
img.alpha_composite(bloom_blur)
img.alpha_composite(bloom)

# Foreground arcs
fg = Image.new('RGBA', (W,H), (0,0,0,0))
fd = ImageDraw.Draw(fg, 'RGBA')
for offset, col, start, end in [(0,(255,170,52,95), 198, 336), (22,(50,225,255,85), 202, 336)]:
    bbox=(pcx-sc(242+offset), pcy-sc(84+offset*0.12), pcx+sc(242+offset), pcy+sc(84+offset*0.12))
    fd.arc(bbox, start, end, fill=col, width=sc(3))
# debris shards around planet
for i in range(36):
    a = random.uniform(-0.25, math.tau-0.25)
    dist = random.randint(sc(200), sc(295))
    x = pcx + int(math.cos(a)*dist)
    y = pcy + int(math.sin(a)*dist*0.82)
    size = random.randint(sc(2), sc(7))
    rot = a + random.random()*1.2
    pts=[]
    for k in range(3):
        aa = rot + k*2.09
        pts.append((x+int(math.cos(aa)*size*random.uniform(0.8,1.7)), y+int(math.sin(aa)*size*random.uniform(0.8,1.7))))
    col=random.choice([(255,130,46,135),(80,220,255,115),(172,132,255,105)])
    fd.polygon(pts, fill=col)
fg = fg.filter(ImageFilter.GaussianBlur(sc(0.15)))
img.alpha_composite(fg)

# Vignette / dark panels for readability
v = Image.new('RGBA', (W,H), (0,0,0,0))
vd = ImageDraw.Draw(v, 'RGBA')
# top title backing glow shadow
vd.rounded_rectangle((sc(36), sc(34), sc(564), sc(266)), radius=sc(28), fill=(0,5,24,65))
# bottom author strip
vd.rounded_rectangle((sc(128), sc(725), sc(472), sc(770)), radius=sc(22), fill=(1,7,22,150), outline=(80,198,255,90), width=sc(1))
v = v.filter(ImageFilter.GaussianBlur(sc(0.6)))
img.alpha_composite(v)

# ---------- Text ----------
font_title = r"C:\Windows\Fonts\NotoSansSC-VF.ttf"
font_serif = r"C:\Windows\Fonts\NotoSerifSC-VF.ttf"
font_sans = r"C:\Windows\Fonts\NotoSansSC-VF.ttf"
for p in [font_title, font_serif, font_sans]:
    if not os.path.exists(p):
        raise FileNotFoundError(p)

# Try a solid Chinese font; stroke adds weight and improves thumbnail clarity
title_font1 = ImageFont.truetype(font_serif, sc(62))
title_font2 = ImageFont.truetype(font_serif, sc(88))
author_font = ImageFont.truetype(font_sans, sc(24))
small_font = ImageFont.truetype(font_sans, sc(16))

def glow_text(base, xy, text, font, fill, stroke_fill=(7,10,28,255), stroke_width=3, glow=(0,210,255,120), glow_radius=7, anchor='mm'):
    layer = Image.new('RGBA', base.size, (0,0,0,0))
    ld = ImageDraw.Draw(layer)
    # bold outer glow through thick strokes
    ld.text(xy, text, font=font, fill=glow, stroke_width=stroke_width+sc(5), stroke_fill=glow, anchor=anchor)
    blur = layer.filter(ImageFilter.GaussianBlur(glow_radius))
    base.alpha_composite(blur)
    bd = ImageDraw.Draw(base)
    bd.text(xy, text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill, anchor=anchor)

# Title line 1
glow_text(img, (sc(300), sc(92)), "我的星球", title_font1,
          fill=(235,249,255,255), stroke_fill=(5,12,40,255), stroke_width=sc(2),
          glow=(0,213,255,112), glow_radius=sc(5), anchor='mm')

# Title line 2 split so the explosive words feel hot while retaining exact text
text_a, text_b = "能", "爆炸"
dummy = ImageDraw.Draw(Image.new('RGBA',(1,1)))
w_a = dummy.textlength(text_a, font=title_font2)
w_b = dummy.textlength(text_b, font=title_font2)
x0 = sc(300) - int((w_a + w_b)/2)
y2 = sc(185)
glow_text(img, (x0, y2), text_a, title_font2,
          fill=(242,252,255,255), stroke_fill=(5,9,32,255), stroke_width=sc(2),
          glow=(0,204,255,98), glow_radius=sc(5), anchor='lm')
glow_text(img, (x0 + int(w_a), y2), text_b, title_font2,
          fill=(255,215,96,255), stroke_fill=(44,10,2,255), stroke_width=sc(2),
          glow=(255,82,23,150), glow_radius=sc(7), anchor='lm')

# small accent subtitle-like visual text; keep platform-safe and minimal
# Avoid adding external logos/watermarks; this is purely genre mood text.
accent = Image.new('RGBA',(W,H),(0,0,0,0))
ad = ImageDraw.Draw(accent)
ad.text((sc(300), sc(266)), "星核崩裂 · 命运重启", font=small_font, fill=(126,224,255,160), anchor='mm')
img.alpha_composite(accent)

# Author
glow_text(img, (sc(300), sc(748)), "风语筑知 著", author_font,
          fill=(230,246,255,255), stroke_fill=(1,8,28,255), stroke_width=sc(1),
          glow=(66,210,255,80), glow_radius=sc(3), anchor='mm')

# Thin border
bd = ImageDraw.Draw(img, 'RGBA')
bd.rounded_rectangle((sc(6), sc(6), sc(594), sc(794)), radius=sc(12), outline=(78,210,255,105), width=sc(2))
bd.rounded_rectangle((sc(12), sc(12), sc(588), sc(788)), radius=sc(8), outline=(255,150,56,50), width=sc(1))

# Downsample for official upload size
final = img.resize((600,800), Image.Resampling.LANCZOS).convert('RGB')
# subtle sharpen
final = final.filter(ImageFilter.UnsharpMask(radius=1.2, percent=115, threshold=3))

png_path = os.path.join(OUT_DIR, 'fanqie_cover_my_planet_explodes_600x800.png')
jpg_path = os.path.join(OUT_DIR, 'fanqie_cover_my_planet_explodes_600x800.jpg')
final.save(png_path, optimize=True)
final.save(jpg_path, quality=94, optimize=True, progressive=True)

prompt_path = os.path.join(OUT_DIR, 'fanqie_cover_my_planet_explodes_prompt.txt')
with open(prompt_path, 'w', encoding='utf-8') as f:
    f.write('''Use case: stylized-concept\nAsset type: 番茄小说封面，600x800竖版\nPrimary request: 为《我的星球能爆炸》（作者：风语筑知）制作一张原创封面。\nScene/backdrop: 深空、星云、星环能量波。\nSubject: 一颗正在裂解的蓝紫色星球，星核从裂缝中爆发橙金色光芒，周围有碎片和冲击波。\nStyle/medium: 电影感科幻玄幻概念封面，强对比、移动端缩略图可读。\nText (verbatim): "我的星球能爆炸"；"风语筑知 著"\nConstraints: 不使用真人照片、不含平台logo/水印/二维码，文字清晰无遮挡。\n''')

for p in [png_path, jpg_path, prompt_path]:
    print(p, os.path.getsize(p))
