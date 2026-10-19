'use client';
import {useCallback,useEffect,useMemo,useState} from 'react';
import {ACADEMY_STORAGE_KEY,cleanAcademyProgress,applyQuizResult,getAcademyStats} from '../lib/academy.mjs';

/** Offline by design. No identity, analytics, signup, remote sync or cookies. */
export function useAcademyProgress(){
  const [progress,setProgress]=useState(()=>cleanAcademyProgress(null));
  const [ready,setReady]=useState(false);
  const [storageError,setStorageError]=useState('');
  useEffect(()=>{
    try{const raw=window.localStorage.getItem(ACADEMY_STORAGE_KEY);if(raw)setProgress(cleanAcademyProgress(JSON.parse(raw)))}
    catch{setStorageError('Saved progress could not be read. Your lessons still work; you can clear site storage to start over.');}
    setReady(true);
    const sync=event=>{
      if(event.key!==ACADEMY_STORAGE_KEY)return;
      try{setProgress(cleanAcademyProgress(event.newValue?JSON.parse(event.newValue):null))}catch{setStorageError('Another tab saved invalid progress; the learning session is still available.')}
    };
    window.addEventListener('storage',sync);return()=>window.removeEventListener('storage',sync);
  },[]);
  const record=useCallback((lessonId,grade)=>{
    const next=applyQuizResult(progress,lessonId,grade);
    setProgress(next);
    try{window.localStorage.setItem(ACADEMY_STORAGE_KEY,JSON.stringify(next));setStorageError('');}
    catch{setStorageError('Browser storage is unavailable. Results are visible in this tab, but may not persist.')}
  },[progress]);
  const reset=useCallback(()=>{
    try{window.localStorage.removeItem(ACADEMY_STORAGE_KEY);setStorageError('')}
    catch{setStorageError('Could not clear browser storage; check your browser settings.')}
    setProgress(cleanAcademyProgress(null));
  },[]);
  const stats=useMemo(()=>getAcademyStats(progress),[progress]);
  return {progress,stats,ready,record,reset,storageError};
}
