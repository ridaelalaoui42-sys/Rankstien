'use client';
import Image from 'next/image';
import Link from 'next/link';
import {useState} from 'react';
import {ACADEMY_BADGES,academyPaths} from '../lib/academy.mjs';
import {useAcademyProgress} from './useAcademyProgress.jsx';
import AcademyCloudAccount from './AcademyCloudAccount.jsx';

function Wreath({percent=0}){return <div className="academy-wreath" aria-label={`${percent}% of all lessons completed`} role="img"><svg viewBox="0 0 140 140" aria-hidden="true"><circle cx="70" cy="70" r="58" className="academy-wreath-base"/><circle cx="70" cy="70" r="58" className="academy-wreath-value" strokeDasharray={`${365*percent/100} 365`}/></svg><div><strong>{percent}%</strong><small>COMPLETE</small></div></div>}
function PathTile({path,index,progress}){
 const finished=path.lessons.filter(id=>progress.completed[id]).length;
 const next=path.lessons.find(id=>!progress.completed[id])||path.lessons[0];
 return <article className={`academy-path-card academy-path-${path.tone}`}>
   <div className="academy-path-art"><Image src={path.cover} alt={`Original Stitch Atlas illustration for ${path.title}`} width={1200} height={700} sizes="(max-width: 740px) 90vw, (max-width: 1140px) 46vw, 32vw"/><div className="academy-path-index">JOURNEY {String(index+1).padStart(2,'0')} / 03</div></div>
   <div className="academy-path-copy"><p className="academy-overline">{path.eyebrow}</p><h3>{path.title}</h3><p>{path.description}</p>
   <div className="academy-path-stats"><span>{finished} / {path.lessons.length} lessons</span><span>~{path.minutes} min of reading</span></div>
   <div role="progressbar" aria-label={`${path.title} completion`} aria-valuenow={finished} aria-valuemin={0} aria-valuemax={path.lessons.length} className="academy-linear"><span style={{width:`${finished/path.lessons.length*100}%`}}/></div>
   <Link href={`/academy/${path.id}`} className="academy-path-cta">{finished===path.lessons.length?'Review the journey':finished?'Continue this journey':'Explore the journey'} <span aria-hidden="true">↗</span></Link>
   {finished>0 && finished<path.lessons.length?<Link href={`/academy/${path.id}/${next}`} className="academy-mini-link">Next lesson: resume here →</Link>:null}
   </div>
  </article>
}

export default function AcademyDashboard(){
 const academy=useAcademyProgress();
 const {progress,stats,ready,reset,storageError}=academy;
 const [confirmReset,setConfirmReset]=useState(false);
 return <main id="main" className="academy-root">
   <div className="academy-masthead"><div className="container academy-masthead-inner"><div className="academy-masthead-text">
      <p className="academy-overline">STITCH ATLAS PRESENTS · THE MAKER'S ACADEMY</p>
      <div className="academy-sparkles" aria-hidden="true">✳ &nbsp; ✥ &nbsp; ✳</div>
      <h1>Small stitches.<br/><em>Big discoveries.</em></h1>
      <p>Learn crochet a little differently. Follow three illustrated learning journeys, answer friendly visual quizzes, and collect meaningful milestones as your understanding grows.</p>
      <div className="academy-masthead-actions"><a href="#paths" className="btn-primary">Choose a learning path <span aria-hidden="true">↗</span></a><Link href="/guides" className="academy-quiet-link">Explore all 12 illustrated guides →</Link></div>
      <div className="academy-confidentiality">✳ &nbsp; Free learning · No account · Your progress stays on this device</div>
    </div><div className="academy-masthead-illustration"><div className="academy-paper-shape"><div className="academy-paper-stamp">A LITTLE PRACTICE, EVERY DAY</div><svg viewBox="0 0 390 420" aria-hidden="true" role="presentation"><circle cx="195" cy="197" r="150" fill="#f7f0e5" stroke="#d8ba9e" strokeWidth="3"/>{Array.from({length:9},(_,i)=><path key={i} d={`M ${73+i*28} 95 C ${40+i*18} 184, ${100+i*26} 225, ${78+i*28} 301`} fill="none" stroke={i%2?'#738d78':'#bd795c'} strokeWidth="8" strokeLinecap="round" opacity=".82"/>)}<circle cx="194" cy="192" r="84" fill="none" stroke="#eee0ca" strokeWidth="20"/><path d="M205 331 C 242 347, 290 380, 349 340" fill="none" stroke="#b66e57" strokeWidth="9" strokeLinecap="round"/><path d="M320 338 l32 1 l-10 25" fill="none" stroke="#b66e57" strokeWidth="5" strokeLinecap="round"/></svg><p>every loop, a little progress</p></div></div>
   </div></div>
   <section className="container academy-progress-summary" aria-labelledby="your-progress-title">
     <div className="academy-summary-copy"><p className="academy-overline">YOUR QUIET COLLECTION OF MILESTONES</p><h2 id="your-progress-title">Progress is a <em>beautiful thing.</em></h2><p>Make mistakes, learn why, and try again. You pass a three-question checkpoint with two correct answers. A perfect quiz adds a little extra sparkle.</p></div>
     <Wreath percent={ready?stats.percent:0}/>
     <div className="academy-stats-panel"><div><strong data-testid="academy-completed">{ready?stats.completedCount:0}<span>/{stats.totalCount}</span></strong><small>LESSONS FINISHED</small></div><div><strong data-testid="academy-xp">{ready?stats.xp:0}</strong><small>LEARNING POINTS</small></div></div>
   </section>
   {storageError?<p className="container academy-storage-warning" role="status">{storageError}</p>:null}
   <div className="container academy-account-wrap"><AcademyCloudAccount {...academy}/></div>
   <section id="paths" className="academy-paths-section" aria-labelledby="academy-paths-title"><div className="container"><div className="academy-section-heading"><p className="academy-overline">THE LEARNING MAP / SELECT A JOURNEY</p><h2 id="academy-paths-title">A world of <em>wonderful loops.</em></h2><p>Each lesson links to a free in-depth guide, plus a three-question checkpoint. You can revisit any step at any time.</p></div><div className="academy-path-grid">{academyPaths.map((path,i)=><PathTile key={path.id} path={path} index={i} progress={progress}/>)}</div></div></section>
   <section className="container academy-badges-section" aria-labelledby="badge-title"><div className="academy-section-heading"><p className="academy-overline">THE LITTLE THINGS WORTH CELEBRATING</p><h2 id="badge-title">Collect the <em>moments.</em></h2><p>Milestones recognize finished learning quizzes, not certified crochet skill or physically completed projects.</p></div><div className="academy-badge-grid">{ACADEMY_BADGES.map(b=><div key={b.id} className={'academy-badge '+(stats.badges.includes(b.id)?'academy-earned':'academy-pending')} aria-label={`${b.title}: ${stats.badges.includes(b.id)?'earned':'not earned yet'}`}><div className="academy-badge-mark" aria-hidden="true"><Image src={`/academy/badge-${b.id}.svg`} alt="" width={230} height={230}/></div><strong>{b.title}</strong><span>{b.desc}</span><small>{stats.badges.includes(b.id)?'✳ COLLECTED':'COMING SOON'}</small></div>)}</div><div className="academy-data-controls"><p>{academy.account?"Google account progress can sync across devices. You can also export your local backup.":"Guest scores remain in your browser. Sign in with Google once cloud saving is configured to carry them to another device."}</p>{confirmReset?<div className="academy-reset-confirm"><span>Clear all recorded quiz progress on this device?</span><button type="button" onClick={()=>{reset();setConfirmReset(false)}}>Yes, clear progress</button><button type="button" onClick={()=>setConfirmReset(false)}>Keep my progress</button></div>:<button className="academy-reset" type="button" onClick={()=>setConfirmReset(true)}>Start over on this device</button>}</div></section>
 </main>
}
