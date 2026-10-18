'use client';
import {useEffect,useState} from 'react';
const STORAGE_KEY='stitch-atlas-saved-guides-v1';
export default function GuideActions({slug}){
  const [saved,setSaved]=useState(false),[notice,setNotice]=useState('');
  useEffect(()=>{try{const keys=JSON.parse(window.localStorage.getItem(STORAGE_KEY)||'[]');setSaved(Array.isArray(keys)&&keys.includes(slug))}catch{setSaved(false)}},[slug]);
  function toggle(){try{
    const parsed=JSON.parse(window.localStorage.getItem(STORAGE_KEY)||'[]');
    const current=Array.isArray(parsed)?parsed.filter(x=>typeof x==='string'&&x.length<100).slice(0,100):[];
    const updated=(saved?current.filter(x=>x!==slug):Array.from(new Set([...current,slug]))).slice(-100);
    window.localStorage.setItem(STORAGE_KEY,JSON.stringify(updated));setSaved(!saved);setNotice(!saved?'Saved in this browser':'Removed from this browser');
  }catch{setNotice('Browser storage is unavailable. You can still read the guide.')}}
  async function copy(){try{await navigator.clipboard.writeText(window.location.href);setNotice('Guide link copied')}catch{setNotice('Copy the link from your browser address bar')}}
  return <div className="guide-actions" aria-label="Guide tools"><button type="button" aria-pressed={saved} onClick={toggle}>{saved?'♥ Saved':'♡ Save for later'}</button><button type="button" onClick={copy}>↗ Copy link</button><button type="button" onClick={()=>window.print()}>▣ Print guide</button><span className="guide-action-status" role="status" aria-live="polite">{notice}</span></div>;
}
