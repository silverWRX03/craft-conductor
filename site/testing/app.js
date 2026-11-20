'use strict';
let catalog=[], runs=[], latest={};
const ALL='all-results';  // the "All Tests Completed" view: every test's latest result from any run
const el=id=>document.getElementById(id);
const safe=(tag,txt)=>{const node=document.createElement(tag);node.textContent=String(txt);return node;};
const version=r=>(String(r.cc_version).match(/^\d+(\.\d+)*/)||[r.cc_version])[0];
// Each test's newest result and the newest version it passed in (runs.json is oldest first). A run that
// lists a test without trying it ("not tested") doesn't hide an older result, and neither does N/A after a
// pass (a later run that didn't rerun a test that had passed).
function collect(){
 latest={};
 for(const r of runs)for(const [id,st] of Object.entries(r.results)){
  if(st==='not-tested'||st==='na'&&latest[id]&&latest[id].passed)continue;
  const t=latest[id]||(latest[id]={status:st,passed:''});
  t.status=st;if(st==='pass')t.passed=version(r);
 }
}
// N/A means the test will not be run (out of date, or hardware the owner doesn't have): its row is struck
// through and it isn't counted anywhere. The catalog view has no run, so it uses each test's newest result.
function statusFor(run,id){
  if(run===ALL)return (latest[String(id)]||{}).status||'not-tested';
  if(!run)return (latest[String(id)]||{}).status==='na'?'na':'not-tested';
  return run.results[String(id)] || 'not-tested';
}
function selectedRun(){return el('run').value===ALL?ALL:runs.find(r=>r.id===el('run').value)||null;}
function render(){
 const run=selectedRun(), all=run===ALL, status=el('status').value, sec=el('section').value, search=el('search').value.toLowerCase();
 const counts={pass:0,fail:0,blocked:0,na:0,'not-tested':0};
 const cases=catalog.filter(t=>!run||all||!run.required_ids.length||run.required_ids.includes(t.id));
 cases.forEach(t=>counts[statusFor(run,t.id)]++);
 const counted=cases.length-counts.na, skipped=counts.na?` ${counts.na} N/A tests (struck through) will not be run and aren't counted.`:'';
 el('validated-head').hidden=!all;
 const stats=el('stats');stats.replaceChildren();
 for(const [name,key] of [['Passed','pass'],['Failed','fail'],['Blocked','blocked'],['Not tested','not-tested']]){
    const box=safe('div','');box.className='card';const number=safe('div',counts[key]);number.className='count '+key;box.append(number,safe('div',name));stats.append(box);
 }
 el('scope-note').textContent=all?`Every test's latest result from all ${runs.length} test runs, and the newest version it passed in. ${counts['not-tested']} of ${counted} tests have never been tried.${skipped}`
  :run?`${run.cc_version} · ${run.kind} · ${run.os||'OS not specified'} · ${counted} required tests. Prior versions are retained separately.${skipped}`:`${counted} tests in master catalog.${skipped}`;
 const body=el('tests');body.replaceChildren();
 for(const t of cases){const st=statusFor(run,t.id);
  if(sec && t.section!==sec || status && st!==status || search && !(`${t.id} ${t.section} ${t.step}`.toLowerCase().includes(search)))continue;
  const tr=document.createElement('tr');tr.id='test-'+t.id;if(st==='na')tr.className='na';
  for(const value of [t.id,t.section,t.step,t.type])tr.append(safe('td',value));
  const cell=safe('td',st==='na'?'N/A':st.replace('-',' '));cell.className='status '+st;tr.append(cell);
  if(all){const v=safe('td',(latest[String(t.id)]||{}).passed||'—');v.className='validated';tr.append(v);}
  body.append(tr);
 }
}
async function start(){
 try{
  const [a,b]=await Promise.all([fetch('data/catalog.json'),fetch('data/runs.json')]);
  if(!a.ok||!b.ok)throw Error('Dashboard data was not published');
  catalog=await a.json();runs=await b.json();collect();
  const s=el('run');s.append(new Option('All Tests Completed',ALL),new Option('All catalog tests',''));
  for(const r of [...runs].reverse())s.append(new Option(`${r.cc_version} · ${r.id}`,r.id));
  if(runs.length)s.value=runs[runs.length-1].id;
  for(const sec of [...new Set(catalog.map(x=>x.section))])el('section').append(new Option(sec,sec));
  for(const id of ['run','section','search','status'])el(id).addEventListener(id==='search'?'input':'change',render);
  render();
 }catch(e){el('scope-note').textContent='Unable to load dashboard data: '+e.message;}
}
start();
