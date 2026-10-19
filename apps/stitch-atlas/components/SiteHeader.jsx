'use client';
import {useState,useEffect} from 'react';
import Link from 'next/link';
import Image from 'next/image';
const links=[['/patterns','Pattern library'],['/guides','Free guides'],['/academy','Academy ✳'],['/learn','Learn crochet'],['/tools','Maker tools'],['/about','Our story']];
export default function SiteHeader(){
 const[open,setOpen]=useState(false);
 useEffect(()=>{function key(e){if(e.key==='Escape')setOpen(false)}document.addEventListener('keydown',key);return()=>document.removeEventListener('keydown',key)},[]);
 return <header className="site-header"><div className="header-wrap"><Link href="/" className="brand-lockup" aria-label="Stitch Atlas home"><Image src="/brand/wordmark.svg" width={245} height={69} priority alt="Stitch Atlas"/></Link><nav aria-label="Main navigation" id="site-nav" className={'site-nav '+(open?'is-open':'')}>
 {links.map(([href,label])=><Link key={href} href={href} onClick={()=>setOpen(false)}>{label}</Link>)}
 </nav><div className="header-end"><Link href="/patterns" className="header-cta">Explore patterns <span aria-hidden="true">↗</span></Link><button type="button" className="menu-toggle" aria-label={open?'Close navigation':'Open navigation'} aria-expanded={open} aria-controls="site-nav" onClick={()=>setOpen(v=>!v)}><span>{open?'×':'☰'}</span></button></div></div></header>;
}
