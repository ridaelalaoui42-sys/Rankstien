'use client';
import {useMemo,useState} from 'react';

function NumberField({label,value,set,min='0',max='10000',step='1'}){
  return <label>{label}<input type="number" inputMode="decimal" min={min} max={max} step={step}
    value={value} onChange={e=>set(e.target.value)}/></label>;
}

/** Local swatch arithmetic—not a tested pattern or measured yarn requirement. */
export default function AdvancedMakerTools(){
  const [swatchWidth,setSwatchWidth]=useState('10');
  const [swatchHeight,setSwatchHeight]=useState('10');
  const [swatchGrams,setSwatchGrams]=useState('12');
  const [projectWidth,setProjectWidth]=useState('30');
  const [projectHeight,setProjectHeight]=useState('40');
  const [buffer,setBuffer]=useState('10');
  const [multiple,setMultiple]=useState('6');
  const [edge,setEdge]=useState('2');
  const [target,setTarget]=useState('81');
  const yarn=useMemo(()=>{
    const values=[swatchWidth,swatchHeight,swatchGrams,projectWidth,projectHeight,buffer].map(Number);
    if(values.some(v=>!Number.isFinite(v))||values.slice(0,5).some(v=>v<=0||v>10000)||values[5]<0||values[5]>50)return null;
    const [sw,sh,grams,pw,ph,allowance]=values;
    const base=grams*(pw*ph)/(sw*sh);
    if(!Number.isFinite(base)||base>1000000)return null;
    return {base:Math.ceil(base),withBuffer:Math.ceil(base*(1+allowance/100))};
  },[swatchWidth,swatchHeight,swatchGrams,projectWidth,projectHeight,buffer]);
  const repeat=useMemo(()=>{
    const values=[multiple,edge,target].map(Number);
    const [m,e,n]=values;
    if(values.some(v=>!Number.isSafeInteger(v))||m<1||m>1000||e<0||e>1000||n<1||n>100000)return null;
    const repetitions=Math.max(1,Math.floor((n-e)/m));
    const low=e+repetitions*m;
    const high=e+(repetitions+(low<n?1:0))*m;
    return {low,high,exact:n===low,repeatCount:repetitions,belowMinimum:n<e+m};
  },[multiple,edge,target]);
  return <div className="advanced-maker-tools">
    <section className="tool-panel advanced-tool-panel" id="yarn-estimator" aria-labelledby="yarn-title">
      <div><p className="kicker">TOOL 04 · A MEASURED STARTING POINT</p><h2 id="yarn-title">How much yarn?<br/><em>Start with a swatch.</em></h2>
      <p>Use the weight of a <strong>real sample swatch</strong> to estimate yarn grams for a similarly textured rectangular project. Different stitches, shaping and fiber can change consumption substantially.</p>
      <p className="calculator-disclaimer">This is an area-based estimate, not a tested project quantity or a substitute for a pattern’s materials list.</p></div>
      <div className="advanced-tool-form"><div className="calc-form-grid">
        <NumberField label="Swatch width (cm)" min="0.1" step="0.1" value={swatchWidth} set={setSwatchWidth}/>
        <NumberField label="Swatch height (cm)" min="0.1" step="0.1" value={swatchHeight} set={setSwatchHeight}/>
        <NumberField label="Swatch weight (grams)" min="0.1" step="0.1" value={swatchGrams} set={setSwatchGrams}/>
        <NumberField label="Project width (cm)" min="0.1" step="0.1" value={projectWidth} set={setProjectWidth}/>
        <NumberField label="Project height (cm)" min="0.1" step="0.1" value={projectHeight} set={setProjectHeight}/>
        <NumberField label="Extra allowance (%)" min="0" max="50" value={buffer} set={setBuffer}/>
      </div><div className="craft-calc-output" aria-live="polite"><span>ESTIMATED YARN INCLUDING ALLOWANCE</span>
        <output data-testid="yarn-estimate">{yarn?yarn.withBuffer+' g':'—'}</output>
        <small>{yarn?'Approximately '+yarn.base+' g before allowance. Estimate varies with your actual technique.':'Enter positive measurements and a 0–50% allowance.'}</small>
      </div></div></section>
    <section className="tool-panel advanced-tool-panel repeat-panel" id="repeat-planner" aria-labelledby="repeat-title">
      <div><p className="kicker">TOOL 05 · BUILD YOUR FOUNDATION</p><h2 id="repeat-title">Every repeat<br/><em>in its right place.</em></h2>
      <p>For a pattern calling for a multiple of stitches plus edge stitches, find foundation counts close to your target. This is arithmetic guidance—not an endorsement of a particular design or fit.</p></div>
      <div className="advanced-tool-form"><div className="calc-form-grid repeat-fields">
        <NumberField label="Stitches per repeat" min="1" value={multiple} set={setMultiple}/>
        <NumberField label="Extra edge stitches" min="0" value={edge} set={setEdge}/>
        <NumberField label="Your approximate target" min="1" max="100000" value={target} set={setTarget}/>
      </div><div className="craft-calc-output" aria-live="polite"><span>CLOSEST VALID FOUNDATION COUNTS</span>
        <output data-testid="repeat-estimate">{repeat?(repeat.exact?repeat.low+' stitches':(repeat.low===repeat.high?repeat.low+' stitches':repeat.low+' or '+repeat.high+' stitches')):'—'}</output>
        <small>{repeat?(repeat.belowMinimum?'Minimum valid foundation count uses '+repeat.repeatCount+' repeat + '+edge+' edge stitches.':repeat.exact?'Exact match: '+repeat.repeatCount+' repeats + '+edge+' edge stitches.':'Choose based on the pattern shaping and desired size. Nearest count at/below target uses '+repeat.repeatCount+' repeats.'):'Use positive integer repeats and realistic stitch counts.'}</small>
      </div></div></section>
  </div>;
}
