'use client';
import {useEffect,useRef,useState} from 'react';
import Link from 'next/link';
import Image from 'next/image';
import {gradeQuiz,academyQuizzes} from '../lib/academy.mjs';
import {useAcademyProgress} from './useAcademyProgress.jsx';

/** One carefully explained question at a time. No timers, leaderboards or failure penalties. */
export default function AcademyQuiz({lessonId,path}){
 const questions=academyQuizzes[lessonId];
 const {progress,record,storageError}=useAcademyProgress();
 const [step,setStep]=useState(0),[choice,setChoice]=useState(null),[checked,setChecked]=useState(false),[answers,setAnswers]=useState([]),[finalResult,setFinalResult]=useState(null),[focusMessage,setFocusMessage]=useState('');
 const headingRef=useRef(null);
 const question=questions[step];
 useEffect(()=>{if(focusMessage)headingRef.current?.focus()},[focusMessage]);
 const check=()=>{if(choice===null)return;setChecked(true);setFocusMessage('Answer reviewed. '+question.explanation)};
 const next=()=>{
  const nextAnswers=[...answers,choice];
  if(step===questions.length-1){
    const result=gradeQuiz(lessonId,nextAnswers);setFinalResult(result);
    if(result.passed)record(lessonId,result);
    setFocusMessage(result.passed?'Checkpoint complete!':'Practice is progress. You can try again.');
  }else{setAnswers(nextAnswers);setStep(v=>v+1);setChoice(null);setChecked(false);setFocusMessage('Question '+(step+2));}
 };
 const restart=()=>{setStep(0);setChoice(null);setChecked(false);setAnswers([]);setFinalResult(null);setFocusMessage('Question 1');};
 return <section className="academy-quiz" aria-labelledby="quiz-heading" id="knowledge-check">
    <div className="academy-quiz-illustration"><Image src={`/guides/${lessonId}.svg`} width={1200} height={720} alt="Visual reference for this crochet knowledge check" sizes="(max-width:900px) 90vw, 460px"/></div><div className="academy-quiz-top"><p className="academy-overline">YOUR KNOWLEDGE CHECK</p><h2 id="quiz-heading">Make it <em>stick.</em></h2><p>Three friendly questions. Two correct answers mark this lesson complete. You can retry as often as you like.</p></div>
    {finalResult?<div className={'academy-results '+(finalResult.passed?'academy-result-passed':'academy-result-retry')} data-testid="academy-result" role="status"><div className="academy-results-star" aria-hidden="true">{finalResult.perfect?'✺':finalResult.passed?'✳':'❋'}</div><p className="academy-overline">{finalResult.passed?'YOUR KNOWLEDGE IS BLOOMING':'TRY AGAIN WHEN YOU ARE READY'}</p><h3>{finalResult.score}/{finalResult.total} answers right</h3><p>{finalResult.perfect?'Beautiful! A perfect checkpoint adds bonus learning points.':finalResult.passed?'Well done. This lesson is now saved in your personal learning map.':'You are building understanding by practicing. Revisit the guide, then give it another try.'}</p><div className="academy-result-actions"><button type="button" onClick={restart}>Try the quiz again ↺</button><Link href={`/academy/${path.id}`}>Your learning path ↗</Link></div></div>:
    <div className="academy-quiz-card"><div className="academy-quiz-progress"><span>QUESTION {step+1} / {questions.length}</span><div className="academy-linear" aria-hidden="true"><span style={{width:`${(step+1)/questions.length*100}%`}}/></div></div>
      <fieldset className="academy-quiz-fieldset" disabled={checked}><legend ref={headingRef} tabIndex={-1}>{question.prompt}</legend><div className="academy-quiz-options">
        {question.options.map((option,i)=><label key={option} className={'academy-quiz-option '+(choice===i?'is-chosen ':'')+(checked&&question.answer===i?'is-correct ':'')+(checked&&choice===i&&i!==question.answer?'is-incorrect':'')}>
         <input type="radio" name={`${lessonId}-q${step}`} value={i} checked={choice===i} onChange={()=>setChoice(i)} />
         <span className="academy-choice-letter" aria-hidden="true">{String.fromCharCode(65+i)}</span><span>{option}</span>{checked&&i===question.answer?<strong aria-hidden="true">✓</strong>:null}
        </label>)}
      </div></fieldset>
      {checked?<div className={'academy-answer-note '+(choice===question.answer?'is-correct':'is-incorrect')} role="status"><span>{choice===question.answer?'✓ THAT’S RIGHT':'✳ A USEFUL DISCOVERY'}</span><p>{question.explanation}</p></div>:null}
      <div className="academy-quiz-actions">{!checked?<button type="button" className="btn-primary" disabled={choice===null} onClick={check}>Check my answer <span aria-hidden="true">↗</span></button>:<button type="button" className="btn-primary" onClick={next}>{step===questions.length-1?'Finish checkpoint':'Next question'} <span aria-hidden="true">↗</span></button>}
       <span>✳ No timer, no penalty</span></div>
    </div>}
    {storageError?<p className="academy-storage-warning" role="status">{storageError}</p>:null}
  </section>
}
