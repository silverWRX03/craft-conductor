'use strict';
let catalog=[], runs=[];
const el=id=>document.getElementById(id);
const safe=(tag,txt)=>{const node=document.createElement(tag);node.textContent=String(txt);return node;};
function statusFor(run,id){
  if(!run)return 'not-tested';
  return run.results[String(id)] || 'not-tested';
}
function selectedRun(){return runs.find(r=>r.id===el('run').value)||null;}
function render(){
 const run=selectedRun(), status=el('status').value, sec=el('section').value, search=el('search').value.toLowerCase();
 const counts={pass:0,fail:0,blocked:0,na:0,'not-tested':0};
 const cases=catalog.filter(t=>!run||!run.required_ids.length||run.required_ids.includes(t.id));
 cases.forEach(t=>counts[statusFor(run,t.id)]++);
 const stats=el('stats');stats.replaceChildren();
 for(const [name,key] of [['Passed','pass'],['Failed','fail'],['Blocked','blocked'],['Not tested','not-tested'],['N/A','na']]){
    const box=safe('div','');box.className='card';const number=safe('div',counts[key]);number.className='count '+key;box.append(number,safe('div',name));stats.append(box);
 }
 el('scope-note').textContent=run?`${run.cc_version} · ${run.kind} · ${run.os||'OS not specified'} · ${cases.length} required tests. Prior versions are retained separately.`:`${catalog.length} tests in master catalog`;
 const body=el('tests');body.replaceChildren();
 for(const t of cases){const st=statusFor(run,t.id);
  if(sec && t.section!==sec || status && st!==status || search && !(`${t.id} ${t.section} ${t.step}`.toLowerCase().includes(search)))continue;
  const tr=document.createElement('tr');tr.id='test-'+t.id;
  for(const value of [t.id,t.section,t.step,t.type])tr.append(safe('td',value));
  const cell=safe('td',st.replace('-',' '));cell.className=st;tr.append(cell);body.append(tr);
 }
}
async function start(){
 try{
  const [a,b]=await Promise.all([fetch('data/catalog.json'),fetch('data/runs.json')]);
  if(!a.ok||!b.ok)throw Error('Dashboard data was not published');
  catalog=await a.json();runs=await b.json();
  const s=el('run');s.append(new Option('All catalog tests',''));
  for(const r of [...runs].reverse())s.append(new Option(`${r.cc_version} · ${r.id}`,r.id));
  if(runs.length)s.value=runs[runs.length-1].id;
  for(const sec of [...new Set(catalog.map(x=>x.section))])el('section').append(new Option(sec,sec));
  for(const id of ['run','section','search','status'])el(id).addEventListener(id==='search'?'input':'change',render);
  render();
 }catch(e){el('scope-note').textContent='Unable to load dashboard data: '+e.message;}
}
start();
