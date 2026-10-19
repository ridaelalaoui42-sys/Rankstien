'use client';
import Link from 'next/link';
import Image from 'next/image';
import {academyQuizzes} from '../lib/academy.mjs';
import {guideBySlug} from '../lib/guides.mjs';
import {useAcademyProgress} from './useAcademyProgress.jsx';

export default function AcademyPath({path}){
 const {progress,ready,stats,storageError}=useAcademyProgress();
 const pathStat=stats.paths.find(p=>p.id===path.id);
 const finished=ready?pathStat.completedCount:0;
 const next=path.lessons.find(id=>!progress.completed[id])||path.lessons[0];
 return <main id="main" className="academy-root academy-path-page">
   <div className="container academy-breadcrumb"><Link href="/">Home</Link><span>/</span><Link href="/academy">Academy</Link><span>/</span><span aria-current="page">{path.title}</span></div>
   <section className={`academy-detail-hero academy-detail-${path.tone}`}><div className="container academy-detail-grid"><div><p className="academy-overline">{path.eyebrow}</p><h1>{path.title}</h1><p className="academy-detail-subtitle">{path.subtitle}</p><p>{path.description}</p><div className="academy-detail-stats"><span>{path.lessons.length} illustrated lessons</span><span>{path.minutes} min of guided learning</span><span>{finished} finished</span></div><Link href={`/academy/${path.id}/${next}`} className="btn-primary">{finished?'Continue your journey':'Begin your journey'} ↗</Link></div><Image src={path.cover} alt={`Original yarn-inspired illustration for the ${path.title} journey`} width={1200} height={700} priority sizes="(max-width: 900px) 94vw, 46vw"/></div></section>
   <section className="container academy-route-section"><div className="academy-route-intro"><p className="academy-overline">THE ROUTE / LEARN AT YOUR OWN PACE</p><h2>One skill leads to <em>another.</em></h2><p>There are no artificial locks. Explore any guide freely, then complete its short knowledge check to mark the lesson finished.</p></div>
     <div className="academy-route-track" role="list">{path.lessons.map((id,i)=>{const g=guideBySlug(id),complete=Boolean(progress.completed[id]);if(!g)return null;const current=id===next;return <article className={'academy-route-step '+(complete?'academy-step-done':'')} role="listitem" key={id}><div className="academy-route-marker"><span aria-hidden="true">{complete?'✓':String(i+1).padStart(2,'0')}</span></div><div className="academy-route-illustration"><Image src={g.visual} alt="" width={1200} height={720} sizes="(max-width:700px) 83vw, 235px"/></div><div className="academy-route-content"><p className="academy-overline">LESSON {String(i+1).padStart(2,'0')} / 04 · {g.category.toUpperCase()}</p><h3>{g.shortTitle}</h3><p>{g.description}</p><div className="academy-route-footer"><span>{complete?`✓ LEARNED · BEST ${progress.completed[id].score}/3`:current?'✳ SUGGESTED NEXT':'AVAILABLE ANYTIME'}</span><Link href={`/academy/${path.id}/${id}`}>{complete?'Review this lesson':'Start lesson'} <span aria-hidden="true">↗</span></Link></div></div></article>})}</div>
     <div className="academy-path-completion"><div><p className="academy-overline">JOURNEY PROGRESS</p><strong>{finished} of {path.lessons.length} lessons complete</strong><span>{pathStat?.complete?'✳ Journey finished! Your collectible badge is now on your dashboard.':'A little practice is enough for today.'}</span></div><div className="academy-linear" role="progressbar" aria-label="Journey completion" aria-valuemin={0} aria-valuemax={path.lessons.length} aria-valuenow={finished}><span style={{width:`${finished/path.lessons.length*100}%`}}/></div><Link href="/academy">Back to the Academy ↗</Link></div>
     {storageError?<p className="academy-storage-warning" role="status">{storageError}</p>:null}
   </section>
 </main>
}
