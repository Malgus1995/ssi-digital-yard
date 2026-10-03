import http from 'node:http';
import {readFile, readdir, stat} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
const here=path.dirname(fileURLToPath(import.meta.url)), root=path.dirname(here);
const execute=promisify(execFile), pending=new Map();
async function exists(p){try{return (await stat(p)).isFile()}catch{return false}}
async function runs(){
 const found=[];
 for(const entry of await readdir(path.join(root,'runs'),{withFileTypes:true}).catch(()=>[])){
  if(!entry.isDirectory())continue;
  for(const method of ['or','sa','rl']){
   const dir=path.join(root,'runs',entry.name,method);
   if(await exists(path.join(dir,'optimized_assignments.csv')) && await exists(path.join(dir,'daily_yard_utilization.csv')))
    found.push({id:`${entry.name}/${method}`,label:`${entry.name} · ${method.toUpperCase()}`,dir});
  }
 }
 const dir=path.join(root,'data','solution');
 if(await exists(path.join(dir,'optimized_assignments.csv')) && await exists(path.join(dir,'daily_yard_utilization.csv')))found.push({id:'data/solution',label:'기본 솔버 결과',dir});
 return found.sort((a,b)=>b.id.localeCompare(a.id));
}
async function prepare(run){
 if(await exists(path.join(run.dir,'snapshots','index.json')))return;
 if(!pending.has(run.id))pending.set(run.id,(async()=>{
  let nodes=path.join(root,'data','적치장 노드 정보.csv');
  try {const metadata=JSON.parse(await readFile(path.join(run.dir,'..','run_metadata.json'),'utf8'));nodes=metadata.inputs.nodes;}catch{}
  const python=await exists(path.join(root,'.venv','bin','python'))?path.join(root,'.venv','bin','python'):'python3';
  await execute(python,['-m','experiment.snapshots','--output-dir',run.dir,'--nodes',nodes],{cwd:root});
 })().finally(()=>pending.delete(run.id)));
 await pending.get(run.id);
}
const server=http.createServer(async(req,res)=>{
 try{
  if(req.method!=='GET'){res.writeHead(405);res.end();return}
  const url=new URL(req.url,'http://localhost');
  if(url.pathname==='/api/runs'){
   res.setHeader('Content-Type','application/json');res.end(JSON.stringify((await runs()).map(({id,label})=>({id,label}))));return;
  }
  if(url.pathname==='/api/index'||url.pathname==='/api/day'){
   const run=(await runs()).find(r=>r.id===url.searchParams.get('run'));
   if(!run){res.writeHead(404);res.end('Unknown run');return}
   await prepare(run);
   const day=url.searchParams.get('date');
   if(url.pathname==='/api/day'&&!/^\d{4}-\d{2}-\d{2}$/.test(day||'')){res.writeHead(400);res.end('Invalid date');return}
   const file=url.pathname==='/api/index'?'index.json':`${day}.json`;
   res.setHeader('Content-Type','application/json');res.end(await readFile(path.join(run.dir,'snapshots',file)));return;
  }
  const files={'/':'index.html','/app.js':'app.js','/style.css':'style.css'};
  const file=files[url.pathname];if(!file){res.writeHead(404);res.end();return}
  res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');
  res.end(await readFile(path.join(here,'public',file)));
 }catch(error){res.writeHead(500,{'Content-Type':'application/json'});res.end(JSON.stringify({error:error.message}));}
});
server.listen(Number(process.env.PORT||3000),'127.0.0.1',()=>console.log(`Yard viewer: http://localhost:${server.address().port}`));
