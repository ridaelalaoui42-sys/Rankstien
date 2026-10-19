/** Emulator-only. Never requires or connects a production Firebase project.
 * Run inside: firebase emulators:exec --project demo-stitch-atlas-rules --only firestore
 */
import {test,before,after,beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {assertFails,assertSucceeds,initializeTestEnvironment} from '@firebase/rules-unit-testing';
import {collection,deleteDoc,doc,getDoc,getDocs,serverTimestamp,setDoc} from 'firebase/firestore';

const projectId='demo-stitch-atlas-rules';
let env;
const lesson='us-uk-crochet-terms';
const record=(score=2)=>({score,completedAt:'2026-10-19T00:00:00.000Z'});
const document=(completed={},generation=0)=>({version:1,generation,completed,updatedAt:serverTimestamp()});
const user=name=>env.authenticatedContext(name);
const ref=(ctx,name)=>doc(ctx.firestore(),'academyProgress',name);
before(async()=>{
  env=await initializeTestEnvironment({
    projectId,
    firestore:{host:'127.0.0.1',port:8080,rules:readFileSync(new URL('../firestore.rules',import.meta.url),'utf8')}
  });
});
beforeEach(async()=>env.clearFirestore());
after(async()=>env?.cleanup());

test('owner may write and retrieve only her own completed lessons',async()=>{
  const alice=user('alice');
  await assertSucceeds(setDoc(ref(alice,'alice'),document({[lesson]:record(2)})));
  const snapshot=await assertSucceeds(getDoc(ref(alice,'alice')));
  assert.equal(snapshot.data().completed[lesson].score,2);
  await assertSucceeds(setDoc(ref(alice,'alice'),document({[lesson]:record(3)})));
  assert.equal((await getDoc(ref(alice,'alice'))).data().completed[lesson].score,3);
});

test('another authenticated user cannot read, overwrite, or delete private scores',async()=>{
  const alice=user('alice'),bob=user('bob');
  await assertSucceeds(setDoc(ref(alice,'alice'),document({[lesson]:record()})));
  await assertFails(getDoc(ref(bob,'alice')));
  await assertFails(setDoc(ref(bob,'alice'),document({[lesson]:record(3)})));
  await assertFails(deleteDoc(ref(bob,'alice')));
  await assertFails(getDocs(collection(bob.firestore(),'academyProgress')));
  await assertFails(deleteDoc(ref(alice,'alice')));
});

test('guests cannot access any accounts or create an anonymous record',async()=>{
  const anon=env.unauthenticatedContext();
  await assertFails(getDoc(ref(anon,'alice')));
  await assertFails(setDoc(ref(anon,'alice'),document()));
  await assertFails(getDocs(collection(anon.firestore(),'academyProgress')));
});

test('all other collections are denied even to signed-in users',async()=>{
  const alice=user('alice');
  await assertFails(setDoc(doc(alice.firestore(),'users','alice'),{name:'Craft Maker'}));
  await assertFails(getDoc(doc(alice.firestore(),'users','alice')));
  await assertFails(setDoc(doc(alice.firestore(),'academyProgress','alice','private','test'),{score:3}));
});

test('unknown lessons, forged scores, and unexpected fields are refused',async()=>{
  const alice=user('alice');
  await assertFails(setDoc(ref(alice,'alice'),document({'unknown-paid-tote':record(3)})));
  await assertFails(setDoc(ref(alice,'alice'),document({[lesson]:record(4)})));
  await assertFails(setDoc(ref(alice,'alice'),document({[lesson]:{score:2,secret:'x'}})));
  await assertFails(setDoc(ref(alice,'alice'),{...document(),staffRole:'admin'}));
  await assertFails(setDoc(ref(alice,'alice'),{...document(),updatedAt:new Date()}));
});

test('generation may advance only by one for an empty reset, never retreat or skip',async()=>{
  const alice=user('alice'),own=ref(alice,'alice');
  await assertSucceeds(setDoc(own,document({[lesson]:record(2)},0)));
  await assertFails(setDoc(own,document({},0))); // silent loss is not a reset
  await assertFails(setDoc(own,document({[lesson]:record(3)},1))); // reset cannot preserve points
  await assertFails(setDoc(own,document({},3))); // prevent bypassing generation
  await assertSucceeds(setDoc(own,document({},1))); // intentional account reset
  await assertFails(setDoc(own,document({[lesson]:record(3)},0))); // stale device
  await assertSucceeds(setDoc(own,document({[lesson]:record(2)},1))); // new lesson
  await assertFails(setDoc(own,document({},1))); // cannot silently remove new lesson
  await assertSucceeds(setDoc(own,document({},2))); // another deliberate reset
});

test('new reset marker is supported without an earlier progress document',async()=>{
  const alice=user('alice');
  await assertSucceeds(setDoc(ref(alice,'alice'),document({},1)));
  await assertFails(setDoc(ref(alice,'bob'),document({},1)));
  await assertFails(setDoc(ref(alice,'alice'),document({},0)));
});
