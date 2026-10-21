import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync,readFileSync,statSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {learningGuides,guideBySlug,guideWordCount} from '../lib/guides.mjs';
import {ACADEMY_STORAGE_KEY,ACADEMY_QUESTIONS_PER_LESSON,PASS_SCORE,ACADEMY_BADGES,academyPaths,academyQuizzes,gradeQuiz,getAcademyLesson,getAcademyPath,applyQuizResult,cleanAcademyProgress,getAcademyStats,getAcademyNextLesson,totalAcademyLessons} from '../lib/academy.mjs';
const root=resolve(import.meta.dirname,'..');
const text=rel=>readFileSync(join(root,rel),'utf8');
const read=rel=>readFileSync(join(root,rel));

test('3 paths and 12 unique illustrated lessons map to real guides without duplicated SEO intent',()=>{
 assert.equal(academyPaths.length,3);assert.equal(totalAcademyLessons,12);assert.equal(learningGuides.length,12);
 const seen=new Set();
 for(const path of academyPaths){
   assert.match(path.id,/^[a-z0-9-]+$/);assert.equal(path.lessons.length,4);
   assert(existsSync(join(root,'public'+path.cover)));assert.strictEqual(getAcademyPath(path.id),path);
   for(const id of path.lessons){assert(!seen.has(id),'Duplicate lesson '+id);seen.add(id);
     const guide=guideBySlug(id);assert(guide);assert(guideWordCount(guide)>=450,'Too short: '+id);
     assert.equal(getAcademyLesson(path.id,id)?.lessonId,id);
   }
 }
 assert.equal(seen.size,12);
 assert.equal(getAcademyLesson('bogus','us-uk-crochet-terms'),null);
 assert.equal(getAcademyLesson('first-stitches','how-to-line-a-crochet-bag'),null);
});

test('36 unique questions have defensible choices and thoughtful explanations',()=>{
 assert.equal(Object.keys(academyQuizzes).length,12);
 let total=0;
 for(const [id,questions] of Object.entries(academyQuizzes)){
   assert(guideBySlug(id));assert.equal(questions.length,ACADEMY_QUESTIONS_PER_LESSON);total+=questions.length;
   const prompts=new Set();
   for(const q of questions){
     assert(q.prompt.length>=27,`${id} question too short`);assert(!prompts.has(q.prompt));prompts.add(q.prompt);
     assert.equal(q.options.length,3);assert.equal(q.options.length,new Set(q.options).size);
     assert(Number.isInteger(q.answer)&&q.answer>=0&&q.answer<q.options.length);
     assert(q.explanation.length>=65,`${id} answer explanation too short`);
     assert(!/buy now|product download|price:\s*\$|paid certificate/i.test(q.explanation));
   }
 }
 assert.equal(total,36);
});

test('quiz grading has clear threshold, feedback and rejects malformed answers',()=>{
 const perfect=gradeQuiz('us-uk-crochet-terms',[0,1,1]);assert.deepEqual([perfect.score,perfect.total,perfect.perfect,perfect.passed],[3,3,true,true]);
 const pass=gradeQuiz('us-uk-crochet-terms',[0,1,0]);assert.equal(pass.score,2);assert(pass.passed&&!pass.perfect);
 const fail=gradeQuiz('us-uk-crochet-terms',[1,0,0]);assert(!fail.passed);assert.equal(fail.score,0);
 for(const payload of [[0,1],[0,-1,1],[0,100,1],[0,'1',1],[],null])assert.throws(()=>gradeQuiz('us-uk-crochet-terms',payload));
 assert.throws(()=>gradeQuiz('does-not-exist',[0,0,0]));assert.equal(PASS_SCORE,2);
});

test('progress is local, replay-safe, only mastered lessons earn badges and points',()=>{
 const first='us-uk-crochet-terms',second='crochet-yarn-weights-and-hook-sizes';
 assert.match(ACADEMY_STORAGE_KEY,/academy.*progress/);
 const initial=getAcademyStats(null);assert.equal(initial.percent,0);assert.equal(initial.xp,0);assert.deepEqual(initial.badges,[]);
 const fail=gradeQuiz(first,[1,0,0]);const unchanged=applyQuizResult(null,first,fail);assert.deepEqual(unchanged.completed,{});
 const pass=gradeQuiz(first,[0,1,0]);const after=applyQuizResult(null,first,pass,'2026-10-19T00:00:00.000Z');
 assert.deepEqual(Object.keys(after.completed),[first]);assert.equal(getAcademyStats(after).xp,50);
 assert.deepEqual(getAcademyStats(after).badges,['first-loop']);
 const better=applyQuizResult(after,first,gradeQuiz(first,[0,1,1]));
 assert.equal(better.completed[first].score,3);assert.equal(getAcademyStats(better).xp,75);
 assert.equal(getAcademyStats(better).completedCount,1,'Cannot farm XP by repeat quizzes');
 assert.deepEqual(getAcademyStats(better).badges.slice(0,2),['first-loop','perfect-swatch']);
 const after2=applyQuizResult(better,second,gradeQuiz(second,[0,1,1]));assert.equal(getAcademyStats(after2).completedCount,2);
 // Same quiz again at a worse grade must never erase previously earned perfect score.
 const replay=applyQuizResult(after2,first,pass);assert.equal(replay.completed[first].score,3);
 const corrupt=cleanAcademyProgress({completed:{'fake-path':{score:3},[first]:{score:999},[second]:{score:2},'how-to-make-magic-ring-crochet':{score:'3'}}});
 assert.deepEqual(Object.keys(corrupt.completed),[second]);
 assert.deepEqual(cleanAcademyProgress({completed:[]} ).completed,{});
 let all=null;
 for(const path of academyPaths)for(const id of path.lessons){const q=academyQuizzes[id];all=applyQuizResult(all,id,gradeQuiz(id,q.map(x=>x.answer)));}
 const stats=getAcademyStats(all);assert.equal(stats.completedCount,12);assert.equal(stats.percent,100);assert.equal(stats.xp,900);
 assert.equal(stats.badges.length,ACADEMY_BADGES.length);assert(stats.paths.every(p=>p.complete));
});

test('recommended next lesson resumes in order, ignores corrupt scores and handles full completion',()=>{
 const start=getAcademyNextLesson(null);
 assert.equal(start.pathId,'first-stitches');
 assert.equal(start.lessonId,'us-uk-crochet-terms');
 assert.equal(start.href,'/academy/first-stitches/us-uk-crochet-terms');
 assert.equal(start.completedCount,0);
 let progress=cleanAcademyProgress(null);
 const passed=id=>gradeQuiz(id,academyQuizzes[id].map(q=>q.answer));
 progress=applyQuizResult(progress,'us-uk-crochet-terms',passed('us-uk-crochet-terms'));
 const next=getAcademyNextLesson(progress);
 assert.equal(next.lessonId,'crochet-yarn-weights-and-hook-sizes');
 assert.equal(next.lessonNumber,2);
 assert.equal(next.completedCount,1);
 assert.equal(getAcademyNextLesson({completed:{'unknown':{score:3}}}).lessonId,start.lessonId);
 for(const id of academyPaths[0].lessons.slice(1))progress=applyQuizResult(progress,id,passed(id));
 assert.equal(getAcademyNextLesson(progress).pathId,'read-the-fabric');
 for(const path of academyPaths.slice(1))for(const id of path.lessons)progress=applyQuizResult(progress,id,passed(id));
 assert.equal(getAcademyNextLesson(progress),null,'Completing everything must never suggest a finished lesson');
 assert.equal(getAcademyNextLesson({completed:{}}).lessonId,start.lessonId);
 const dashboard=text('components/AcademyDashboard.jsx');
 assert(dashboard.includes('getAcademyNextLesson'));
 assert(dashboard.includes('data-testid="academy-next-lesson"'));
 assert(dashboard.includes('Revisit the guides'));
 assert(text('app/layout.jsx').includes("import '../styles/continue-learning.css'"));
});

test('new editorial illustrations and 12 Pinterest drafts are original and ready for later verified destinations',()=>{
 const added=learningGuides.slice(6);assert.equal(added.length,6);
 for(const g of added){const rel='public'+g.visual;assert(existsSync(join(root,rel)));const svg=text(rel);
   assert(svg.includes('<title')&&svg.includes('<desc')&&svg.includes('role="img"'));assert(svg.length<30000);
   assert(!/<script|<foreignObject|onload=|https?:\/\/(?!www\.w3\.org)/i.test(svg.replace('http://www.w3.org/2000/svg','')));
   assert(g.sources.some(s=>new URL(s.url).protocol==='https:'));
   assert(guideWordCount(g)>475,`${g.slug} must contain substantial human-friendly explanations`);
 }
 for(const path of academyPaths){const s=text('public'+path.cover);assert(s.includes('<title')&&s.includes('<desc')&&s.includes('role="img"'))}
 const pins=JSON.parse(text('docs/PINTEREST_ASSETS_MANIFEST.json'));assert.equal(pins.autopublish,false);assert.equal(pins.destinationHost,null);assert.equal(pins.pins.length,12);
 for(const p of pins.pins){assert(guideBySlug(p.slug));assert.equal(p.approvedToPublish,false);assert.equal(p.targetPath,'/guides/'+p.slug);assert.match(p.status,/draft/);
   const raw=read('public'+p.image);assert(raw.length>20000);assert.equal(raw.subarray(0,8).toString('hex'),'89504e470d0a1a0a');assert.equal(raw.readUInt32BE(16),1000);assert.equal(raw.readUInt32BE(20),1500);
 }
});

test('all academy routes and navigation are discoverable but stay noindexed in preview',()=>{
 for(const route of ['app/academy/page.jsx','app/academy/[pathId]/page.jsx','app/academy/[pathId]/[lessonId]/page.jsx'])assert(existsSync(join(root,route)));
 const lesson=text('app/academy/[pathId]/[lessonId]/page.jsx');assert(lesson.includes('generateStaticParams'));assert(lesson.includes('notFound()'));assert(lesson.includes('AcademyQuiz'));
 const nav=text('components/SiteHeader.jsx');assert(nav.includes("['/academy','Academy"));
 assert(text('components/Footer.jsx').includes('href="/academy"'));assert(text('app/page.jsx').includes('href="/academy"'));
 assert(text('app/layout.jsx').includes('index:false,follow:false'));
 assert(text('app/robots.js').includes("disallow:'/'"));
 const hook=text('components/useAcademyProgress.jsx');assert(hook.includes('window.localStorage'));assert(!/fetch\(|sendBeacon|XMLHttpRequest/.test(hook));
 assert(!/awardCertificate|physically_tested|test_status/.test(text('lib/academy.mjs')));
});
