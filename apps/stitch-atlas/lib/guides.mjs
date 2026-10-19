import {advancedGuides} from './advanced-guides.mjs';
/**
 * Original skill/reference journalism for the preview publication.
 * Intentionally NOT a collection of invented, physically tested patterns.
 * Guides contain no fictitious testers, authors, endorsements or ratings.
 * Sources are attributed for factual standards; copy remains original.
 */
export const learningGuides = [
  {
    slug:'how-to-count-crochet-stitches',
    title:'How to count crochet stitches without losing your place',
    shortTitle:'Count your crochet stitches',
    description:'A visual way to identify stitch tops, check row ends and catch off-by-one mistakes before they spread.',
    category:'Stitch confidence',categoryId:'stitches',stage:'Learning reference',visual:'/guides/count-stitches.svg',accent:'sage',
    lead:'Counting stitches feels mysterious until you know what you are actually counting. The trick is to look for the tops of completed stitches—not the spaces, gaps or yarn strands between them.',
    answer:'Count the V-shaped tops of the actual stitches in your current row. Mark the first and last stitch, follow the pattern’s turning-chain instructions, and recount at predictable checkpoints instead of waiting until the fabric starts to lean.',
    keywords:['count crochet stitches','how to count crochet stitches','crochet row end mistakes'],
    checklist:['Find the first complete stitch—not the turning chain by assumption.','Mark both row edges before working back across.','Check the expected count after increases and decreases.','Treat turning chains according to that pattern’s instructions.'],
    sections:[
      {id:'look-for-vs',title:'01. Find the little V at the top',paragraphs:[
        'Lay your work flat in good light, with the upper edge facing you. On an ordinary row of basic stitches, each completed stitch has two top loops that form a small V. Travel along the top edge and count one V per completed stitch.',
        'Do not count the hole under a stitch as a separate stitch. Do not confuse the two loops of a single V with two separate stitches. For a taller stitch, the vertical post can help you trace its top if the fabric is textured.'
      ],note:{heading:'A helpful habit',body:'Place removable stitch markers into the first and last actual stitches. It makes the edge easier to find when you turn your work.'}},
      {id:'turning-chain',title:'02. The turning-chain question',paragraphs:[
        'This is where many neat pieces go crooked. Some instructions say the turning chain counts as a stitch, especially in taller-stitch patterns; other instructions explicitly say it does not. There is no universal rule that replaces the pattern key.',
        'When the turning chain counts, it occupies a stitch position and may be worked into on the next row. When it does not count, look for the real first stitch beside it. If you always assume one rule, you can accidentally add a stitch each row or skip the last one.'
      ],bullets:['Read the pattern’s “turning chain counts as…” note before you begin.','If it counts, include it in the stated stitch total.','If it does not count, treat it as height rather than a separate worked stitch.']},
      {id:'count-rows',title:'03. Count rows as carefully as stitches',paragraphs:[
        'Single crochet rows appear as shorter, tighter horizontal ridges, while taller stitches show more elongated posts. To count rows, begin at a distinct foundation edge and follow the ridges or rows of posts upward. A row marker placed every five or ten rows can save a lot of recounting.',
        'Some textured patterns combine rows into a repeating motif. In those, counting one ridge may not equal one complete pattern repeat; use the row numbers in the actual instructions and write down each completed row.'
      ]},
      {id:'find-errors',title:'04. Troubleshoot a count that changed',paragraphs:[
        'If a rectangle widens, inspect whether you worked into a turning chain that was not meant to count. If it narrows, check whether the first or final stitch is being skipped. If the count changes suddenly, examine any increase or decrease that was supposed to happen on that row.',
        'A correct number on the last row does not always mean the earlier shaping is right. Compare the locations of any increases, not just the total. A quick recount every few rows is less work than unraveling a large section.'
      ],steps:['Lay the latest completed row flat.','Identify and mark the first and last stitches.','Count every stitch top, checking the pattern key for chain spaces and clusters.','Compare the number to the written row total.','If wrong, trace back to the last row where the total was correct.']},
      {id:'practice',title:'05. A five-minute confidence exercise',paragraphs:[
        'Make a short, simple row of US single crochet using light-colored yarn. Before turning, point to each V with the tip of your hook. Then place a stitch marker in the last completed stitch. Repeat on a second row and check the two edges.',
        'This is a counting exercise, not an independently tested finished-object pattern. For projects with complex stitches, always follow the specific pattern’s counting convention.'
      ],note:{heading:'Make it easier next time',body:'Use the free row counter for your place in the project, but keep a separate stitch count for each row whenever shaping is involved.'}},
    ],related:['us-uk-crochet-terms','how-to-measure-crochet-gauge','moss-stitch-crochet-explained'],sources:[{title:'Craft Yarn Council: Crochet abbreviations',url:'https://media.craftyarncouncil.com/?q=node%2F31'}]
  },
  {
    slug:'us-uk-crochet-terms',
    title:'US vs UK crochet terms: a friendly stitch conversion guide',
    shortTitle:'US / UK stitch glossary',
    description:'The same hook movement can have two names. Learn the essential US-to-UK stitch matches with a clear reference chart.',
    category:'Pattern literacy',categoryId:'beginners',stage:'Terminology reference',visual:'/guides/us-uk-terms.svg',accent:'rose',
    lead:'A UK double crochet and a US double crochet are not the same stitch. That small naming trap can change the entire texture and size of a project. Here is the reference worth keeping next to your hook.',
    answer:'Check whether a pattern uses US or UK terminology before starting. For the most common stitches: US single crochet (sc) equals UK double crochet (dc); US half double crochet (hdc) equals UK half treble (htr); and US double crochet (dc) equals UK treble (tr).',
    keywords:['US vs UK crochet terms','crochet abbreviation conversion','UK double crochet vs US'],
    checklist:['Look for the source’s explicit US/UK notation.','Translate stitch meanings, not the letters on their own.','Keep a conversion key beside the work.','Check special abbreviations in the original pattern key.'],
    sections:[
      {id:'why-names-differ',title:'01. Same movement, different name',paragraphs:[
        'Crochet instruction names developed under different conventions. The familiar UK “double crochet” is the same physical movement as a US “single crochet.” The common UK “treble” is the same movement as a US “double crochet.”',
        'This is not about changing the hook, the yarn or the number of times you make the movement. It is about reading the vocabulary correctly. That is why two written versions of a design can look different even when the designer intended the same stitch.'
      ]},
      {id:'chart',title:'02. Keep this conversion chart nearby',paragraphs:['The following matches follow the Craft Yarn Council’s published US/UK abbreviation reference. Check the individual pattern for unusual stitch names.'],table:{head:['US stitch (abbreviation)','UK equivalent (abbreviation)'],rows:[['Slip stitch (sl st)','Slip stitch (ss)'],['Single crochet (sc)','Double crochet (dc)'],['Half double crochet (hdc)','Half treble (htr)'],['Double crochet (dc)','Treble (tr)'],['Treble (tr)','Double treble (dtr)'],['Double treble (dtr)','Triple treble (trtr)']]}},
      {id:'identify-pattern',title:'03. How can you tell which system a pattern uses?',paragraphs:[
        'First, read its introduction, abbreviations and notes. A well-edited pattern states its terminology explicitly. If it does not, do not rely only on a country flag, a .com domain, or a photo. Designers sometimes publish internationally.',
        'The presence of “sc” usually signals US terminology, because standard UK terminology ordinarily calls that movement “dc.” But this is a clue, not permission to ignore the pattern’s own stitch definitions.'
      ],bullets:['Find the words “US terms” or “UK terms” near the start.','Match one described movement to the conversion chart.','Ask the designer rather than guessing if the source is ambiguous.']},
      {id:'worked-example',title:'04. An example of a costly mix-up',paragraphs:[
        'Imagine instructions that say “work 12 dc” and use UK terminology. The intention is 12 stitches of the shorter US single-crochet height. If you make 12 US double crochet stitches instead, your fabric will be taller and usually more open.',
        'For a counted project, the stitch total may still look correct even while the finished size or texture is wrong. That is why stitch count and stitch identity both matter.'
      ]},
      {id:'more-than-terms',title:'05. What about yarn-over and gauge?',paragraphs:[
        'You may also encounter “gauge” in US instructions and “tension” in UK instructions. Both refer to measured stitch and row density in a sample fabric. Other word choices, such as “yarn over hook,” may also vary.',
        'Symbols and abbreviations for unusual stitches are often designer-specific. Use the original key and any technique photos provided with the pattern; no generic translation table is complete for every variation.'
      ],note:{heading:'One more shortcut',body:'Use the stitch converter in the Maker Desk to check a single common term while reading. It cannot translate a whole complex pattern automatically.'}},
    ],related:['how-to-count-crochet-stitches','how-to-measure-crochet-gauge','moss-stitch-crochet-explained'],sources:[{title:'Craft Yarn Council: master crochet abbreviations and UK differences',url:'https://media.craftyarncouncil.com/?q=node%2F31'},{title:'Craft Yarn Council: crochet chart symbols',url:'https://craftyarncouncil.com/standards/crochet-chart-symbols'}]
  },
  {
    slug:'how-to-measure-crochet-gauge',
    title:'Crochet gauge explained: make a swatch that tells the truth',
    shortTitle:'Measure crochet gauge',
    description:'Read stitch and row gauge, measure the center of a swatch, and understand what your numbers mean for a project.',
    category:'Tools & tension',categoryId:'beginners',stage:'Measurement reference',visual:'/guides/gauge-swatch.svg',accent:'sand',
    lead:'Gauge is less about following a hook recommendation and more about discovering what your own hands make. A small swatch can prevent a bag that grows far wider than intended or a garment that does not fit.',
    answer:'Make a sample with your intended yarn, hook and stitch pattern. After preparing it as the finished fabric will be treated, count the stitches and rows across a measured center area, commonly 4 inches / about 10 cm, then compare those counts with the pattern’s stated gauge.',
    keywords:['crochet gauge swatch','how to measure crochet gauge','crochet stitches per 10 cm'],
    checklist:['Use the same yarn, hook and stitch pattern as the project.','Make the swatch larger than the area you will measure.','Measure away from rolled or uneven edge stitches.','Follow any blocking/washing instruction before final comparison.'],
    sections:[
      {id:'meaning',title:'01. Two numbers, one fabric',paragraphs:[
        'Stitch gauge is the number of stitches across a given width; row gauge is the number of rows over a given height. A pattern might state 18 stitches and 22 rows over 10 cm. Those figures describe the actual fabric the designer measured—not an instruction to use a particular hook size at any cost.',
        'Tension changes with fiber, hook shape, stitch style and your hands. Two makers working with the same yarn label can produce different dimensions. When a project has to fit or match a precise measurement, the swatch matters.'
      ]},
      {id:'swatch',title:'02. Make a swatch bigger than the ruler',paragraphs:[
        'Work a sample in the specified stitch and with the materials you plan to use. A sample somewhat larger than the measurement square lets you avoid edge distortion. Keep the fabric relaxed; stretching it to make the numbers match hides useful information.',
        'If a project uses joined rounds or an unusual texture, a flat plain-stitch square may not reproduce its fabric density. Follow the pattern’s gauge instructions for that construction.'
      ],steps:['Use the intended yarn and hook size.','Work the specified stitch pattern until you have an area larger than 10 × 10 cm (4 × 4 in).','If the finished piece will be washed or blocked, treat the swatch in the relevant way and allow it to dry.','Lay it flat without pulling the edges straight by force.','Count stitches and rows within the center measuring area.']},
      {id:'read-gauge',title:'03. Count across the middle, not the edge',paragraphs:[
        'Place a ruler across the middle of the sample. Count full stitches within 10 cm or 4 inches; then measure row count vertically over the same height. A ruler edge through half a stitch can cause disagreement, so use a consistent starting point and note fractional counts if the pattern demands precision.',
        'A practical sketch has the horizontal ruler for stitch gauge and the vertical ruler for row gauge. For stitches with strong texture or open holes, count actual stitch columns rather than the visible gaps.'
      ],note:{heading:'Example, not a pattern guarantee',body:'If you count 18 stitches across 10 cm, a simple proportional estimate for 30 cm is 18 × 3 = 54 stitches. Real stitch multiples, shaping and borders may require a different starting count.'}},
      {id:'not-matching',title:'04. What to try when your gauge differs',paragraphs:[
        'If you get more stitches than required within 10 cm, your stitches are smaller or denser than the target. A larger hook may help you reach the expected dimensions. If you get fewer stitches than required, your stitches are larger; consider trying a smaller hook.',
        'Change one thing, make another swatch and measure again. Remember that switching hook sizes may also change drape and feel. Sometimes the chosen yarn simply does not behave like the original.'
      ]},
      {id:'after',title:'05. Keep checking on the actual project',paragraphs:[
        'A gauge swatch captures one moment. Tension can change when working a long piece, when you switch from a narrow band to a large panel, or when a bag begins to carry weight. Recheck width periodically and pay attention to the fabric itself.',
        'Our Maker Desk offers a proportional gauge estimator and a separate yarn-weight estimator. Both are planning aids based on your real inputs; they do not certify fit or replace a tested project pattern.'
      ]},
    ],related:['how-to-count-crochet-stitches','how-to-choose-yarn-for-crochet-bags','us-uk-crochet-terms'],sources:[{title:'Craft Yarn Council: why gauge matters',url:'https://www.craftyarncouncil.com/node/3206'},{title:'Craft Yarn Council: gauge measurement standards',url:'https://media.craftyarncouncil.com/files/CYC_YS_s_and_g_rev2015_6.pdf'}]
  },
  {
    slug:'how-to-choose-yarn-for-crochet-bags',
    title:'Choosing yarn for crochet bags that need to hold their shape',
    shortTitle:'Choose yarn for crochet bags',
    description:'Compare cotton, blends, stitch density and straps before you spend hours on a handmade everyday bag.',
    category:'Bag-making essentials',categoryId:'bags',stage:'Materials guide',visual:'/guides/bag-yarn.svg',accent:'olive',
    lead:'A bag has a different job from a soft blanket. It may need to support a phone, a notebook or groceries while being carried by handles. The right yarn decision begins with what the finished object will actually hold.',
    answer:'Choose yarn after deciding the bag’s load, fabric structure and care needs. Firmly worked cotton or suitable blends are often useful starting points, but swatch the actual stitch fabric and test a strap sample with weight before committing to a finished bag.',
    keywords:['best yarn for crochet bags','crochet bag yarn type','crochet bag strap stretching'],
    checklist:['Decide what the bag will carry and how often.','Compare yarn behavior after washing and gentle loading.','Swatch with the actual stitch and intended hook.','Plan strap construction and consider a fabric lining.'],
    sections:[
      {id:'begin-with-purpose',title:'01. Design for the things inside',paragraphs:[
        'A decorative little pouch, a farmer’s-market tote and a shoulder bag for books have very different demands. A loose, open mesh can be attractive for produce but may snag small objects. A denser fabric or lining makes more sense for a phone, keys or pens.',
        'Think about two questions before choosing fiber: how much weight will the bag carry, and how often will the fabric be pulled by the handles? The answers should guide stitch choice, strap design, lining and yarn together.'
      ]},
      {id:'fibers',title:'02. Cotton, blends and synthetic yarn',paragraphs:[
        'Cotton yarn can produce crisp stitch definition and a less fluffy surface that suits many bags, but cotton can also grow or sag under sustained weight depending on construction. Fiber content alone is not a guarantee that a strap will never stretch.',
        'Blends and some synthetic yarns behave differently under friction, moisture and washing. Read the actual yarn label for care requirements and compare swatches rather than assuming one fiber is universally “best.” Consider how heavy the yarn feels in a larger finished bag, especially if you plan to line it.'
      ],bullets:['A tightly worked fabric can be more structured than a loose version using the same yarn.','A wider or reinforced handle spreads force differently from a narrow single cord.','A lining can contain small items, but it does not automatically reinforce a weakly attached handle.']},
      {id:'swatch-with-purpose',title:'03. Make two useful samples',paragraphs:[
        'First, crochet a small patch in the stitch planned for the bag body. Hold it up to the light and consider whether pens or keys might slip through. Then check its drape, feel and appearance after the kind of washing the finished bag may receive.',
        'Second, make a short sample of the intended strap stitch. Gently load it with a known weight in a controlled way and compare its length before and after. That cannot fully reproduce months of use, but it is more informative than relying only on a photograph.'
      ]},
      {id:'strap-questions',title:'04. Where bags often get longer',paragraphs:[
        'Handles concentrate force at their attachment points. The body may remain fairly stable while thin straps become longer. Longer straps also change how a bag carries weight across a shoulder or hand.',
        'Consider a shorter initial handle, a firm stitch, a separately reinforced strap or a sewn webbing component if suitable for the design. Attachment quality matters as much as the yarn itself. Inspect the join after a controlled weight test.'
      ],note:{heading:'Worth remembering',body:'“Never stretches” is not a property a yarn label can guarantee. Test construction, stitches, weight and attachment points together.'}},
      {id:'lining-and-care',title:'05. A lining is a design decision',paragraphs:[
        'An inner layer can help stop smaller belongings from poking through crochet fabric. It may also improve usability and make the inside easier to clean. Whether it adds meaningful structural support depends on how it is cut and attached.',
        'Choose lining fabric compatible with the bag’s washing needs. Before cutting it, measure the actual completed crochet body, not only the nominal dimensions from the design sketch. See our lining guide for a separate fitting checklist.'
      ]},
    ],related:['how-to-line-a-crochet-bag','how-to-measure-crochet-gauge','how-to-count-crochet-stitches'],sources:[{title:'Craft Yarn Council: yarn weight and gauge standards',url:'https://media.craftyarncouncil.com/read_instructions.html'},{title:'Wilma Westenberg: fabric lining in crochet bags',url:'https://wilmade.com/fabric-lining-crochet/'}]
  },
  {
    slug:'how-to-line-a-crochet-bag',
    title:'How to plan and fit a fabric lining inside a crochet bag',
    shortTitle:'Plan a crochet bag lining',
    description:'An original measurement-first lining checklist: fabric choice, seam allowance, trial fit and neat hand attachment.',
    category:'Bag-making essentials',categoryId:'bags',stage:'Sewing reference',visual:'/guides/bag-lining.svg',accent:'rose',
    lead:'A lining should fit the bag you have, not an imaginary rectangle in a pattern sketch. Begin with the finished crocheted shape, a tape measure and a paper mock-up. A calm trial fit is worth more than a perfectly cut piece of fabric that turns out too small.',
    answer:'Measure the finished bag interior, draft a paper or scrap-fabric lining with adequate seam and top-hem allowances, test its fit, then sew the fabric lining and attach its folded top edge inside the crochet opening using careful, even stitches.',
    keywords:['how to line a crochet bag','crochet bag lining guide','hand sew lining crochet bag'],
    checklist:['Finish and measure the actual bag first.','Choose fabric that matches the project’s structure and care needs.','Add the seam allowances required by your chosen construction.','Test-fit before sewing the lining permanently.'],
    sections:[
      {id:'why',title:'01. Why add fabric inside crochet?',paragraphs:[
        'Some beautiful crochet fabrics have large gaps between stitches. A lining can keep little objects from slipping out and can make the interior look more finished. It also gives you an opportunity to add a pocket, although pockets introduce their own placement and strength requirements.',
        'The purpose of a lining is not the same as structural reinforcement. A lightweight loose lining may still move under a heavy load, so do not assume it makes fragile straps or handles safe for heavy objects.'
      ]},
      {id:'measure',title:'02. Measure the bag you actually made',paragraphs:[
        'Lay the bag flat without stretching it. Measure the interior width across the opening, the interior height, and whether the bottom is flat, boxed or rounded. For a tote with depth, record the depth separately instead of treating it as a flat pouch.',
        'Crochet fabric often stretches when worn. For lining dimensions, use its relaxed finished size and compare with a light load if appropriate. Sketch the outline on paper and note where side seams and handle joins sit.'
      ]},
      {id:'draft',title:'03. Draft and test a fabric insert',paragraphs:[
        'For a simple flat pouch, two panels shaped to the interior can be easier to handle than a complicated box construction. Leave extra fabric for the seams and for folding the top hem. The exact allowances depend on the fabric and method, so do not cut to the bag’s inside dimensions without adding them.',
        'Pin or clip the paper/fabric mock-up and place it inside the bag before stitching. Adjust the depth and width until it sits naturally without pulling the crochet sides inward or bunching into large folds.'
      ],steps:['Trace or measure the relaxed interior shape.','Decide where the side and bottom seams will run.','Add your chosen seam allowances and top-fold allowance.','Cut an inexpensive paper or scrap-fabric mock-up first.','Pin the mock-up inside the bag and adjust until it fits without tension.']},
      {id:'sew',title:'04. Sew the lining before attachment',paragraphs:[
        'Once the mock-up is right, use it to cut the lining fabric with the same seam plan. Sew or hand-stitch the panel seams, turn and inspect the corners, then fold and press the top edge according to the fabric’s care instructions. Press the fabric away from delicate or heat-sensitive crochet yarn.',
        'A pocket can be attached before the lining is installed, provided its stitches and placement are suitable for the expected contents.'
      ]},
      {id:'attach',title:'05. Attach the lining invisibly',paragraphs:[
        'Place the lining inside the crochet bag with its finished fabric side facing into the interior. Align the side seams and keep its top edge slightly below the crochet opening, then clip it evenly around. Attach with small hand stitches through the folded fabric edge and just enough crochet to hold it in place.',
        'Check the exterior as you sew: a large pull can distort the crochet edge and show thread on the outside. Keep the stitch spacing regular, test the bag opening, and make a few secure finishing stitches on the inside.'
      ],note:{heading:'Scope of this guide',body:'This is a planning and sewing-reference checklist, not a tested one-size-fits-all bag-lining pattern. A shaped or zippered bag needs construction-specific measurements.'}},
      {id:'inspect',title:'06. Check the finished fit',paragraphs:[
        'Put a few light objects inside and look for pulling at the top edge, excess fabric at the bottom, or a pocket that pulls the lining sideways. Adjust any stressed attachment points before regular use.',
        'If the bag is intended for substantial weight, test strap and lining construction separately. A correct visual fit does not prove load capacity.'
      ]},
    ],related:['how-to-choose-yarn-for-crochet-bags','how-to-measure-crochet-gauge','how-to-count-crochet-stitches'],sources:[{title:'Wilmade: hand-sewing a crochet bag lining',url:'https://wilmade.com/fabric-lining-crochet/'},{title:'Marching North: how to line a handmade bag by hand',url:'https://www.marchingnorth.com/how-to-line-a-macrame-or-crochet-bag/'}]
  },
  {
    slug:'moss-stitch-crochet-explained',
    title:'Moss stitch crochet explained: the rhythm behind the texture',
    shortTitle:'Understand moss stitch',
    description:'Recognize the quiet texture of crochet moss stitch, its alternating single crochet and chain spaces, and common counting mistakes.',
    category:'Stitch confidence',categoryId:'stitches',stage:'Technique explanation',visual:'/guides/moss-stitch.svg',accent:'sage',
    lead:'Moss stitch can look like woven fabric, yet its rhythm is pleasingly modest. Once you recognize the difference between a worked single crochet and a chain space, you start to see the fabric as a repeating grid rather than a wall of loops.',
    answer:'In common US-terminology moss stitch (also called linen stitch), single crochet stitches alternate with chain-one spaces. On following rows, the single crochet is usually worked into a chain space rather than directly into every stitch top; the exact edge setup depends on the pattern.',
    keywords:['crochet moss stitch explained','moss stitch crochet for beginners','crochet linen stitch chain spaces'],
    checklist:['Check whether the source uses US or UK terms.','Identify the single crochet posts and the chain-one spaces.','Follow the pattern’s turning-chain and first/last-edge instructions.','Count repeats, not just visible holes.'],
    sections:[
      {id:'what-it-is',title:'01. What is crochet moss stitch?',paragraphs:[
        'Moss stitch is commonly made with a single-crochet-and-chain rhythm that produces a textured, interlocking surface. Designers may also call it linen stitch or granite stitch, though naming conventions vary and some patterns use distinct variations.',
        'The resulting fabric can feel more woven than many tall-stitch motifs. That appearance comes from the way new stitches occupy earlier chain spaces, making little offset blocks of color and texture.'
      ]},
      {id:'see-grid',title:'02. Read the fabric before copying the row',paragraphs:[
        'Find the relatively solid single crochet posts. The small horizontal chain-one spans between them form spaces; these are usually the locations for the next row’s single crochet. On an ordinary flat sample, the new posts are offset relative to those below.',
        'Think of two alternating parts: a worked stitch and a space. The space matters, but it does not mean that every open gap should be counted as an additional single crochet.'
      ]},
      {id:'practice',title:'03. Try the rhythm on a small learning swatch',paragraphs:[
        'In a simple learning exercise using US terms, alternate a single crochet with a chain-one space across a foundation in a way that matches the intended stitch repeat. On a following row, work the single crochet into an established chain-one space, then make another chain-one span.',
        'The first and last stitches, chain length and turning setup differ between published moss-stitch patterns. Use a complete pattern’s foundation and edge instructions for accurate stitch counts; this reference deliberately does not invent a validated finished-project recipe.'
      ],note:{heading:'Terminology check',body:'US single crochet (sc) is UK double crochet (dc). Confirm which language convention your chosen instructions use before starting the swatch.'}},
      {id:'mistakes',title:'04. Three ways the edges go wrong',paragraphs:[
        'One common mistake is placing a stitch into a stitch top when the repeat expects the chain-one space beside it. Another is skipping the very last edge stitch or treating the turning chain as an extra repeat. A third is working extra chains each time you turn.',
        'If the fabric begins to taper or widen, stop and mark the first and last expected stitch locations. Compare the number of repeats in the previous two rows before continuing.'
      ],bullets:['Look for chain spaces before inserting the hook.','Mark the edge stitch identified by the original pattern.','Count stitch-plus-chain repeats at the end of each row.']},
      {id:'uses',title:'05. Where moss stitch can be useful',paragraphs:[
        'Its understated texture works well as a swatch exercise and is sometimes used for blankets, scarves, home accessories and fabric bags. The suitability depends on yarn, gauge, density, drape and the actual dimensions of the design.',
        'For bags, test a real sample with light load rather than assuming a named stitch automatically provides enough structure. If fit matters, compare measured gauge after the treatment the finished item will receive.'
      ]},
    ],related:['how-to-count-crochet-stitches','us-uk-crochet-terms','how-to-measure-crochet-gauge'],sources:[{title:'Craft Yarn Council: common crochet stitch abbreviations',url:'https://media.craftyarncouncil.com/?q=node%2F31'}]
  }
, ...advancedGuides];

export const guideCategories = [
  {id:'all',label:'All guides'},
  {id:'stitches',label:'Stitch confidence'},
  {id:'beginners',label:'Beginner foundations'},
  {id:'bags',label:'Bags & structure'},
];

export const guideBySlug = slug=>learningGuides.find(guide=>guide.slug===slug)??null;
export const getRelatedGuides = guide => guide.related.map(guideBySlug).filter(Boolean);
export const guideWordCount = guide => [guide.title,guide.description,guide.lead,guide.answer,...guide.sections.flatMap(section=>[section.title,...(section.paragraphs||[]),...(section.bullets||[]),...(section.steps||[])])].join(' ').trim().split(/\s+/).length;
