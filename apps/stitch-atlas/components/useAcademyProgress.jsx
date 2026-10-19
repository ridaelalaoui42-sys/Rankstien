'use client';
import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {ACADEMY_STORAGE_KEY,cleanAcademyProgress,applyQuizResult,getAcademyStats} from '../lib/academy.mjs';
import {mergeAcademyScores,mergeAcademyBackup,serializeAcademyBackup} from '../lib/academy-backup.mjs';
import {
 ACADEMY_OWNER_KEY,academyCloudConfigured,watchAcademyGoogleUser,
 signInAcademyWithGoogle,signOutAcademyGoogle,syncAcademyGoogleProgress,
 clearAcademyGoogleProgress,
} from '../lib/academy-cloud.mjs';

const blank=()=>cleanAcademyProgress(null);
const safeLocal=()=>{try{return window.localStorage}catch{return null}};

/** Guest-first Academy. Google sign-in and Firestore are entirely optional.
 * Save locally first, sync using best-score transaction when authorized.
 * Never migrate progress from a DIFFERENT Google account on shared devices.
 */
export function useAcademyProgress(){
 const [progress,setProgress]=useState(blank);
 const [ready,setReady]=useState(false);
 const [storageError,setStorageError]=useState('');
 const [account,setAccount]=useState(null);
 const [cloudStatus,setCloudStatus]=useState(academyCloudConfigured?'connecting':'unconfigured');
 const [cloudError,setCloudError]=useState('');
 const currentRef=useRef(blank());
 const userRef=useRef(null);
 const mountedRef=useRef(false);
 const syncVersionRef=useRef(0);
 const updateProgress=useCallback((value,uid)=>{
   const cleaned=cleanAcademyProgress(value);
   currentRef.current=cleaned;
   if(mountedRef.current)setProgress(cleaned);
   const storage=safeLocal();
   try{
     if(storage){
       storage.setItem(ACADEMY_STORAGE_KEY,JSON.stringify(cleaned));
       if(uid)storage.setItem(ACADEMY_OWNER_KEY,uid);
       else storage.removeItem(ACADEMY_OWNER_KEY);
     }
     if(mountedRef.current)setStorageError('');
   }catch{
     if(mountedRef.current)setStorageError('Your progress is visible here but browser storage could not save it. Export a backup when possible.');
   }
   return cleaned;
 },[]);
 const synchronize=useCallback(async(user,initial=currentRef.current)=>{
   if(!user?.uid)return;
   const callId=++syncVersionRef.current;
   if(mountedRef.current){setCloudStatus('syncing');setCloudError('');}
   try{
     const server=await syncAcademyGoogleProgress(user,initial);
     if(!mountedRef.current||userRef.current?.uid!==user.uid||callId!==syncVersionRef.current)return;
     // A quiz may have finished while the network was busy. Never erase its new score.
     const combined=mergeAcademyScores(currentRef.current,server);
     updateProgress(combined,user.uid);
     if(mountedRef.current)setCloudStatus('saved');
     // If local progress advanced after transaction began, send it on the next
     // quiz/reconnect/manual synchronization. Never claim a bad write is saved.
   }catch(error){
     if(mountedRef.current&&userRef.current?.uid===user.uid&&callId===syncVersionRef.current){
       setCloudStatus('error');
       setCloudError('Cloud sync is unavailable right now. Your lesson results remain saved on this device. Try Sync again.');
     }
   }
 },[updateProgress]);
 useEffect(()=>{
   mountedRef.current=true;
   let disposed=false;
   let unsubscribe=null;
   const storage=safeLocal();
   let owner='';
   try{
     owner=storage?.getItem(ACADEMY_OWNER_KEY)||'';
     if(!owner){
       const raw=storage?.getItem(ACADEMY_STORAGE_KEY);
       const local=cleanAcademyProgress(raw?JSON.parse(raw):null);
       currentRef.current=local;
       setProgress(local);
     }
   }catch{setStorageError('Saved progress could not be read. Your lessons still work; a backup may help recover it.');}
   setReady(true);
   if(academyCloudConfigured){
     watchAcademyGoogleUser(async user=>{
       if(disposed)return;
       if(!user){
         userRef.current=null;setAccount(null);setCloudStatus('guest');
         // After sign-out on a shared device, remove previous account's cached scores.
         const previousOwner=storage?.getItem(ACADEMY_OWNER_KEY);
         if(previousOwner){
           currentRef.current=blank();setProgress(blank());
           try{storage?.removeItem(ACADEMY_STORAGE_KEY);storage?.removeItem(ACADEMY_OWNER_KEY)}catch{}
         }
         return;
       }
       userRef.current=user;
       setAccount({uid:user.uid,name:user.displayName||'Crochet maker',email:user.email||''});
       let local=blank();
       try{
         const recordedOwner=storage?.getItem(ACADEMY_OWNER_KEY)||'';
         if(!recordedOwner||recordedOwner===user.uid){
           const raw=storage?.getItem(ACADEMY_STORAGE_KEY);
           local=cleanAcademyProgress(raw?JSON.parse(raw):null);
         }
       }catch{}
       // Immediately isolate this account, even when online cloud sync is blocked.
       updateProgress(local,user.uid);
       await synchronize(user,local);
     }).then(cancel=>{if(disposed)cancel();else unsubscribe=cancel}).catch(()=>{
       if(!disposed){setCloudStatus('error');setCloudError('Google sign-in could not initialize. You can continue learning as a guest.');}
     });
   }
   const online=()=>{if(userRef.current)synchronize(userRef.current)};
   window.addEventListener('online',online);
   const onStorage=e=>{
     if(e.key!==ACADEMY_STORAGE_KEY||!e.newValue)return;
     const expected=userRef.current?.uid||'';
     const owner=safeLocal()?.getItem(ACADEMY_OWNER_KEY)||'';
     if(owner!==expected)return;
     try{const next=cleanAcademyProgress(JSON.parse(e.newValue));currentRef.current=next;if(mountedRef.current)setProgress(next)}catch{}
   };
   window.addEventListener('storage',onStorage);
   return()=>{disposed=true;mountedRef.current=false;syncVersionRef.current++;unsubscribe?.();window.removeEventListener('online',online);window.removeEventListener('storage',onStorage)};
 },[synchronize,updateProgress]);
 const record=useCallback((lessonId,grade)=>{
   const next=applyQuizResult(currentRef.current,lessonId,grade);
   const user=userRef.current;
   updateProgress(next,user?.uid||null);
   if(user)void synchronize(user,next);
 },[synchronize,updateProgress]);
 const reset=useCallback(async()=>{
   const user=userRef.current;
   if(user){
     setCloudStatus('syncing');setCloudError('');
     try{
       await clearAcademyGoogleProgress(user);
       if(userRef.current?.uid!==user.uid)return;
       syncVersionRef.current++;
       updateProgress(blank(),user.uid);setCloudStatus('saved');
     }catch{
       setCloudStatus('error');
       setCloudError('Cloud progress could not be cleared. Your existing milestones have been kept.');
     }
   }else{
     syncVersionRef.current++;
     currentRef.current=blank();setProgress(blank());
     try{const storage=safeLocal();storage?.removeItem(ACADEMY_STORAGE_KEY);storage?.removeItem(ACADEMY_OWNER_KEY);setStorageError('')}catch{setStorageError('Unable to clear saved progress in this browser.');}
   }
 },[updateProgress]);
 const signIn=useCallback(async()=>{
   if(!academyCloudConfigured)return;
   setCloudStatus('connecting');setCloudError('');
   try{await signInAcademyWithGoogle()}catch(error){
     setCloudStatus('guest');
     if(error?.code!=='auth/popup-closed-by-user')setCloudError('Google sign-in was not completed. Check pop-up permissions or the Firebase authorized domain.');
   }
 },[]);
 const signOut=useCallback(async()=>{
   try{await signOutAcademyGoogle()}catch{setCloudError('Could not sign out. Please retry.');}
 },[]);
 const syncNow=useCallback(()=>{if(userRef.current)return synchronize(userRef.current)},[synchronize]);
 const exportProgress=useCallback(()=>serializeAcademyBackup(currentRef.current),[]);
 const importProgress=useCallback(async text=>{
   const merged=mergeAcademyBackup(text,currentRef.current);
   const user=userRef.current;
   updateProgress(merged,user?.uid||null);
   if(user)await synchronize(user,merged);
   return getAcademyStats(merged).completedCount;
 },[updateProgress,synchronize]);
 const stats=useMemo(()=>getAcademyStats(progress),[progress]);
 return {progress,stats,ready,record,reset,storageError,cloudConfigured:academyCloudConfigured,account,cloudStatus,cloudError,signIn,signOut,syncNow,exportProgress,importProgress};
}
