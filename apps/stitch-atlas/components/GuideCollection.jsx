import Image from 'next/image';
import Link from 'next/link';
import {learningGuides} from '../lib/guides.mjs';

export default function GuideCollection({guides=learningGuides,compact=false}){
  return <div className={'guide-card-grid'+(compact?' guide-card-grid-compact':'')}>
    {guides.map((guide,index)=><Link className={'guide-card guide-card-'+guide.accent} key={guide.slug} href={'/guides/'+guide.slug} aria-label={'Read: '+guide.title}>
      <div className="guide-card-illustration"><Image src={guide.visual} width={1200} height={720} alt="" loading="lazy" sizes="(max-width: 767px) 88vw, (max-width: 1100px) 44vw, 30vw"/><span className="guide-number">FIELD GUIDE / {String(index+1).padStart(2,'0')}</span></div>
      <div className="guide-card-body"><p className="kicker">{guide.category} · FREE GUIDE</p><h3>{guide.shortTitle}</h3><p>{guide.description}</p><span className="guide-read-link">Read the guide <span aria-hidden="true">↗</span></span></div>
    </Link>)}
  </div>
}
