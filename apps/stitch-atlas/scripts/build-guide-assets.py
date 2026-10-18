"""Generate original guide diagrams and 2:3 Pinterest concept PNGs.

No copyrighted competitor photography, untested pattern claims, or placeholder URL.
The SVGs are explanatory illustrations, not standardized crochet charts.
"""
from __future__ import annotations
import html
import json
from pathlib import Path
import io
import math
from PIL import Image, ImageDraw, ImageFont, ImageOps
import cairosvg

ROOT = Path(__file__).resolve().parent.parent
VISUALS = ROOT / 'public' / 'guides'
PINS = ROOT / 'public' / 'pins'
VISUALS.mkdir(parents=True,exist_ok=True)
PINS.mkdir(parents=True,exist_ok=True)
INK='#243b2f'; RUST='#b36f57'; CREAM='#faf5ec'; SAGE='#dbe7d9'; GREEN='#64826c'; PAPER='#f4e9da'; LINEN='#d5c2a8'; GRAY='#65766a'


def esc(s): return html.escape(s,quote=True)
def label(x,y,s,size=22,color=INK,serif=False,weight=500,anchor='start'):
    family='Georgia,serif' if serif else 'Arial,sans-serif'
    return f'<text x="{x}" y="{y}" fill="{color}" font-family="{family}" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">{esc(s)}</text>'

def path(d,color=INK,w=3,fill='none',extra=''):
    return f'<path d="{d}" stroke="{color}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round" fill="{fill}" {extra}/>'

def base(title,subtitle,art,seq):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 720" width="1200" height="720" role="img" aria-labelledby="title description">
    <title id="title">{esc(title)}</title><desc id="description">{esc(subtitle)}. Original Stitch Atlas explanatory illustration, not a tested project pattern.</desc>
    <defs><pattern id="paper-grain" width="56" height="56" patternUnits="userSpaceOnUse"><path d="M0 28h56 M28 0v56" stroke="#cabbab" opacity=".20" stroke-width=".7"/></pattern>
    <pattern id="loops" width="42" height="48" patternUnits="userSpaceOnUse"><path d="M1 25Q9 3 22 24T42 25" fill="none" stroke="#e7eee0" stroke-width="5"/></pattern></defs>
    <rect width="1200" height="720" rx="0" fill="{CREAM}"/><rect width="1200" height="720" fill="url(#paper-grain)"/>
    <path d="M82 86h1036" stroke="#c4bba9" stroke-width="1"/>
    {label(83,63,'STITCH ATLAS  /  VISUAL FIELD NOTES',16,RUST,False,700)}
    {label(1114,63,'STUDY  /  '+seq,16,GREEN,False,700,'end')}
    {art}
    <path d="M82 642h1036" stroke="#c4bba9" stroke-width="1"/>
    {label(84,677,title,25,INK,True,500)}
    {label(1114,677,'ILLUSTRATION · NOT A FINISHED PATTERN',13,GRAY,False,700,'end')}
    </svg>'''

def count_art():
    a=['<rect x="110" y="170" width="980" height="354" rx="22" fill="#e1e9dc"/>']
    for row in range(3):
        y=240+row*80
        a.append(path(f'M170 {y+19}Q210 {y-22} 247 {y+19} Q285 {y-22} 323 {y+19} T399 {y+19} T475 {y+19} T551 {y+19} T627 {y+19} T703 {y+19} T779 {y+19} T855 {y+19} T931 {y+19} T1007 {y+19}',GREEN,9))
    for i in range(8):
        x=245+i*96
        a.append(path(f'M{x-25} 205L{x} 233L{x+25} 205',RUST,6))
        a.append(f'<circle cx="{x}" cy="164" r="18" fill="#fff7ef" stroke="{RUST}" stroke-width="2"/>')
        a.append(label(x,172,str(i+1),21,INK,True,600,'middle'))
    a.extend([label(135,586,'Count the top V of each completed stitch',27,INK,True),label(1025,583,'MARK BOTH EDGES',15,RUST,False,700,'end')])
    return ''.join(a)

def terms_art():
    return f'''<rect x="108" y="151" width="476" height="405" rx="20" fill="{SAGE}"/>
    <rect x="616" y="151" width="476" height="405" rx="20" fill="#ead9cf"/>
    {label(155,211,'UNITED STATES',24,GREEN,False,700)}{label(663,211,'UNITED KINGDOM',24,RUST,False,700)}
    {label(345,375,'sc',155,INK,True,500,'middle')}{label(852,375,'dc',155,INK,True,500,'middle')}
    {path('M527 346h144 M639 319l32 27-32 26',RUST,7)}
    {label(345,442,'single crochet',27,GRAY,True,400,'middle')}
    {label(852,442,'double crochet',27,GRAY,True,400,'middle')}
    {label(155,506,'SAME PHYSICAL STITCH',17,GREEN,False,700)}
    {label(661,506,'DIFFERENT STITCH NAME',17,RUST,False,700)}
    {label(150,602,'Always check the terminology used by the original instructions.',26,INK,True)}'''

def gauge_art():
    out=['<rect x="202" y="151" width="690" height="405" rx="11" fill="#dce8d8"/>']
    for row in range(7):
        y=204+row*48
        for col in range(13):
            x=246+col*48
            out.append(path(f'M{x-15} {y-10}Q{x} {y+24} {x+15} {y-10}',GREEN,5))
    out.append('<rect x="270" y="200" width="540" height="304" fill="none" stroke="#bc795f" stroke-width="6" stroke-dasharray="17 12"/>')
    out.extend([path('M270 160h540 M270 148v23 M810 148v23',INK,4),label(540,138,'MEASURE IN THE CENTER',19,INK,False,700,'middle'),path('M868 200v304 M853 200h30 M853 504h30',INK,4),label(960,335,'ROWS',19,GREEN,False,700),label(960,367,'up / down',20,INK,True),label(440,597,'STITCHES  ·  left / right',23,INK,True)])
    return ''.join(out)

def yarn_art():
    a=[]
    colors=[('#b7735d',197),('#688b72',477),('#c4a97f',757)]
    for col,x in colors:
        a.extend([f'<ellipse cx="{x+120}" cy="418" rx="125" ry="166" fill="{col}" opacity=".91"/>',f'<ellipse cx="{x+120}" cy="421" rx="93" ry="143" fill="none" stroke="#f7ecdc" stroke-width="7" opacity=".6"/>'])
        for v in range(5):
            q=x+65+v*28
            a.append(path(f'M{q} 298q84 113 0 234',"#e9e5d7",7))
        a.append(f'<rect x="{x+45}" y="384" width="149" height="73" rx="10" fill="{PAPER}"/>')
    a.extend([label(317,608,'THE FIBER',21,INK,True,500,'middle'),label(597,608,'THE STITCH',21,INK,True,500,'middle'),label(877,608,'THE STRAP',21,INK,True,500,'middle'),label(103,185,'A strong bag is a fabric-and-construction decision.',29,INK,True)])
    return ''.join(a)

def lining_art():
    a=[f'<path d="M216 190h420l-37 376H251l-35-376Z" fill="{SAGE}" stroke="{GREEN}" stroke-width="10"/>',f'<path d="M294 215v-42q0-71 129-71t129 71v42" fill="none" stroke="{GREEN}" stroke-width="13"/>',f'<path d="M285 263h279l-23 245H309l-24-245Z" fill="#f4d5c8" stroke="{RUST}" stroke-width="6" stroke-dasharray="14 12"/>',path('M331 307h192 M328 354h198 M325 401h202 M324 448h204',RUST,4),path('M643 347h107',INK,4),path('M731 332l19 15-19 15',INK,4),f'<rect x="771" y="215" width="235" height="293" fill="#e9d4bf" stroke="{RUST}" stroke-width="6"/>',path('M787 239v251 M990 239v251',INK,2,extra='stroke-dasharray="12 10"'),label(884,555,'FABRIC MOCK-UP',19,INK,False,700,'middle'),label(883,593,'Fit before stitching',25,INK,True,400,'middle'),label(260,594,'BAG INTERIOR',19,GREEN,False,700)]
    return ''.join(a)

def moss_art():
    a=[f'<rect x="135" y="170" width="935" height="389" rx="17" fill="{SAGE}"/>']
    for row in range(5):
        y=232+row*61
        offset=40 if row%2 else 0
        for col in range(9):
            x=193+col*93+offset
            if x>1020:continue
            a.append(f'<rect x="{x}" y="{y}" width="41" height="29" rx="12" fill="{GREEN}"/>')
            a.append(path(f'M{x+50} {y+16}q19-21 35 0',RUST,7))
    a.extend([label(224,594,'SOLID = single crochet',21,INK,True),label(685,594,'CURVE = ch-1 space',21,INK,True),label(140,137,'Simplified rhythm illustration — not a pattern chart',24,INK,True)])
    return ''.join(a)

GUIDES=[
    ('how-to-count-crochet-stitches','Find each stitch.','Count with confidence.','Stop the off-by-one mistake before it grows.',count_art,'01'),
    ('us-uk-crochet-terms','US vs UK crochet','without the confusion','Same stitch. Different name. Keep the chart handy.',terms_art,'02'),
    ('how-to-measure-crochet-gauge','The gauge swatch','that tells the truth','Know your stitch count before starting a project.',gauge_art,'03'),
    ('how-to-choose-yarn-for-crochet-bags','Choose bag yarn','with intention','Structure, handles, load and fabric—together.',yarn_art,'04'),
    ('how-to-line-a-crochet-bag','Fit a fabric lining','the thoughtful way','Measure the finished bag. Mock up. Then stitch.',lining_art,'05'),
    ('moss-stitch-crochet-explained','See moss stitch','as a gentle rhythm','Single crochets and chain spaces, made understandable.',moss_art,'06'),
]
for slug,headline1,headline2,subtitle,art_fn,idx in GUIDES:
    diagram=base(headline1+' '+headline2,subtitle,art_fn(),idx)
    diagram_file = {
        'how-to-count-crochet-stitches':'count-stitches.svg',
        'us-uk-crochet-terms':'us-uk-terms.svg',
        'how-to-measure-crochet-gauge':'gauge-swatch.svg',
        'how-to-choose-yarn-for-crochet-bags':'bag-yarn.svg',
        'how-to-line-a-crochet-bag':'bag-lining.svg',
        'moss-stitch-crochet-explained':'moss-stitch.svg',
    }[slug]
    (VISUALS/diagram_file).write_text(diagram,encoding='utf8')
    # Explanatory graphic forms 1000x1500 Pinterest-ready raster; entirely original artwork.
    img=Image.new('RGB',(1000,1500),'#faf5ec');d=ImageDraw.Draw(img)
    d.rectangle((0,0,1000,24),fill=INK)
    d.text((76,98),'STITCH ATLAS   /   THE MAKER NOTEBOOK',font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',22),fill=RUST)
    def f(size,serif=True):return ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf' if serif else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',size)
    y=191
    for line in [headline1,headline2]:
        font=f(66)
        textbbox=d.textbbox((0,0),line,font=font)
        if textbbox[2]>850:
            font=f(56)
        d.text((76,y),line,font=font,fill=INK if y==191 else RUST)
        y+=96
    d.text((76,426),'FREE CROCHET LEARNING GUIDE',font=f(25,False),fill=GREEN)
    d.rounded_rectangle((68,500,932,1150),radius=29,fill='#e3e9dd')
    screenshot=cairosvg.svg2png(bytestring=diagram.encode(),output_width=850,output_height=510)
    art_img=Image.open(io.BytesIO(screenshot)).convert('RGB')
    img.paste(art_img,(75,568))
    d=ImageDraw.Draw(img)
    d.line((75,1205,925,1205),fill=RUST,width=4)
    # Word-wrap descriptive subtitle for graphic accessibility.
    parts=subtitle.split(' ');lines=[];line=''
    for word in parts:
        trial=(line+' '+word).strip()
        if d.textbbox((0,0),trial,font=f(28))[2]>836 and line:
            lines.append(line);line=word
        else:line=trial
    if line:lines.append(line)
    for i,txt in enumerate(lines[:2]):d.text((75,1246+45*i),txt,font=f(28),fill=INK)
    d.text((75,1406),'ORIGINAL ILLUSTRATION   ·   NOT A FINISHED PATTERN',font=f(18,False),fill=GRAY)
    img.save(PINS/(slug+'.png'),format='PNG',optimize=True)
    print(slug, len(diagram), (PINS/(slug+'.png')).stat().st_size)

manifest=[{'slug':slug,'image':f'/pins/{slug}.png','targetPath':f'/guides/{slug}',
  'pinTitle':(h1+' '+h2).strip(),'pinDescription':subtitle+' Read the free learning guide at Stitch Atlas.',
  'status':'draft_no_verified_canonical_or_pinterest_account', 'approvedToPublish':False,
  'imageRights':'Original Stitch Atlas diagram artwork; no competitor photography.'}
  for slug,h1,h2,subtitle,_,_ in GUIDES]
(ROOT/'docs/PINTEREST_ASSETS_MANIFEST.json').write_text(json.dumps({'site':'Stitch Atlas','destinationHost':None,'autopublish':False,'pins':manifest},indent=2),encoding='utf8')
print('Generated',len(GUIDES),'SVG diagrams and 1000x1500 PNG Pinterest draft assets')
