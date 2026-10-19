'use client';
import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {ACADEMY_STORAGE_KEY,cleanAcademyProgress,applyQuizResult,getAcademyStats} from '../lib/academy.mjs';
import {mergeAcademyScores,mergeAcademyBackup,serializeAcademyBackup} from '../lib/academy-backup.mjs';
import {
 ACADEMY_OWNER_KEY,ACADEMY_GUEST_KEY,academyGenerationKey,sanitizeGeneration,academyCloudConfigured,watchAcademyGoogleUser,
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
 const [guestCount,setGuestCount]=useState(0);
 const currentRef=useRef(blank());
 const userRef=useRef(null);
 const mountedRef=useRef(false);
 const syncVersionRef=useRef(0);
 const generationRef=useRef(0);
 const updateProgress=useCallback((value,uid)=>{
   const cleaned=cleanAcademyProgress(value);
   currentRef.current=cleaned;
   if(mountedRef.current)setProgress(cleaned);
   const storage=safeLocal();
   try{
     if(storage){
       storage.setItem(ACADEMY_STORAGE_KEY,JSON.stringify(cleaned));
       if(uid)storage.setItem(ACADEMY_OWNER_KEY,uid);
       else{storage.removeItem(ACADEMY_OWNER_KEY);storage.setItem(ACADEMY_GUEST_KEY,JSON.stringify(cleaned));}
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
     const result=await syncAcademyGoogleProgress(user,initial,generationRef.current);
     if(!mountedRef.current||userRef.current?.uid!==user.uid||callId!==syncVersionRef.current)return;
     if(result.generation>generationRef.current){
       generationRef.current=result.generation;
       try{window.localStorage.setItem(academyGenerationKey(user.uid),String(result.generation))}catch{}
     }
     // A reset on another device must override older cached lessons.
     const combined=result.stale?result.progress:mergeAcademyScores(currentRef.current,result.progress);
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
       try{storage?.setItem(ACADEMY_GUEST_KEY,JSON.stringify(local))}catch{}
     }
   }catch{setStorageError('Saved progress could not be read. Your lessons still work; a backup may help recover it.');}
   try{const raw=storage?.getItem(ACADEMY_GUEST_KEY);setGuestCount(raw?Object.keys(cleanAcademyProgress(JSON.parse(raw)).completed).length:0)}catch{}
   setReady(true);
   if(academyCloudConfigured){
     watchAcademyGoogleUser(async user=>{
       if(disposed)return;
       if(!user){
         userRef.current=null;setAccount(null);setCloudStatus('guest');
         // After sign-out on a shared device, remove previous account's cached scores.
         const previousOwner=storage?.getItem(ACADEMY_OWNER_KEY);
         if(previousOwner){
           const guestRaw=storage?.getItem(ACADEMY_GUEST_KEY);
           const savedGuest=cleanAcademyProgress(guestRaw?JSON.parse(guestRaw):null);
           currentRef.current=savedGuest;setProgress(savedGuest);
           try{storage?.setItem(ACADEMY_STORAGE_KEY,JSON.stringify(savedGuest));storage?.removeItem(ACADEMY_OWNER_KEY)}catch{}
         }
         return;
       }
       userRef.current=user;
       setAccount({uid:user.uid,name:user.displayName||'Crochet maker',email:user.email||''});
       let local=blank();
       try{
         const recordedOwner=storage?.getItem(ACADEMY_OWNER_KEY)||'';
         if(!recordedOwner){
           const raw=storage?.getItem(ACADEMY_STORAGE_KEY);
           const guest=cleanAcademyProgress(raw?JSON.parse(raw):null);
           storage?.setItem(ACADEMY_GUEST_KEY,JSON.stringify(guest));
           setGuestCount(Object.keys(guest.completed).length);
         }else if(recordedOwner===user.uid){
           const raw=storage?.getItem(ACADEMY_STORAGE_KEY);
           local=cleanAcademyProgress(raw?JSON.parse(raw):null);
         }
         generationRef.current=sanitizeGeneration(Number(storage?.getItem(academyGenerationKey(user.uid))||0));
       }catch{}
       // Guest lessons are NEVER uploaded automatically on a shared device.
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
       const generation=await clearAcademyGoogleProgress(user);
       if(userRef.current?.uid!==user.uid)return false;
       syncVersionRef.current++;
       generationRef.current=generation;
       try{window.localStorage.setItem(academyGenerationKey(user.uid),String(generation))}catch{}
       updateProgress(blank(),user.uid);setCloudStatus('saved');return true;
     }catch{
       setCloudStatus('error');
       setCloudError('Cloud progress could not be cleared. Your existing milestones have been kept.');return false;
     }
   }else{
     syncVersionRef.current++;
     currentRef.current=blank();setProgress(blank());
     try{const storage=safeLocal();storage?.removeItem(ACADEMY_STORAGE_KEY);storage?.removeItem(ACADEMY_GUEST_KEY);storage?.removeItem(ACADEMY_OWNER_KEY);setStorageError('');setGuestCount(0)}catch{setStorageError('Unable to clear saved progress in this browser.');}
     return true;
   }
 },[updateProgress]);
 const importGuest=useCallback(async()=>{
   const user=userRef.current,storage=safeLocal();if(!user||!storage)return false;
   try{
     const raw=storage.getItem(ACADEMY_GUEST_KEY);
     const guest=cleanAcademyProgress(raw?JSON.parse(raw):null);
     if(!Object.keys(guest.completed).length)return true;
     setCloudStatus('syncing');setCloudError('');
     // Explicit opt-in only. Confirm the transaction before erasing the guest copy.
     const response=await syncAcademyGoogleProgress(user,mergeAcademyScores(currentRef.current,guest),generationRef.current);
     if(userRef.current?.uid!==user.uid)return false;
     if(response.stale){generationRef.current=response.generation;updateProgress(response.progress,user.uid);setCloudError('Your account was reset on another device. Please review and retry importing.');setCloudStatus('error');return false;}
     updateProgress(response.progress,user.uid);storage.removeItem(ACADEMY_GUEST_KEY);setGuestCount(0);setCloudStatus('saved');return true;
   }catch{setCloudStatus('error');setCloudError('Guest import could not reach the private account. Your guest backup is still on this device.');return false;}
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
 return {progress,stats,ready,record,reset,storageError,cloudConfigured:academyCloudConfigured,account,cloudStatus,cloudError,guestCount,importGuest,signIn,signOut,syncNow,exportProgress,importProgress};
}
