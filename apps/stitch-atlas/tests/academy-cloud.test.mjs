import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {getAcademyStats,academyPaths} from '../lib/academy.mjs';
import {mergeAcademyScores,serializeAcademyBackup,mergeAcademyBackup} from '../lib/academy-backup.mjs';
import {academyCloudConfigured,ACADEMY_OWNER_KEY} from '../lib/academy-cloud.mjs';

const file=(name)=>readFileSync(new URL('../'+name,import.meta.url),'utf8');
const first=academyPaths[0].lessons[0],second=academyPaths[0].lessons[1];
const mastered=(id,score=3)=>({version:1,completed:{[id]:{score,completedAt:'2026-10-19T00:00:00.000Z'}}});

test('Google cloud auth stays strictly opt-in; no Firebase SDK access in an unconfigured build',()=>{
  assert.equal(academyCloudConfigured,false);
  assert.match(ACADEMY_OWNER_KEY,/owner/);
  const code=file('lib/academy-cloud.mjs');
  assert.match(code,/academyCloudConfigured/);
  assert.match(code,/if\(!academyCloudConfigured\)/);
  assert.match(code,/auth\.currentUser\?\.uid!==user\.uid/);
  assert.match(code,/runTransaction/);
  assert.doesNotMatch(code,/serviceAccount|PRIVATE_KEY|firebase-admin|recetagenial|recetadolce/i);
});

test('best-score cloud merging is idempotent and never duplicates learning points',()=>{
  const local=mastered(first,2);
  const remote=mastered(first,3);
  remote.completed[second]={score:2,completedAt:'2026-10-19T00:00:00.000Z'};
  const merged=mergeAcademyScores(remote,local);
  assert.equal(merged.completed[first].score,3);
  assert.equal(merged.completed[second].score,2);
  assert.deepEqual(mergeAcademyScores(merged,local),merged);
  assert.equal(getAcademyStats(merged).xp,125);
});

test('sign in from guest merges earned lessons with scores from a different device',()=>{
  const local=mastered(first,3),remote=mastered(second,2);
  const merged=mergeAcademyScores(local,remote);
  assert.equal(getAcademyStats(merged).completedCount,2);
  assert.equal(getAcademyStats(merged).xp,125);
});

test('a corrupt backup cannot change progress; importing twice earns no extra XP',()=>{
  const local=mastered(first,2);
  const raw=serializeAcademyBackup(mastered(second,3));
  const restored=mergeAcademyBackup(raw,local);
  const again=mergeAcademyBackup(raw,restored);
  assert.equal(getAcademyStats(again).xp,getAcademyStats(restored).xp);
  assert.throws(()=>mergeAcademyBackup('{bad',local));
  assert.throws(()=>mergeAcademyBackup(JSON.stringify({kind:'nonsense'}),local));
});

test('Firestore rules restrict own document, known lessons, safe scores and disallow listing',()=>{
  const rules=file('firestore.rules');
  assert.match(rules,/request\.auth\.uid == userId/g);
  assert.match(rules,/allow get:/);
  assert.match(rules,/allow list: if false/);
  assert.match(rules,/allow delete: if false/);
  assert.match(rules,/updatedAt == request\.time/);
  assert.match(rules,/completed is map/);
  assert.match(rules,/score >= 2/);
  assert.match(rules,/score <= 3/);
  assert.match(rules,/keys\(\)\.hasOnly/);
  for(const path of academyPaths)for(const id of path.lessons)assert(rules.includes("validOne('"+id+"')"));
});

test('dashboard presents a guest path and an account path without publishing personal details',()=>{
  const dash=file('components/AcademyDashboard.jsx');
  const panel=file('components/AcademyCloudAccount.jsx');
  assert(dash.includes('<AcademyCloudAccount'));
  assert(panel.includes('cloudConfigured'));
  assert(panel.includes('Continue with Google'));
  assert(panel.includes('guest'));
  const hook=file('components/useAcademyProgress.jsx');
  assert(hook.includes('ACADEMY_OWNER_KEY'));
  assert(hook.includes('removeItem(ACADEMY_OWNER_KEY)'));
  assert(hook.includes('syncAcademyGoogleProgress'));
  assert(hook.includes('clearAcademyGoogleProgress'));
});

test('Firebase public config requires four values and no service role credentials',()=>{
  const example=file('.env.example');
  for(const name of ['NEXT_PUBLIC_FIREBASE_API_KEY','NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN','NEXT_PUBLIC_FIREBASE_PROJECT_ID','NEXT_PUBLIC_FIREBASE_APP_ID'])
    assert(example.includes(name+'='));
  assert(!example.includes('FIREBASE_PRIVATE_KEY'));
  const packageJson=JSON.parse(file('package.json'));
  assert.match(packageJson.dependencies.firebase,/^(\^)?13\./);
  assert.equal(packageJson.scripts['test:cloud'],'node --test tests/academy-cloud.test.mjs');
});
