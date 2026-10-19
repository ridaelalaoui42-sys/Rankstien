/** Portable offline Academy backup. No network, identity, grading override or cloud sync. */
import {ACADEMY_STORAGE_KEY, ACADEMY_VERSION, academyQuizzes, cleanAcademyProgress} from './academy.mjs';

export const ACADEMY_BACKUP_KIND='stitch-atlas-academy-backup';
export const MAX_ACADEMY_BACKUP_BYTES=64*1024;

export function serializeAcademyBackup(progress,now=new Date().toISOString()){
  const data=cleanAcademyProgress(progress);
  return JSON.stringify({
    kind:ACADEMY_BACKUP_KIND,
    schema_version:ACADEMY_VERSION,
    exported_at:now,
    progress:data,
    note:'Offline Stitch Atlas learning checkpoints; not proof of a completed physical crochet project.'
  },null,2);
}

/** Highest-score merge. No remote leaderboard, no claims of verified proficiency. */
export function mergeAcademyScores(a,b){
  const left=cleanAcademyProgress(a),right=cleanAcademyProgress(b);
  const merged={version:ACADEMY_VERSION,completed:{...left.completed}};
  for(const [id,incoming] of Object.entries(right.completed)){
    const old=merged.completed[id];
    if(!old || incoming.score>old.score){
      merged.completed[id]={score:incoming.score,completedAt:old?.completedAt||incoming.completedAt||null};
    }
  }
  return merged;
}

export function mergeAcademyBackup(raw,currentProgress){
  if(typeof raw!=='string'||raw.length>MAX_ACADEMY_BACKUP_BYTES||raw.length===0)
    throw Error('Academy backup must be a nonempty JSON file under 64 KB.');
  let archive;
  try{archive=JSON.parse(raw)}catch{throw Error('This backup is not valid JSON. No scores were changed.')}
  if(!archive||typeof archive!=='object'||Array.isArray(archive)||
    archive.kind!==ACADEMY_BACKUP_KIND||archive.schema_version!==ACADEMY_VERSION)
    throw Error('This is not a supported Stitch Atlas Academy backup.');
  const imported=archive.progress;
  if(!imported||typeof imported!=='object'||Array.isArray(imported)||
    imported.version!==ACADEMY_VERSION||!imported.completed||
    typeof imported.completed!=='object'||Array.isArray(imported.completed))
    throw Error('The backup has invalid progress data.');
  const known=new Set(Object.keys(academyQuizzes));
  const incoming=Object.entries(imported.completed);
  if(incoming.length>known.size)throw Error('The backup contains too many lesson records.');
  for(const [lessonId,record] of incoming){
    if(!known.has(lessonId)||!record||typeof record!=='object'||Array.isArray(record)||
       !Number.isInteger(record.score)||record.score<2||record.score>3||
       (record.completedAt!==null&&record.completedAt!==undefined&&
        (typeof record.completedAt!=='string'||!Number.isFinite(Date.parse(record.completedAt)))))
      throw Error('The backup contains an invalid or unknown lesson record.');
  }
  const safeCurrent=cleanAcademyProgress(currentProgress);
  const safeImported=cleanAcademyProgress(imported);
  const merged={version:ACADEMY_VERSION,completed:{...safeCurrent.completed}};
  for(const [id,record] of Object.entries(safeImported.completed)){
    const old=merged.completed[id];
    if(!old||record.score>old.score){
      merged.completed[id]={score:record.score,completedAt:old?.completedAt||record.completedAt||null};
    }
  }
  return merged;
}
