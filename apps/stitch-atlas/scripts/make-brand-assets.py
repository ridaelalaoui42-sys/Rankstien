from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
import cairosvg, io, math
root=Path(__file__).resolve().parent.parent
brand=root/'public/brand'; cats=root/'public/category'; imgs=root/'public/images'
brand.mkdir(exist_ok=True,parents=True); cats.mkdir(exist_ok=True,parents=True)
ink='#24382e'; rust='#b66e57'; beige='#faf6ef'; sage='#718776'; white='#fffaf0'
mark='''<circle cx="55" cy="58" r="36" fill="none" stroke="{color}" stroke-width="3.8"/>
<path d="M25 44c25-22 41-23 60-11M20 54c21-19 49-28 68-8M21 65c18-19 45-25 69-12M31 81c7-16 26-31 53-28M46 92c3-21 17-33 39-36M23 47C32 70 56 89 72 90M35 30c-2 27 26 51 40 55M46 23c-3 24 27 43 38 48" fill="none" stroke="{color}" stroke-width="2.3" stroke-linecap="round"/>
<path d="M81 91Q100 109 121 98M93 101Q105 77 122 70" fill="none" stroke="{color}" stroke-width="3.1" stroke-linecap="round"/>
<path d="M121 71Q99 70 99 88Q114 91 121 71Z" fill="{leaf}"/>
<path d="M121 98Q116 115 99 112Q99 99 121 98Z" fill="{leaf}"/>
<circle cx="25" cy="27" r="3.5" fill="{leaf}"/>'''
def svg(inner,w,h,view=None,bg='none'):
 return f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="{view or f"0 0 {w} {h}"}" role="img"><rect width="100%" height="100%" fill="{bg}"/>{inner}</svg>'
def put(name,content): (brand/name).write_text(content,encoding='utf-8')
put('mark.svg',svg(mark.format(color=rust,leaf=sage),140,140,'0 0 140 140'))
put('mark-inverse.svg',svg(mark.format(color=white,leaf='#d8aa91'),140,140,'0 0 140 140'))
for inverse in [False,True]:
 foreground=white if inverse else ink
 lines=f'''<g transform="translate(8,10) scale(.45)">{mark.format(color='#f5d6c4' if inverse else rust,leaf='#c1d1ba' if inverse else sage)}</g>
<text x="78" y="50" fill="{foreground}" font-family="Georgia,Times New Roman,serif" font-size="41" letter-spacing="-2">Stitch <tspan fill="{'#efc1a9' if inverse else rust}">Atlas</tspan></text>
<text x="80" y="67" fill="{'#ccd9ca' if inverse else '#637668'}" font-family="Arial,sans-serif" font-size="8.6" font-weight="bold" letter-spacing="2.3">CROCHET · CREATIVE LIVING</text>'''
 put('wordmark-inverse.svg' if inverse else 'wordmark.svg',svg(lines,340,82,bg='none'))
put('divider.svg',svg('<path d="M0 16H102 M155 16H280" stroke="#c4bdad"/><path d="M124 5q-8 14 10 23q16-7 10-23q-16 7-20 0Z" fill="none" stroke="#b66e57" stroke-width="2.6"/>',280,35))
put('motif-tile.svg',svg('''<defs><pattern id="st" width="54" height="58" patternUnits="userSpaceOnUse"><path d="M7 12C16 1 34 3 39 16C45 32 26 43 15 31C4 21 15 10 24 16C31 24 20 27 18 23M18 28Q10 48 32 53" fill="none" stroke="#718776" stroke-width="4" opacity=".4" stroke-linecap="round"/></pattern></defs><rect width="320" height="320" fill="url(#st)"/>''',320,320))
put('illustration.svg',svg('''<defs><pattern id="threads" width="38" height="38" patternUnits="userSpaceOnUse"><path d="M4 8Q14 0 23 8T32 24Q26 36 14 30T4 8Z" fill="none" stroke="#fff6e8" opacity=".37" stroke-width="4"/></pattern></defs>
<ellipse cx="380" cy="655" rx="255" ry="26" fill="#3c674b" opacity=".1"/>
<path d="M197 525q-77-76-17-192q31-58 110-80q134-33 218 73q87 109 7 227q-75 105-209 77q-82-18-109-105Z" fill="#faf1de" stroke="#b9745d" stroke-width="4"/>
<path d="M197 525q-77-76-17-192q31-58 110-80q134-33 218 73q87 109 7 227q-75 105-209 77q-82-18-109-105Z" fill="url(#threads)"/>
<path d="M220 333q107-53 219 21M175 412q142-79 341-4M181 501q123-87 338-7M220 566q125-65 250-37" stroke="#b9745d" stroke-width="18" stroke-linecap="round" fill="none" opacity=".65"/>
<path d="M251 285q-23 151 137 341M305 255q-36 174 133 355M366 264q-15 168 98 309M425 310q-27 135 35 204" stroke="#c7896b" stroke-width="13" opacity=".53" stroke-linecap="round" fill="none"/>
<path d="M427 215L556 596" stroke="#e4c79f" stroke-width="18" stroke-linecap="round"/><path d="M427 215q-27-58 4-78q35-15 41 18q3 26-34 43" fill="none" stroke="#e4c79f" stroke-width="16" stroke-linecap="round"/><path d="M482 128L578 410" stroke="#f8edd2" stroke-width="17" stroke-linecap="round"/><path d="M482 128q-13-30 2-53q21-13 30 12t-25 30" fill="none" stroke="#f8edd2" stroke-width="14"/>
<path d="M112 587Q78 455 116 314M104 459Q55 454 38 405M108 403Q148 363 155 308" fill="none" stroke="#466651" stroke-width="7"/><path d="M116 314Q71 301 70 355Q109 358 116 314ZM108 403Q155 390 154 430Q129 444 108 403ZM98 471Q64 455 56 484Q80 505 98 471ZM122 356Q151 334 171 355Q163 377 122 356Z" fill="#527b61"/>
<path d="M623 608Q647 526 625 445M627 496Q593 476 576 453M637 540Q678 510 693 480" fill="none" stroke="#355f4c" stroke-width="7"/><path d="M625 448Q597 433 596 459Q614 473 625 448ZM632 512Q665 481 672 508Q650 535 632 512ZM634 554Q596 544 603 577Q626 582 634 554Z" fill="#537e60"/>
<path d="M305 664q72 30 158 1" stroke="#b9745d" stroke-width="3" fill="none" opacity=".5"/>''',750,750,'0 0 750 750'))
# Category icons based on shared outline style
paths={
 'bag':'<path d="M51 45h96l14 117H37L51 45Z"/><path d="M73 57V34q0-35 26-35t26 35v23"/><path d="M58 118q41-25 81 0M58 134q41-25 81 0"/>',
 'stitch':'<path d="M24 84Q42 25 79 44T137 94Q156 149 119 154T45 144Q12 128 24 84Z"/><path d="M36 83q33-39 80-18M33 107q58-42 101-2M47 132q45-35 82-17M86 51q-23 57 10 93M107 58q-22 49 10 78"/>',
 'yarn':'<circle cx="93" cy="100" r="67"/><path d="M33 77q66-54 121-22M28 103q69-52 131-18M38 135q67-53 109-28M62 45q-12 69 59 109M91 35q-13 75 44 98"/><path d="M151 151l26 20"/>',
 'blanket':'<path d="M27 48h136v113H27z"/><path d="M47 57v94M75 57v94M102 57v94M132 57v94M38 77h117M38 105h117M38 134h117"/><path d="M163 48q15 0 16 14v106q-13 18-26-7"/>',
 'flower':'<circle cx="96" cy="104" r="13"/><path d="M96 90Q64 46 96 34Q127 42 102 91ZM111 100Q152 66 162 98Q154 133 111 107ZM108 114Q137 163 104 174Q77 160 95 118ZM88 112Q47 144 29 118Q35 81 83 101ZM87 95Q73 51 47 65Q21 99 82 105Z"/><path d="M96 118l2 70"/>',
 'square':'<path d="M26 26h148v148H26z"/><path d="M43 43h114v114H43zM61 61h78v78H61zM80 80h40v40H80z"/><path d="M26 26l35 35M174 26l-35 35M26 174l35-35M174 174l-35-35"/>',
}
for key,path in paths.items():
 s=svg(f'<g stroke="{ink}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" fill="none" transform="translate(9 7) scale(.91)">{path}</g>',200,200,'0 0 200 200')
 (cats/f'{key}.svg').write_text(s,encoding='utf-8')
# Export usable app/PWA icon files
for size,name in [(32,'favicon.png'),(180,'apple-touch-icon.png'),(192,'icon-192.png'),(512,'icon-512.png')]:
 canvas=svg(f'<rect x="0" y="0" width="140" height="140" rx="33" fill="{beige}"/><g>{mark.format(color=rust,leaf=sage)}</g>',140,140)
 raw=cairosvg.svg2png(bytestring=canvas.encode(),output_width=size,output_height=size)
 (root/'public'/name).write_bytes(raw)
im=Image.open(root/'public/favicon.png');im.save(root/'public/favicon.ico',format='ICO',sizes=[(16,16),(32,32)])
# PNG site OG and Pinterest placeholders with own approved generated still-life art.
hero=Image.open(imgs/'editorial-hero.jpg').convert('RGB')
font_candidates=['/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf','/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf']
font_file=next(x for x in font_candidates if Path(x).exists())
sans_file='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
def font(size,serif=True):return ImageFont.truetype(font_file if serif else sans_file,size)
def cover(size,photo_left=False):
 w,h=size;bg=Image.new('RGB',size,'#faf6ef');d=ImageDraw.Draw(bg)
 pic=ImageOps.fit(hero,(int(w*.51),h),method=Image.Resampling.LANCZOS,centering=(.54,.5))
 bg.paste(pic,(int(w*.49),0));d=ImageDraw.Draw(bg);pad=int(w*.065)
 d.rectangle((0,0,int(w*.49),h),fill='#faf6ef')
 d.text((pad,int(h*.12)),'STITCH ATLAS',fill=ink,font=font(int(w*.034)))
 d.line((pad,int(h*.23),int(w*.37),int(h*.23)),fill=rust,width=3)
 for j,line in enumerate(['There’s beauty in','every little loop.']):d.text((pad,int(h*.31)+int(h*.13)*j),line,fill=ink if j==0 else rust,font=font(int(w*.043)))
 d.text((pad,int(h*.69)),'CROCHET · CREATIVE LIVING · FREE LEARNING',fill=ink,font=font(int(w*.013),False))
 return bg
cover((1200,630)).save(root/'public/og-cover.png',optimize=True)
# Pinterest concept: not an untested "pattern" promotion
pin=Image.new('RGB',(1000,1500),'#faf6ef');p=ImageOps.fit(hero,(1000,995),method=Image.Resampling.LANCZOS,centering=(.54,.45));pin.paste(p,(0,0));d=ImageDraw.Draw(pin)
d.rectangle((0,995,1000,1500),fill='#faf6ef')
d.text((75,1037),'STITCH ATLAS  ·  THE MAKER JOURNAL',font=font(29,False),fill=rust)
d.text((75,1100),'Make room for',font=font(78),fill=ink);d.text((75,1206),'the handmade.',font=font(84),fill=rust)
d.text((75,1350),'FREE LEARNING NOTES  /  ORIGINAL PROJECTS COMING SOON',font=font(22,False),fill=ink)
pin.save(brand/'pinterest-concept.png',optimize=True)
# wide social cover (not claiming a launched website)
social=Image.new('RGB',(1640,624),'#faf6ef');crop=ImageOps.fit(hero,(720,624),method=Image.Resampling.LANCZOS);social.paste(crop,(920,0));d=ImageDraw.Draw(social)
d.text((95,95),'STITCH ATLAS',font=font(75),fill=ink)
d.line((95,210,810,210),fill=rust,width=5)
d.text((95,280),'Every little loop',font=font(75),fill=ink);d.text((95,365),'has a story.',font=font(80),fill=rust)
d.text((95,520),'A NEW HOME FOR FREE CROCHET LEARNING',font=font(25,False),fill=ink)
social.save(brand/'social-cover.png',optimize=True)
# Small screenshot-friendly transparent wordmark PNG
cairosvg.svg2png(url=str(brand/'wordmark.svg'),write_to=str(brand/'wordmark.png'),output_width=680,output_height=164)
cairosvg.svg2png(url=str(brand/'mark.svg'),write_to=str(brand/'avatar.png'),output_width=600,output_height=600)
print('Generated',len(list(brand.iterdir())),'brand assets,',len(list(cats.iterdir())),'category icons')
