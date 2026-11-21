const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements=new Map();function element(){return {value:'',checked:true,style:{},children:[],classList:{toggle(){}},setAttribute(){},getContext(){return {}},getBoundingClientRect(){return {width:1000,height:560}},addEventListener(){},replaceChildren(){this.children=[]},append(x){this.children.push(x)}}}
const context={console,document:{getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id)},createElement:element,createTextNode:t=>({textContent:t})},fetch:async()=>({ok:true,json:async()=>JSON.parse(fs.readFileSync('dashboard/assets/data.json','utf8'))}),ResizeObserver:class{observe(){}},requestAnimationFrame(){},devicePixelRatio:1};
elements.set('map',element());elements.get('map').getContext=()=>({setTransform(){}});vm.createContext(context);vm.runInContext(fs.readFileSync('dashboard/app.js','utf8'),context);
setTimeout(()=>{vm.runInContext(`
if(!D)throw Error('Data did not initialize');
for(const i of [0,1,30,365,dates.length-1]){
setDay(i);
const area=active.reduce((s,[c])=>s+D.blocks[c].length*D.blocks[c].width,0);
const actual=Object.values(occupancy).reduce((s,o)=>s+o.area,0);
if(Math.abs(area-actual)>.0001)throw Error('Area mismatch');
for(const p of placements){const y=nodes[p.yard];if(p.x<y.x-y.width/2-.001||p.x+p.w>y.x+y.width/2+.001||p.y<y.y-y.depth/2-.001||p.y+p.h>y.y+y.depth/2+.001)throw Error('Placement outside yard');}
for(const e of events){const route=path(e.from,e.to);if(route&&(route[0]!==e.from||route.at(-1)!==e.to))throw Error('Invalid route');}
}
setDay(0);tab='yards';renderList();select(yards[0].code);select(events[0].block);
const baseline=slots[0].result;
const originalDate=dates[day], originalCost=D.total_cost;
const alternative=JSON.parse(JSON.stringify(baseline));alternative.total_cost+=123;
const firstCode=Object.keys(alternative.assignment)[0], oldYard=alternative.assignment[firstCode];
const newYard=yards.find(y=>y.code!==oldYard).code;
alternative.assignment[firstCode]=newYard;
for(const es of Object.values(alternative.daily_moves))for(const e of es)if(e.block===firstCode){if(e.action==='입고')e.to=newYard;if(e.action==='출고')e.from=newYard;}
validateResult(alternative);slots[1].result=alternative;activateSlot(1);
if(D.total_cost!==originalCost+123||D.assignment[firstCode]!==newYard||dates[day]!==originalDate)throw Error('Slot switch did not preserve date / use alternative');
if(slots[0].result.assignment[firstCode]!==oldYard)throw Error('Baseline mutated');
activateSlot(0);if(D.total_cost!==originalCost)throw Error('Baseline restore failed');
for(const bad of [{...alternative,total_cost:null},{...alternative,assignment:{bad:'unknown'}},{...alternative,daily_moves:{'2026-02-30':[]}}]){let rejected=false;try{validateResult(bad)}catch{rejected=true}if(!rejected)throw Error('Invalid result accepted');}
const narrow={assignment:{},total_cost:0,daily_moves:{'2026-02-01':[]}};validateResult(narrow);slots[2].result=narrow;activateSlot(2);if(!$('dayinfo').textContent.includes('기간 밖'))throw Error('Missing out-of-range indication');
console.log('Passed date/area/placement/route checks, slot switching, isolation, JSON validation and out-of-range comparison');
`,context)},100);
