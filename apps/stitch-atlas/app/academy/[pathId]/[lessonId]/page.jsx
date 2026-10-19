import Image from 'next/image';
import Link from 'next/link';
import AcademyQuiz from '../../../../components/AcademyQuiz.jsx';
import {academyPaths,getAcademyLesson} from '../../../../lib/academy.mjs';
import {guideBySlug} from '../../../../lib/guides.mjs';
import {notFound} from 'next/navigation';
export const dynamicParams=false;
export function generateStaticParams(){return academyPaths.flatMap(p=>p.lessons.map(id=>({pathId:p.id,lessonId:id})))}
export async function generateMetadata({params}){const {pathId,lessonId}=await params,item=getAcademyLesson(pathId,lessonId);if(!item)return{title:'Not found',robots:{index:false}};const guide=guideBySlug(lessonId);return {title:`${guide.shortTitle} | Interactive Crochet Lesson`,description:`${guide.description} Learn with a free illustrated guide and three-question interactive quiz.`}}
export default async function LessonPage({params}){
 const {pathId,lessonId}=await params,item=getAcademyLesson(pathId,lessonId);
 if(!item)notFound();
 const {path}=item,guide=guideBySlug(lessonId);
 if(!guide)notFound();
 const lessonNumber=path.lessons.indexOf(lessonId)+1;
 const nextId=path.lessons[lessonNumber]||null;
 return <main id="main" className="academy-root academy-lesson-page">
   <div className="container academy-breadcrumb"><Link href="/academy">Academy</Link><span>/</span><Link href={`/academy/${path.id}`}>{path.title}</Link><span>/</span><span aria-current="page">Lesson {lessonNumber}</span></div>
   <section className="container academy-lesson-hero"><div className="academy-lesson-hero-text"><p className="academy-overline">{path.eyebrow} · LESSON {lessonNumber.toString().padStart(2,'0')}/04</p><h1>{guide.shortTitle}</h1><p className="academy-lesson-lede">{guide.lead}</p><div className="academy-lesson-tags"><span>ILLUSTRATED FIELD GUIDE</span><span>3-QUESTION CHECKPOINT</span><span>FREE, NO LOGIN</span></div><a className="btn-primary" href="#lesson-core">Explore the lesson ↘</a></div>
     <figure className="academy-lesson-hero-art"><Image src={guide.visual} alt={guide.shortTitle+' illustrated schematic from Stitch Atlas'} width={1200} height={720} priority sizes="(max-width: 900px) 94vw, 46vw"/><figcaption>Original educational illustration · Not a tested finished-object pattern</figcaption></figure>
   </section>
   <section className="container academy-lesson-body" id="lesson-core"><div className="academy-lesson-core"><div className="academy-overline">THE BIG IDEA / {guide.category.toUpperCase()}</div><h2>What matters <em>most.</em></h2><p>{guide.answer}</p><div className="academy-lesson-checklist"><h3>Before you move on</h3><ul>{guide.checklist.map((line,i)=><li key={i}><span aria-hidden="true">{String(i+1).padStart(2,'0')}</span>{line}</li>)}</ul></div><div className="academy-read-guide"><div><p className="academy-overline">YOUR COMPANION FIELD GUIDE</p><strong>Curious about the details?</strong><p>The full illustrated article explains how, why and when the technique is useful—with additional examples and source references.</p></div><Link href={`/guides/${guide.slug}`}>Read the full guide ↗</Link></div></div>
     <AcademyQuiz lessonId={lessonId} path={path}/>
   </section>
   <nav className="container academy-lesson-nav" aria-label="Next academy lesson"><Link href={`/academy/${path.id}`}>← All lessons in this journey</Link>{nextId?<Link href={`/academy/${path.id}/${nextId}`}>Continue to the next lesson ↗</Link>:<Link href="/academy">Your academy dashboard ↗</Link>}</nav>
 </main>
}
