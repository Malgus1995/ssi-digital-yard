const fs = require('fs'), vm = require('vm'), assert = require('assert');
(async () => {
  const elements = new Map(), timers = [], calls = [];
  let job = null, refreshes = 0, offline = false;
  const element = id => {
    if (!elements.has(id)) elements.set(id, { value: ({milpLimit:'30',metaLimit:'2',runSeed:'42'})[id] || '', parentElement:{} });
    return elements.get(id);
  };
  const context = { document:{getElementById:element}, setTimeout:fn=>timers.push(fn),
    refreshResults:async()=>refreshes++, fetch:async(url,options)=>{
      calls.push({url,options});
      if (offline) return {ok:false,status:404,json:async()=>({})};
      if (options?.method==='POST') {
        if(url.endsWith('/cancel')) job={...job,cancel_requested:true};
        else job={id:'test',directory:'runs/dashboard-jobs/test',revision:0,status:'running',tasks:{},settings:JSON.parse(options.body)};
      }
      return {ok:true,json:async()=>({available:true,job})};
    }
  };
  vm.createContext(context);vm.runInContext(fs.readFileSync('dashboard/runner.js','utf8'),context);
  await new Promise(setImmediate);
  assert.equal(element('runBoth').disabled,false);
  await element('runBoth').onclick();
  assert.equal(job.settings.target,'both');assert.equal(job.settings.milp_seconds,30);
  assert.equal(element('runMilp').disabled,true);assert.equal(element('cancelRun').disabled,false);
  await element('cancelRun').onclick();assert(job.cancel_requested);
  job={...job,status:'succeeded',revision:1,tasks:{milp:{status:'succeeded',elapsed_seconds:3,log:'verified'}}};
  await timers.shift()();assert.equal(refreshes,1);assert.equal(element('runMeta').disabled,false);
  assert(element('runLogs').textContent.includes('verified'));
  offline=true;await timers.shift()();assert.equal(element('runBoth').disabled,true);
  assert(element('runStatus').textContent.includes('serve.py'));
  console.log('Passed run buttons, duplicate disabling, cancellation, completion refresh and offline fallback');
})().catch(error=>{console.error(error);process.exitCode=1});
