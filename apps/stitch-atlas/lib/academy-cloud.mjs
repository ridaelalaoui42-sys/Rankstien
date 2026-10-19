/** Optional browser-only Firebase Google sign-in and Firestore score synchronization.
 * No Admin SDK, no service account and no access to recipe projects.
 * Cloud is OFF unless all four explicit NEXT_PUBLIC_FIREBASE_* values exist.
 */
import {ACADEMY_VERSION,cleanAcademyProgress} from './academy.mjs';
import {mergeAcademyScores} from './academy-backup.mjs';

const config={
  apiKey:process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain:process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId:process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  appId:process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
};
export const ACADEMY_OWNER_KEY='stitch-atlas.academy.local-owner.v1';
export const ACADEMY_GUEST_KEY='stitch-atlas.academy.guest-progress.v1';
export const academyGenerationKey=uid=>`stitch-atlas.academy.generation.${uid}`;
export const sanitizeGeneration=n=>Number.isSafeInteger(n)&&n>=0&&n<=1000000?n:0;
export const academyCloudConfigured=Boolean(
  config.apiKey && config.authDomain && config.projectId && config.appId &&
  /^[-\w]+\.firebaseapp\.com$/.test(config.authDomain) &&
  /^[-\w]+$/.test(config.projectId)
);

let runtimePromise=null;
async function runtime(){
  if(!academyCloudConfigured)throw Error('Google cloud saving is not configured yet.');
  if(!runtimePromise){
    runtimePromise=Promise.all([
      import('firebase/app'),import('firebase/auth'),import('firebase/firestore')
    ]).then(([app,authApi,dbApi])=>{
      const instance=app.getApps().find(x=>x.name==='stitch-atlas-academy')||
        app.initializeApp(config,'stitch-atlas-academy');
      const auth=authApi.getAuth(instance);
      const db=dbApi.getFirestore(instance);
      const provider=new authApi.GoogleAuthProvider();
      provider.setCustomParameters({prompt:'select_account'});
      return {auth,db,provider,authApi,dbApi};
    }).catch(error=>{runtimePromise=null;throw error});
  }
  return runtimePromise;
}

export async function watchAcademyGoogleUser(callback){
  const {auth,authApi}=await runtime();
  return authApi.onAuthStateChanged(auth,callback);
}
export async function signInAcademyWithGoogle(){
  const {auth,provider,authApi}=await runtime();
  return authApi.signInWithPopup(auth,provider);
}
export async function signOutAcademyGoogle(){
  const {auth,authApi}=await runtime();
  return authApi.signOut(auth);
}
export async function syncAcademyGoogleProgress(user,localProgress,clientGeneration=0){
  if(!user?.uid)throw Error('A signed-in Google account is required.');
  const {auth,db,dbApi}=await runtime();
  if(auth.currentUser?.uid!==user.uid)throw Error('The Google account changed. Progress was not uploaded.');
  const ref=dbApi.doc(db,'academyProgress',user.uid);
  return dbApi.runTransaction(db,async transaction=>{
    const snap=await transaction.get(ref);
    const data=snap.exists()?snap.data():null;
    const remote=cleanAcademyProgress(data);
    const generation=sanitizeGeneration(data?.generation);
    // A reset on another device supersedes stale local results. Do not resurrect them.
    if(generation>sanitizeGeneration(clientGeneration))return {progress:remote,generation,stale:true};
    const merged=mergeAcademyScores(remote,localProgress);
    if(!snap.exists()||JSON.stringify(remote.completed)!==JSON.stringify(merged.completed))
      transaction.set(ref,{version:ACADEMY_VERSION,generation,completed:merged.completed,updatedAt:dbApi.serverTimestamp()});
    return {progress:merged,generation,stale:false};
  },{maxAttempts:5});
}
export async function clearAcademyGoogleProgress(user){
  if(!user?.uid)throw Error('Sign in to clear cloud progress.');
  const {auth,db,dbApi}=await runtime();
  if(auth.currentUser?.uid!==user.uid)throw Error('Google account changed during reset.');
  const ref=dbApi.doc(db,'academyProgress',user.uid);
  return dbApi.runTransaction(db,async transaction=>{
    const snap=await transaction.get(ref);
    const generation=sanitizeGeneration(snap.exists()?snap.data()?.generation:0)+1;
    transaction.set(ref,{version:ACADEMY_VERSION,generation,completed:{},updatedAt:dbApi.serverTimestamp()});
    return generation;
  });
}
