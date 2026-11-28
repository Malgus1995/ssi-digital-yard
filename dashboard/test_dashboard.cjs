const fs = require('fs'), vm = require('vm'), assert = require('assert');
const elements = new Map();
let canvasCalls = 0;
function drawingContext() {
  return new Proxy({}, { get(target, key) {
    if (key === 'measureText') return text => ({ width: String(text).length * 7 });
    if (key in target) return target[key];
    return (...args) => {
      canvasCalls++;
      for (const value of args) if (typeof value === 'number') assert(Number.isFinite(value), `Nonfinite canvas argument: ${key}`);
    };
  } });
}
function element() {
  const context = drawingContext();
  return { value: '', checked: true, hidden: false, width: 164, height: 96,
    style: {}, children: [], textContent: '', classList: { toggle() {} },
    setAttribute() {}, getContext() { return context; },
    getBoundingClientRect() { return { width: 1000, height: 560, left: 0, top: 0 }; },
    addEventListener() {}, setPointerCapture() {},
    replaceChildren() { this.children = []; }, append(...items) { this.children.push(...items); }
  };
}
const html = fs.readFileSync('dashboard/index.html', 'utf8');
const context = {
  console, document: { body: { style: {} }, addEventListener() {},
    getElementById(id) {
      assert(html.includes(`id="${id}"`), `Missing HTML element: ${id}`);
      if (!elements.has(id)) elements.set(id, element());
      return elements.get(id);
    }, createElement: element, createTextNode: text => ({ textContent: text })
  },
  fetch: async () => ({ ok: true, json: async () => JSON.parse(fs.readFileSync('dashboard/assets/data.json', 'utf8')) }),
  ResizeObserver: class { observe() {} }, requestAnimationFrame() {}, devicePixelRatio: 1
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('dashboard/app.js', 'utf8'), context);
setTimeout(()=>{vm.runInContext(`
if(!D || $('error').textContent)throw Error('Data did not initialize: '+$('error').textContent);
$('viewMode').value='blocks';$('speed').value='3000';
for(const id of ['meta','greedy','sa','tabu']){
const slot=slots.find(s=>s.id===id);
if(!slot)throw Error('Missing meta result slot: '+id);
if(!slot.result||!slot.metrics)continue;
const metrics=benchmarkMetrics(slot);
if(!metrics||!metrics.feasibility.valid||!Number.isFinite(metrics.timing.solver_seconds))throw Error('Missing verified benchmark: '+id);
const saved=slot.metrics;slot.metrics={...saved,problem_fingerprint:'different'};
if(benchmarkMetrics(slot))throw Error('Different environment accepted');slot.metrics=saved;
}
for(const row of $('comparisonBody').children)if(row.children.length!==11)throw Error('Comparison column count mismatch');
const initialDate=dates[day],initialCamera={zoom,...offset};
const tabuIndex=slots.findIndex(s=>s.id==='tabu'&&s.result);
if(tabuIndex>=0){
$('algorithm').onchange({target:{value:String(tabuIndex)}});
if(slots[currentSlot].id!=='tabu'||dates[day]!==initialDate||zoom!==initialCamera.zoom||offset.x!==initialCamera.x||offset.y!==initialCamera.y)throw Error('Algorithm selector changed date or camera');
}
activateSlot(0);
for(const i of [0,1,30,100,293,365,600,dates.length-1]){
setDay(i);
const area=active.reduce((s,[c])=>s+D.blocks[c].length*D.blocks[c].width,0);
const actual=Object.values(occupancy).reduce((s,o)=>s+o.area,0);
if(Math.abs(area-actual)>.0001)throw Error('Area mismatch');
for(const p of placements){const y=nodes[p.yard];if(p.x<y.x-y.width/2-.001||p.x+p.w>y.x+y.width/2+.001||p.y<y.y-y.depth/2-.001||p.y+p.h>y.y+y.depth/2+.001)throw Error('Placement outside yard');}
for(let j=0;j<placements.length;j++)for(let k=j+1;k<placements.length;k++){
const a=placements[j],b=placements[k];
if(a.x<b.x+b.w-.00001&&a.x+a.w>b.x+.00001&&a.y<b.y+b.h-.00001&&a.y+a.h>b.y+.00001)throw Error('Block footprints overlap');
}
const count=placements.length+Object.values(occupancy).reduce((s,o)=>s+o.unplaced,0);
if(count!==active.length)throw Error('Unplaced blocks lost from inventory');
dirty=true;draw(1000+i);$('viewMode').value='occupancy';dirty=true;draw(2000+i);$('viewMode').value='blocks';
for(const e of events){const route=path(e.from,e.to);if(route&&(route[0]!==e.from||route.at(-1)!==e.to))throw Error('Invalid route');}
}
setDay(0);tab='yards';renderList();select(yards[0].code);select(events[0].block);
const baseline=slots[0].result;
const originalDate=dates[day], originalCost=D.total_cost, originalZoom=zoom, originalOffset={...offset};
const alternative=JSON.parse(JSON.stringify(baseline));alternative.total_cost+=123;
const firstCode=Object.keys(alternative.assignment)[0], oldYard=alternative.assignment[firstCode];
const newYard=yards.find(y=>y.code!==oldYard).code;
alternative.assignment[firstCode]=newYard;
for(const es of Object.values(alternative.daily_moves))for(const e of es)if(e.block===firstCode){if(e.action==='입고')e.to=newYard;if(e.action==='출고')e.from=newYard;}
validateResult(alternative);slots[1].result=alternative;activateSlot(1);
if(D.total_cost!==originalCost+123||D.assignment[firstCode]!==newYard||dates[day]!==originalDate)throw Error('Slot switch did not preserve date / use alternative');
if(zoom!==originalZoom||offset.x!==originalOffset.x||offset.y!==originalOffset.y)throw Error('Slot switch moved camera');
if(slots[0].result.assignment[firstCode]!==oldYard)throw Error('Baseline mutated');
activateSlot(0);if(D.total_cost!==originalCost)throw Error('Baseline restore failed');
for(const bad of [{...alternative,total_cost:null},{...alternative,assignment:{bad:'unknown'}},{...alternative,daily_moves:{'2026-02-30':[]}}]){let rejected=false;try{validateResult(bad)}catch{rejected=true}if(!rejected)throw Error('Invalid result accepted');}
const narrow={assignment:{},total_cost:0,daily_moves:{'2026-02-01':[]}};validateResult(narrow);slots[2].result=narrow;activateSlot(2);if(!$('dayinfo').textContent.includes('기간 밖'))throw Error('Missing out-of-range indication');
activateSlot(0);setDay(dates.indexOf('2026-10-21'));
const center={x:(W/2-offset.x)/zoom,y:(H/2-offset.y)/zoom};
zoomAt(1.4);
if(Math.abs((W/2-offset.x)/zoom-center.x)>1e-7||Math.abs((H/2-offset.y)/zoom-center.y)>1e-7)throw Error('Zoom anchor moved');
zoomAt(1e12);if(zoom!==16)throw Error('Zoom maximum not clamped');
zoomAt(1e-12);if(zoom!==.035)throw Error('Zoom minimum not clamped');fit();
$('blocksTab').onclick();$('search').value=active[0][0];renderList();
if($('list').children.length!==1)throw Error('Stored block search failed');$('search').value='';
select(active[0][0]);showDetail();if(!$('details').textContent.includes('m²'))throw Error('Missing block area');
const a={x:0,y:0},b={x:100,y:0},c={x:100,y:50};
for(const [t,x,y]of [[0,0,0],[.5,75,0],[1,100,50]]){const p=movePoint([a,b,c],t);if(p.x!==x||p.y!==y)throw Error('Animation is not following route segments');}
// Unequal route lengths must cover equal metres in equal time, including turns.
const shortRoute=[{x:0,y:0},{x:500,y:0}],longRoute=[{x:0,y:0},{x:0,y:100},{x:1900,y:100}];
for(const ms of [100,400,800,1200]){
 const expected=ms/1000*TRANSPORT_METERS_PER_SECOND;
 const shortDistance=transportProgress(shortRoute,ms)*routeLength(shortRoute);
 const longDistance=transportProgress(longRoute,ms)*routeLength(longRoute);
 if(Math.abs(shortDistance-expected)>1e-8||Math.abs(longDistance-expected)>1e-8)throw Error('Unequal transporter speeds');
 const point=movePoint(longRoute,transportProgress(longRoute,ms));
 const covered=point.y+(point.x||0);
 if(Math.abs(covered-expected)>1e-8)throw Error('Speed changed at a route corner');
}
if(transportProgress(shortRoute,10000)!==1)throw Error('Transporter overshot destination');
if(transportProgress([{x:0,y:0},{x:0,y:0}],100)!==1)throw Error('Zero-length trip failed');
setDay(0);setPlaying(true,true);draw(5000);draw(5100);draw(5200);
const pausedElapsed=elapsed;setPlaying(false);draw(5300);
if(elapsed!==pausedElapsed)throw Error('Pause changed vehicle position');
$('speed').value='750';$('speed').onchange();
if(elapsed!==pausedElapsed)throw Error('Speed change teleported vehicles');
setPlaying(true,true);draw(6000);draw(6100);
if(Math.abs(elapsed-400)>1e-8)throw Error('Playback multiplier not shared');
$('speed').value='3000';setPlaying(false);
setDay(0);setPlaying(true);draw(10000);for(let i=1,n=Math.ceil(dayDuration/100)+1;i<=n;i++)draw(10000+i*100);
if(day!==1||!playing)throw Error('Playback did not advance date');
setPlaying(false);setDay(5);setPlaying(true,true);draw(20000);for(let i=1,n=Math.ceil(dayDuration/100)+1;i<=n;i++)draw(20000+i*100);
if(day!==5||playing)throw Error('Day replay did not stop on same date');
setDay(dates.length-1);setPlaying(true);draw(30000);for(let i=1,n=Math.ceil(dayDuration/100)+1;i<=n;i++)draw(30000+i*100);
if(playing||day!==dates.length-1)throw Error('Playback did not stop at end');
setPlaying(false);$('play').onclick();if(day!==0||!playing)throw Error('Replay from final date failed');setPlaying(false);
setDay(0);tab='yards';renderList();toggleExpanded(true);toggleExpanded(false);
console.log('Passed inventory/area, non-overlapping footprints, route animation, both map modes, zoom, search, playback, slots, isolation and JSON validation');
`,context);assert(canvasCalls>1000);console.log('Canvas calls validated:',canvasCalls);},100);
