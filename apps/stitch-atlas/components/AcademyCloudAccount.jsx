'use client';
/** Calm optional account UI. No dark patterns or forced signup. */
export default function AcademyCloudAccount({cloudConfigured,account,cloudStatus,cloudError,signIn,signOut,syncNow}){
 return <section className="academy-cloud-account" aria-labelledby="academy-cloud-title">
   <div className="academy-cloud-copy"><p className="academy-overline">YOUR STITCHES CAN TRAVEL WITH YOU</p>
     <h2 id="academy-cloud-title">{account?'Welcome back, maker.':'Keep your learning close.'}</h2>
     <p>{account?'Your completed lessons and best quiz scores can follow your Google account across devices. Your progress is private.':'Keep learning freely as a guest. When Google sign-in is connected, you can optionally save your lesson progress on any device.'}</p>
     <p className="academy-cloud-privacy">✳ No leaderboard. No certificate claims. No Gmail access. Account email is not stored in your learning-progress document.</p></div>
   <div className="academy-cloud-actions">
     {account?<><div className="academy-cloud-identity"><strong>{account.name}</strong><small>{account.email}</small></div><button type="button" className="academy-cloud-button" onClick={syncNow} disabled={cloudStatus==='syncing'}>↻ {cloudStatus==='syncing'?'Syncing your progress…':'Sync progress now'}</button><button type="button" className="academy-cloud-secondary" onClick={signOut}>Sign out of Google</button></>:
       cloudConfigured?<button className="academy-google-button" type="button" disabled={cloudStatus==='connecting'} onClick={signIn}><span aria-hidden="true">G</span> {cloudStatus==='connecting'?'Connecting…':'Continue with Google'}</button>:
       <div className="academy-cloud-unconfigured" role="status">✳ Google cloud saving is not connected yet. Your guest progress stays on this device.</div>}
     {account&&cloudStatus==='saved'?<p className="academy-cloud-status" role="status">✓ Best scores synced to your private account.</p>:null}
     {cloudError?<p className="academy-cloud-error" role="alert">{cloudError}</p>:null}
   </div>
 </section>;
}