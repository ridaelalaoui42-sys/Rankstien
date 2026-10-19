/** Stitch Atlas Academy: original, educational quiz content. No certification,
 * completed physical crochet project, test claim, login or server database.
 * No hidden/remote rewards; records live only on this browser.
 */
export const ACADEMY_STORAGE_KEY='stitch-atlas.academy.progress.v1';
export const ACADEMY_VERSION=1;
export const PASS_SCORE=2;
export const ACADEMY_QUESTIONS_PER_LESSON=3;

export const academyPaths=[
 {id:'first-stitches',eyebrow:'PATH 01 · THE FOUNDATIONS',title:'The First Stitches',subtitle:'Your hands, your hook, your first confident loops.',description:'Understand pattern language, yarn labels, stitch tops and adjustable starting rings—one approachable skill at a time.',cover:'/academy/first-stitches.svg',tone:'peach',minutes:35,lessons:[
  'us-uk-crochet-terms','crochet-yarn-weights-and-hook-sizes','how-to-count-crochet-stitches','how-to-make-magic-ring-crochet']},
 {id:'read-the-fabric',eyebrow:'PATH 02 · THE STITCH DETECTIVE',title:'Read the Fabric',subtitle:'Turn tiny mysteries into confident decisions.',description:'Learn to recognize textured stitches, identify fabric faces, understand gauge and check shaping arithmetic.',cover:'/academy/read-the-fabric.svg',tone:'sage',minutes:40,lessons:[
  'moss-stitch-crochet-explained','crochet-right-side-vs-wrong-side','how-to-measure-crochet-gauge','crochet-increases-decreases-stitch-math']},
 {id:'bag-maker-studio',eyebrow:'PATH 03 · PROJECT THINKING',title:'The Bag Maker Studio',subtitle:'Material decisions become beautiful structures.',description:'Choose practical yarn, understand strap stretch, plan a fabric lining and finish loose ends neatly. No untested bag patterns.',cover:'/academy/bag-maker-studio.svg',tone:'olive',minutes:45,lessons:[
  'how-to-choose-yarn-for-crochet-bags','how-to-avoid-stretchy-crochet-bag-straps','how-to-line-a-crochet-bag','how-to-weave-in-crochet-ends']},
];

const q=(prompt,options,answer,explanation)=>({prompt,options,answer,explanation});
export const academyQuizzes={
'us-uk-crochet-terms':[
 q('In UK terminology, “dc” commonly means which US stitch?',['US single crochet','US double crochet','US treble crochet'],0,'UK double crochet is the same movement as US single crochet. Always check the pattern’s declared terminology.'),
 q('You see “12 dc” in a pattern labelled UK terms. What should you do?',['Make 12 US double crochets','Work the UK dc movement (US sc)','Ignore the abbreviation key'],1,'A correctly read stitch type matters as much as the count; UK dc equals US sc.'),
 q('Which clue is the most reliable way to identify stitch terminology?',['The designer’s country','The pattern’s explicit US/UK key','The yarn colour'],1,'The source’s own stitch key is authoritative; country or platform is not a safe shortcut.')],
'crochet-yarn-weights-and-hook-sizes':[
 q('What does a yarn weight category mostly describe?',['Thickness family','How many grams the ball weighs','The finished object weight'],0,'Category describes a general thickness family, not the package mass.'),
 q('Why prefer the millimeter size on a hook?',['It guarantees gauge','Letters and numbers can vary by brand','A larger mm hook always uses less yarn'],1,'The measured millimeter size is a more dependable cross-brand comparison.'),
 q('The label suggests a 5 mm hook, but your fitted pattern gauge is wrong. What next?',['Use 5 mm without checking','Change a variable and re-swatch','Double every stitch'],1,'Generic label guidance is only a starting point; project-specific gauge is what matters.')],
'how-to-count-crochet-stitches':[
 q('What should you usually identify when counting a basic crochet row?',['The spaces beneath stitches','Each complete V-shaped stitch top','Both loops of each V as separate stitches'],1,'A complete V is one stitch top, not two. Count whole tops along the working edge instead of the two strands within each V.'),
 q('Does a turning chain always count as a stitch?',['Yes, every time','No, never','Only when that pattern says it does'],2,'Different stitch and pattern setups treat turning chains differently.'),
 q('Your straight fabric keeps narrowing. What is a useful first check?',['Are edge stitches being skipped?','Is the yarn colour pale?','Are your scissors sharp?'],0,'Missing the first or last stitch is a common cause of unintended narrowing.')],
'how-to-make-magic-ring-crochet':[
 q('What makes a magic ring different from a fixed chain ring?',['You can adjust the center opening','It automatically makes every pattern safe','It needs no yarn tail'],0,'An adjustable loop can tighten the starting center once the first round is made; the tail still needs to be secured.'),
 q('Before tightening your first round, what matters?',['Count the actual stitches worked','Cut the tail short','Make every stitch in US double crochet'],0,'The original pattern gives the correct first-round count and stitch type.'),
 q('What should happen to the loose tail after the center closes?',['Cut it flush immediately','Secure it according to the project and yarn','Leave it hanging for decoration'],1,'An unsecured adjustable center can loosen; leave enough tail to weave in securely.')],
'moss-stitch-crochet-explained':[
 q('Common moss/linen stitch uses what basic rhythm in US terms?',['Single crochet with chain-one spaces','Only treble crochet','Knitted purl stitches'],0,'The common version alternates single crochet and chain-one spaces, though edge rules differ.'),
 q('Where do the next row’s single crochet posts often go?',['Into established chain-one spaces','Always into the turning chain','Only into the previous row’s posts'],0,'The offset post-over-space rhythm creates the familiar woven texture.'),
 q('Your moss stitch sides widen each row. What should you inspect first?',['The edge/turning instructions','The colour names','The hook brand logo'],0,'Extra turning chains or wrong edge placements can change repeat counts.')],
'crochet-right-side-vs-wrong-side':[
 q('What does RS usually mean in a crochet pattern?',['Row spacing','Right side','Repeat sequence'],1,'RS generally marks the intended outward-facing fabric face. Which texture looks best depends on the original pattern and stitch.'),
 q('Is the face with a ridge always the wrong side?',['Yes','No; check the stitch and pattern','Only if the yarn is wool'],1,'Many textures are reversible, while other stitches have intentional ridges.'),
 q('What helps keep similar panels oriented during assembly?',['Mark the intended face','Assume all panels match automatically','Pull harder on the seams'],0,'A removable marker prevents accidental reversing during sewing or lining.')],
'how-to-measure-crochet-gauge':[
 q('Why make a gauge swatch before a fitted project?',['To predict measurements from your real fabric','To prove the designer’s rating','To skip reading instructions'],0,'Real stitches and rows per measured area help predict the size of your finished work.'),
 q('Your sample has more stitches per 10 cm than required. One possible adjustment?',['Try a larger hook then re-swatch','Always choose smaller yarn','Ignore the gauge'],0,'A larger hook may loosen the fabric and reduce the number of stitches per measured area; make a fresh sample and check.'),
 q('Which part of the crochet swatch should you measure?',['A tiny stretched edge','A representative, relaxed interior area','Only the number printed on the yarn label'],1,'Measure an even interior section without distorting the swatch; stretched edges can give an inaccurate stitch count.')],
'crochet-increases-decreases-stitch-math':[
 q('Start with 24 stitches, add three ordinary increases and two ordinary decreases. End count?',['22','25','29'],1,'The row begins with 24 stitches; three normal increases add three, and two decreases remove two, leaving 25 stitch tops.'),
 q('Two new stitches in one old location usually change the count by…',['+1','−1','0'],0,'One previous stitch position creates two new tops, adding one stitch to the next row compared with one-for-one work.'),
 q('Does the correct stitch total prove the shaping positions are correct?',['Yes, always','No, changes could be placed incorrectly','Only for cotton'],1,'Where you increase or decrease matters as much as the final number.')],
'how-to-choose-yarn-for-crochet-bags':[
 q('What is often valuable in a bag fabric sample?',['Resistance to stretching and suitable density','The brightest colour only','Unverified star ratings'],0,'A bag fabric must suit the planned use; real samples help assess structure.'),
 q('What may matter more than the gram weight of a ball for shopping?',['Ball length in meters/yards','Packaging colour','The barcode prefix'],0,'Different yarn thicknesses have different lengths per gram. Check meters or yards before assuming two 100 g balls have equal yardage.'),
 q('Should a label alone guarantee a bag’s strength?',['Yes','No, test yarn and construction','Only for green yarn'],1,'Yarn, stitches, seams and strap attachments all affect how a bag performs; a ball label cannot certify the construction.')],
'how-to-avoid-stretchy-crochet-bag-straps':[
 q('Why can even dense-looking crochet straps lengthen?',['Loops can shift under tension','Every crochet hook is identical','Yarn colour fades'],0,'Loop geometry and fiber behavior can cause a handle to lengthen under load, even when the original fabric looks dense.'),
 q('Where else should a strap be supported?',['Attachment points on the bag body','Only the very middle of the strap','Nowhere'],0,'The anchors can be the weakest area if they pull on a few loose stitches.'),
 q('Can a finished-looking bag be described as load-rated without tests?',['Yes, if photographed','No, real testing is required','Only if the strap is wide'],1,'Aesthetic photos do not establish load-bearing performance; use a practical sample and reinforce the connection points.')],
'how-to-line-a-crochet-bag':[
 q('Before cutting a lining, what should you do?',['Measure the actual finished bag','Use unrelated measurements from a photo','Assume every bag is rectangular'],0,'The actual bag dimensions determine the lining shape and seam allowance.'),
 q('Why might you include a lining in an openwork bag?',['To help stop small objects escaping','To replace every structural seam','To make the yarn waterproof'],0,'Linings may contain small items but are not automatic reinforcement or waterproofing.'),
 q('Should the lining be sewn while the bag is stretched to its maximum?',['Always','No; consider normal finished shape and use','Only for wool'],1,'A lining fit should respect the bag’s relaxed shape and expected movement.')],
'how-to-weave-in-crochet-ends':[
 q('Why leave enough yarn tail when fastening off?',['It makes a secure weaving route possible','It increases stitch height','It converts UK to US terms'],0,'Very short tails are difficult to secure within the fabric and can work loose after repeated stretching and use.'),
 q('What can help resist a straight pull-out?',['Changing weave direction through existing stitches','Cutting ends at the knot','Only sewing one inch straight'],0,'Changing direction and checking the finish can help the tail stay concealed.'),
 q('Does one finishing method guarantee no yarn will ever loosen?',['Yes','No; fiber and use affect durability','Only on premium yarn'],1,'Test the actual material and expected use rather than relying on guarantees.')],
};

export function getAcademyPath(id){return academyPaths.find(p=>p.id===id)||null}
export function getAcademyLesson(pathId,lessonId){const path=getAcademyPath(pathId);return path?.lessons.includes(lessonId)?{path,lessonId,questions:academyQuizzes[lessonId]}:null}
export function gradeQuiz(lessonId,answers){
 const questions=academyQuizzes[lessonId];
 if(!questions || !Array.isArray(answers)||answers.length!==questions.length)throw Error('Incomplete quiz');
 if(!answers.every((v,i)=>Number.isInteger(v) && v>=0 && v<questions[i].options.length))throw Error('Invalid answer choice');
 const score=answers.reduce((n,a,i)=>n+(a===questions[i].answer?1:0),0);
 return {score,total:questions.length,passed:score>=PASS_SCORE,perfect:score===questions.length,feedback:questions.map((question,i)=>({correct:answers[i]===question.answer,answer:question.answer,explanation:question.explanation}))};
}

export const ACADEMY_BADGES=[
 {id:'first-loop',title:'First Loop',desc:'Complete your first academy lesson.',symbol:'✳'},
 {id:'perfect-swatch',title:'Perfect Swatch',desc:'Get all three answers right in any quiz.',symbol:'❋'},
 {id:'foundation-finder',title:'Foundation Finder',desc:'Complete The First Stitches path.',symbol:'◈'},
 {id:'stitch-detective',title:'Stitch Detective',desc:'Complete Read the Fabric.',symbol:'⌕'},
 {id:'bag-thinker',title:'Thoughtful Maker',desc:'Complete The Bag Maker Studio.',symbol:'✥'},
 {id:'atlas-explorer',title:'Atlas Explorer',desc:'Complete all 12 learning quizzes.',symbol:'✺'}
];
export const totalAcademyLessons=academyPaths.reduce((sum,p)=>sum+p.lessons.length,0);

export function cleanAcademyProgress(value){
 const result={version:ACADEMY_VERSION,completed:{}};
 if(!value || typeof value!=='object' || Array.isArray(value))return result;
 const raw=value.completed;
 if(!raw || typeof raw!=='object' || Array.isArray(raw))return result;
 for(const id of Object.keys(academyQuizzes)){
  const entry=raw[id];
  if(!entry||typeof entry!=='object'||Array.isArray(entry))continue;
  const score=entry.score;
  if(!Number.isInteger(score)||score<PASS_SCORE||score>ACADEMY_QUESTIONS_PER_LESSON)continue;
  const completedAt=typeof entry.completedAt==='string' && /^\d{4}-\d\d-\d\dT/.test(entry.completedAt)?entry.completedAt:null;
  result.completed[id]={score,completedAt};
 }
 return result;
}
export function applyQuizResult(progress,lessonId,grade,completedAt=new Date().toISOString()){
 const base=cleanAcademyProgress(progress);
 if(!academyQuizzes[lessonId]||!grade?.passed)return base;
 const score=Math.max(Number(base.completed[lessonId]?.score)||0,grade.score);
 base.completed[lessonId]={score,completedAt:base.completed[lessonId]?.completedAt||completedAt};
 return base;
}
export function getAcademyStats(progress){
 const safe=cleanAcademyProgress(progress),ids=Object.keys(safe.completed),complete=new Set(ids);
 const paths=academyPaths.map(path=>({...path,completedCount:path.lessons.filter(id=>complete.has(id)).length,complete:path.lessons.every(id=>complete.has(id))}));
 const xp=ids.reduce((sum,id)=>sum+50+(safe.completed[id].score===3?25:0),0);
 const badges=[];
 if(ids.length)badges.push('first-loop');
 if(ids.some(id=>safe.completed[id].score===3))badges.push('perfect-swatch');
 if(paths[0].complete)badges.push('foundation-finder');
 if(paths[1].complete)badges.push('stitch-detective');
 if(paths[2].complete)badges.push('bag-thinker');
 if(ids.length===totalAcademyLessons)badges.push('atlas-explorer');
 return {completedCount:ids.length,totalCount:totalAcademyLessons,percent:Math.round(ids.length/totalAcademyLessons*100),xp,badges,paths};
}
