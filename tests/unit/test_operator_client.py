import shutil
import subprocess
from pathlib import Path

import pytest


def test_operator_global_metrics_and_stop_control():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for the operator client regression checks")
    source = Path(__file__).resolve().parents[2] / "backend/static/operator/operator.js"
    script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const elements = new Map();
const element = id => {
  if (!elements.has(id)) elements.set(id, {
    id, value:'', dataset:{}, innerHTML:'', textContent:'', hidden:false,
    addEventListener(){}, setAttribute(){}, showModal(){}, close(){},
    insertAdjacentHTML(position,html){this.innerHTML+=html;},
    classList:{add(){},remove(){},toggle(){return false;}},
  });
  return elements.get(id);
};
const calls = [];
const context = vm.createContext({
  document:{getElementById:element,querySelectorAll:()=>[],
    addEventListener(){},documentElement:{dataset:{}}},
  window:{addEventListener(){}}, location:{hash:''},
  localStorage:{getItem(){return null;}},
  setInterval(){},setTimeout(){},clearTimeout(){},
  Date,Map,URL,URLSearchParams,Number,String,Promise,
  testApi:async(path,options)=>{
    calls.push({path,method:options?.method});
    if (path.startsWith('/api/rankstein/pins?')) return {total:101};
    assert.equal(path,'/api/rankstein/control/stop/production');
    return {ok:true,pid:123,stopped:true};
  },
});
// Override startup and networking while executing the actual client functions.
vm.runInContext(fs.readFileSync(process.argv[1],'utf8') + `
function init() {}
async function refreshStatus() {}
async function api(path,options) {return testApi(path,options);}
`, context);
(async()=>{
  vm.runInContext(`state.data={domains:[],runtime:{supervisor:{running:true}},
    actions:{production:{alive:true}},queue:{}};
    state.pinTotal=101; state.pins={total:5}; renderOverview();`,context);
  assert.match(element('metrics').innerHTML,/101/);
  assert.equal(element('stop-batch').disabled,false);
  vm.runInContext('state.data.actions.production.alive=false; renderOverview();',context);
  assert.equal(element('stop-batch').disabled,true);
  await vm.runInContext('refreshPinTotal()',context);
  assert.equal(vm.runInContext('state.pins.total',context),5);
  assert.equal(vm.runInContext('state.pinTotal',context),101);
  vm.runInContext(`openCommand('stop-production')`,context);
  assert.equal(element('batch-fields').hidden,true);
  assert.match(element('command-description').textContent,/queued pins keep running/);
  await vm.runInContext('runCommand({preventDefault(){}})',context);
  assert.equal(calls.filter(c=>c.method==='POST').length,1);
  assert.equal(element('log-mode').value,'production');
  assert.match(element('toast').textContent,/Batch stopped/);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run([node, "-e", script, str(source)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
