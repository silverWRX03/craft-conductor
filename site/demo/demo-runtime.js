"use strict";
/* Craft Conductor public demonstration adapter.
   Every /api/ call is handled locally; no real server, account, filesystem, or router is contacted.
   A released production frontend is assembled alongside this adapter at Pages build time. */
(() => {
  const params = new URLSearchParams(location.search);
  const storeKey = "cc-public-demo-state-v1";
  const now = () => Math.floor(Date.now() / 1000);
  const demoMod = (id, name) => ({id,source:"modrinth",key:"modrinth:"+id,name,version:"1.0.0",required:true,deps:[],filename:id+"-1.0.0.jar",status:"installed",channel:"release"});
  const example = () => ({id:"family-survival",name:"Family Survival",motd:"Family Survival",state:"running",loader:"fabric",minecraft:"1.21.1",memory_gb:8,max_players:20,port:25565,mods:[demoMod("fabric-api","Fabric API"),demoMod("lithium","Lithium"),demoMod("terralith","Terralith")],players:["Alex","Mia","KaiCrafts"],known:["Alex","Mia","KaiCrafts","Sam_Builds"],whitelist:["Alex","Mia","KaiCrafts"],requests:[{name:"Sam_Builds",time:now()}],bans:[],ops:["Alex"],backups:[{name:"before-update.tar.gz",size_bytes:158000000,created:now()-86400,kind:"automatic"}],settings:{memory_gb:8,motd:"Family Survival",max_players:20,port:25565},events:[],console:[]});
  const makeState = kind => ({servers:kind==="fresh"?[]:[example()], sequence:0, created:now()});
  let state;
  try {state=JSON.parse(sessionStorage.getItem(storeKey)||"null")}catch{}
  if(!state || params.has("scenario")) state=makeState(params.get("scenario")==="fresh"?"fresh":"example");
  if(!state || !Array.isArray(state.servers))state=makeState("example");
  const save=()=>{try{sessionStorage.setItem(storeKey,JSON.stringify(state))}catch{}};
  save();
  try {if(!localStorage.getItem("craft-conductor-theme")) localStorage.setItem("craft-conductor-theme","night");}catch{}
  function selected(){const m=location.hash.match(/#s\/([^/]+)/);return state.servers.find(x=>x.id===(m&&m[1]))||state.servers[0]||null;}
  const serial=s=>({id:s.id,name:s.name,motd:s.motd,state:s.state,players:s.state==="running"?s.players.length:0,port:s.port,minecraft:s.minecraft,loader:s.loader,setup_pending:false,mods:s.mods.length,join_requests:s.requests.length,update:false,problem:null});
  function hub(){return {version:window.CC_DEMO_VERSION||"demo",single:false,local:false,role:"owner",notice_accepted:true,auth:{default:false,strong:true,managed:true,mode:"password"},guide:{asked:true,active:false},servers:state.servers.map(serial),user:null,access:{},self_update:null,health:[],share:null,device:null,update_result:null};}
  function appendLog(s,message){if(!s)return;s.sequence=(s.sequence||0)+1;s.console.push({seq:s.sequence,text:"["+new Date().toLocaleTimeString("en-GB",{hour12:false})+"] [Server thread/INFO]: "+message});s.events.push({seq:s.sequence,time:now(),level:"info",message});if(s.console.length>300)s.console.shift();if(s.events.length>200)s.events.shift();save();}
  for(const s of state.servers){if(!s.console.length){appendLog(s,"Starting minecraft server version "+s.minecraft);appendLog(s,"Done! For help, type help");s.players.forEach(p=>appendLog(s,p+" joined the game"));}}
  function serverStatus(s){return {id:s.id,motd:s.motd,minecraft:s.minecraft,loader:s.loader,loader_version:"0.16.9",state:s.state,setup_pending:false,job:null,last_job:null,java_major:21,java_forced:null,mods:s.mods.length,port:s.port,players:s.state==="running"?s.players:[],max_players:s.max_players,uptime:s.state==="running"?Math.max(1,now()-state.created):0,auto_upgrade:true,strategy:"compatible",update:{up_to_date:true,latest:s.minecraft,target:null,checked_at:now(),lagging:null},problem:null,disk:{used_bytes:1200000000,total_bytes:10000000000,free_bytes:8800000000},resources:s.state==="running"?{cpu_percent:19,cpus:8,memory_bytes:2450000000,memory_max_bytes:s.memory_gb*1073741824,system_memory_bytes:17179869184}:null};}
  function playersData(s){return {running:s.state==="running",online:s.state==="running"?s.players.slice():[],known:s.known.map(name=>({name})),ops:s.ops.map(name=>({name,level:4})),whitelist:s.whitelist.map(name=>({name})),bans:s.bans.map(name=>({name,reason:"Demo moderation"})),ip_bans:[],whitelist_enabled:true,online_mode:true};}
  function active(s){if(!s)throw Error("No demo server exists. Create one first.");return s;}
  function playersOnline(s){return {players:(s.state==="running"?s.players:[]).map(name=>({name,op:s.ops.includes(name),ping:null,level:s.ops.includes(name)?4:0})),online:s.state==="running"?s.players:[],whitelist:s.whitelist,whitelist_enabled:true,ping:{available:false,reason:"The demo does not connect to a Minecraft server."}};}
  function modData(s){return {minecraft:s.minecraft,loader:s.loader,configured:s.mods.map(m=>({...m})),installed:s.mods.map(m=>({...m})),held:[],unmanaged:[],disabled:[],skipped:[],known_conflicts:[],dependencies:[],changes:[]};}
  function backupData(s){return {backups:s.backups.map(b=>({...b,size:b.size_bytes,date:b.created,mtime:b.created,holds:[],check:null})),scheduled:false,settings:{keep:10,interval_hours:6,world:true,mods:true,configs:true,players:true,webmap:false,secrets:false,logs:false}};}
  function setup(){return {current:null,loaders:[{name:"vanilla",label:"Vanilla",description:"Plain Minecraft without mods.",mods:false},{name:"fabric",label:"Fabric",description:"Lightweight modded servers.",mods:true},{name:"neoforge",label:"NeoForge",description:"Modded Minecraft.",mods:true},{name:"forge",label:"Forge",description:"Classic modded Minecraft.",mods:true},{name:"quilt",label:"Quilt",description:"A Fabric-compatible mod loader.",mods:true},{name:"paper",label:"Paper",description:"Plugins instead of mods.",mods:false},{name:"purpur",label:"Purpur",description:"Paper-compatible plugin server.",mods:false}],versions:["1.21.1","1.21.4","1.21"],betas:[],memory_gb:4,port:25565,network_access:false,network_option:false,properties_schema:[]};}
  function success(message){return {ok:true,message:message||"Done in the demonstration. No real system changes were made."};}
  function process(path,method,body){
    const u=new URL(path,location.origin), full=u.pathname;
    // Server-scoped requests are converted to the same API names as the real single-server mode.
    const scoped=full.match(/^\/api\/servers\/([^/]+)\/(.+)$/);
    const p=scoped?"/api/"+scoped[2]:full;
    const s=scoped?state.servers.find(x=>x.id===scoped[1]):selected();
    const get=method==="GET";
    if(p==="/api/hub"&&get)return hub();
    if(p==="/api/auth"&&get)return {version:"demo",default:false,managed:true,local:true,mode:"password",passkeys:0};
    if(p==="/api/hub/memory")return {total_gb:16,used_gb:state.servers.filter(x=>x.state==="running").reduce((a,x)=>a+x.memory_gb,0),fits:true};
    if(p==="/api/hub/setup"&&get)return setup();
    if(p==="/api/hub/mods/latest"||p==="/api/hub/loaders/latest")return {version:"1.21.4",latest:"1.21.4"};
    if(p.startsWith("/api/hub/mods/")&&get)return {results:[],mods:[],dependencies:[],requires:[],versions:[],ready:true};
    if(p==="/api/hub/create"&&!get){
      const id="demo-"+(state.servers.length+1)+"-"+Date.now().toString(36).slice(-4);
      const newServer=example();Object.assign(newServer,{id,name:body.name||body.motd||"My Minecraft Server",motd:body.motd||"My Minecraft Server",minecraft:body.minecraft==="latest"?"1.21.4":body.minecraft||"1.21.4",loader:body.loader||"vanilla",memory_gb:Number(body.memory_gb)||4,port:body.port||25565,state:"stopped",players:[],known:[],whitelist:[],requests:[],bans:[],ops:[],backups:[],mods:(body.mods||[]).map(x=>demoMod(x,x)),console:[],events:[]});
      state.servers.push(newServer);appendLog(newServer,"Demo server created; press Start when ready");save();return {id};
    }
    if(p==="/api/hub/delete"&&!get){state.servers=state.servers.filter(x=>x.id!==body.id);save();return success("Demo server removed.");}
    if(p==="/api/status"&&get)return serverStatus(active(s));
    if((p==="/api/server/start"||p==="/api/server/stop"||p==="/api/server/restart")&&!get){active(s);if(p.endsWith("start")){s.state="running";appendLog(s,"Server ready");if(s.whitelist.length){s.players=s.whitelist.slice(0,2);s.players.forEach(n=>appendLog(s,n+" joined the game"));}}else if(p.endsWith("stop")){s.state="stopped";s.players=[];appendLog(s,"Saving the world. Server stopped");}else{appendLog(s,"Restarting server");s.state="running";s.players=[];appendLog(s,"Server restarted successfully");}save();return success("Server "+s.state+" (simulated).");}
    if(p==="/api/setup"&&!get){return success("Demo server setup complete.");}
    if(p==="/api/console"&&get){const seq=Number(u.searchParams.get("since")||0);return {lines:active(s).console.filter(x=>x.seq>seq).map(x=>({text:x.text,user:false})),last:s.sequence||0,seq:s.sequence||0};}
    if(p==="/api/events"&&get){const seq=Number(u.searchParams.get("since")||0);return {events:active(s).events.filter(x=>x.seq>seq),last:s.sequence||0};}
    if(p==="/api/command"&&!get){let command=String(body.command||"").trim();if(command==="list")appendLog(s,"There are "+s.players.length+" players online: "+s.players.join(", "));else if(command.startsWith("say "))appendLog(s,"[Server] "+command.slice(4,256));else if(command==="help")appendLog(s,"Commands: help, list, say <message>");else appendLog(s,"Demo command received: "+command.slice(0,180));return success("Command simulated.");}
    if(p==="/api/broadcast"&&!get){appendLog(s,"[Server] "+String(body.message||"").slice(0,256));return success("Message sent to fictional players.");}
    if(p==="/api/players"&&get)return playersData(active(s));
    if(p==="/api/players/online"&&get)return playersOnline(active(s));
    if(p==="/api/join-requests"&&get)return {whitelist_on:true,requests:active(s).requests.slice()};
    if(p==="/api/join-requests/answer"&&!get){s.requests=s.requests.filter(x=>x.name!==body.name);if(body.allow){if(!s.whitelist.includes(body.name))s.whitelist.push(body.name);appendLog(s,body.name+" was added to the whitelist");}save();return success(body.allow?"Added to whitelist.":"Request ignored.");}
    if(p==="/api/players/action"&&!get){const a=body.action,n=String(body.name||"");if(a==="whitelist-add"&&!s.whitelist.includes(n))s.whitelist.push(n);if(a==="whitelist-remove")s.whitelist=s.whitelist.filter(x=>x!==n);if(a==="kick"){s.players=s.players.filter(x=>x!==n);appendLog(s,n+" left the game (kicked)");}if(a==="ban"){s.players=s.players.filter(x=>x!==n);if(!s.bans.includes(n))s.bans.push(n);}if(a==="pardon")s.bans=s.bans.filter(x=>x!==n);if(a==="op"&&!s.ops.includes(n))s.ops.push(n);if(a==="deop")s.ops=s.ops.filter(x=>x!==n);save();return success("Player action simulated: "+a);}
    if(p==="/api/players/activity"&&get)return {players:[],week:Array.from({length:7},()=>Array(24).fill(0)),days:Number(u.searchParams.get("days")||7)};
    if(p==="/api/mods"&&get)return modData(active(s));
    if(p==="/api/mods/search"&&get){const q=(u.searchParams.get("q")||"").toLowerCase();const all=[demoMod("fabric-api","Fabric API"),demoMod("sodium","Sodium"),demoMod("lithium","Lithium"),demoMod("terralith","Terralith"),demoMod("biomes-o-plenty","Biomes O' Plenty"),demoMod("glitchcore","GlitchCore")];return {results:all.filter(x=>x.name.toLowerCase().includes(q)||x.id.includes(q))};}
    if(p==="/api/mods/add"&&!get){const m=demoMod(body.id||"sample-mod",body.id||"Sample Mod");if(!s.mods.some(x=>x.id===m.id))s.mods.push(m);save();return success("Mod added to demo.");}
    if(p==="/api/mods/remove"&&!get){s.mods=s.mods.filter(x=>x.id!==body.id);save();return success("Mod removed from demo.");}
    if(p==="/api/mods/required"&&!get){const m=s.mods.find(x=>x.id===body.id);if(m)m.required=!!body.required;save();return success("Mod setting updated.");}
    if(p==="/api/mods/versions"&&get)return {versions:[],results:[]};
    if(p==="/api/configs"&&get)return {mods:[]};
    if(p==="/api/modsets"&&get)return {sets:[]};
    if(p==="/api/updates"&&get)return {status:serverStatus(active(s)),update:{up_to_date:true,latest:s.minecraft,target:null},candidate:null,latest:s.minecraft,changes:[],blocked:[],dropped:[],manual:[],installed:s.minecraft,available:[]};
    if(p==="/api/updates/check"&&!get){appendLog(s,"Checking Minecraft and mod updates");return success("Demo compatibility check complete.");}
    if(p==="/api/updates/rehearsal"&&get)return {report:null,rehearsal:null};
    if(p==="/api/backups"&&get)return backupData(active(s));
    if(p==="/api/backups/create"&&!get){let name="demo-backup-"+Date.now()+".tar.gz";s.backups.unshift({name,size_bytes:140000000,created:now(),kind:"manual"});appendLog(s,"Backup completed: "+name);return success("Demo backup created.");}
    if(p==="/api/backups/restore"&&!get){appendLog(s,"Demo backup restored: "+body.name);return success("Simulated backup restored.");}
    if(p==="/api/backups/changes"&&get)return {changes:[],diff:[],safe:true};
    if(p==="/api/settings"&&get)return {memory_gb:s.memory_gb,motd:s.motd,max_players:s.max_players,port:s.port,loader:s.loader,minecraft:s.minecraft,properties:[],schedule_restart:"",auto_upgrade:true,save_settings:{},backup_keep:10};
    if(p==="/api/settings"&&!get){Object.assign(s,body);save();return success("Demo settings saved.");}
    if(p==="/api/java"&&get)return {major:21,needed:21,used:21,current:{major:21,source:"download",wanted:21},shared:[],installed:[],java:[],choices:[],available:[]};
    if(p==="/api/performance"&&get)return {tps:20,mspt:32,history:[],lagging:false,can_profile:false};
    if(p==="/api/performance/lag"&&get)return {running:false,report:null};
    if(p==="/api/doctor"&&get)return {checks:[],problems:[],actions:[]};
    if(p==="/api/doctor/internet"&&get)return {checks:[]};
    if(p==="/api/webmap"&&get)return {url:null,enabled:false};
    if(p==="/api/tunnel"&&get)return {running:false,available:false};
    if(p==="/api/play-here"&&get)return {available:false};
    if(p==="/api/hub/singleplayer"&&get)return {games:[]};
    if(p==="/api/hub/saves"&&get)return {worlds:[]};
    if(p==="/api/hub/guide"&&get)return {asked:true,active:false,steps:[],next:null};
    if(p==="/api/hub/passkeys"&&get)return {passkeys:[],allowed:false};
    if(p==="/api/hub/phone"&&get)return {devices:[],strong:true,addresses:[]};
    if(p==="/api/hub/firewall-rules"&&get)return {rules:[]};
    if(p==="/api/hub/discord"&&get)return {set:false};
    if(p==="/api/hub/curseforge"&&get)return {set:false};
    if(p==="/api/hub/users"&&get)return {people:[],servers:state.servers.map(serial),addresses:[],catalog:{presets:[],groups:[],implies:{}}};
    if(p==="/api/account"&&get)return {passkeys:[],devices:[],allowed:false};
    if(p==="/api/client"&&get)return {enabled:false,players_mods:[],links:[],mods:[],local:[]};
    if(p==="/api/hub/self-update"&&get)return {version:"demo",phase:"none"};
    if(p==="/api/hub"&&!get)return success();
    if(get)throw Error("This screen requires a demo API fixture not yet implemented: "+p);
    throw Error("Demo-only action: "+p+" does not modify a real computer.");
  }
  const nativeFetch=window.fetch.bind(window);
  window.fetch=async (input,init={})=>{
    const target=typeof input==="string"?input:input.url;const url=new URL(target,location.href);
    const method=(init.method||(typeof input!=="string"&&input.method)||"GET").toUpperCase();
    if(url.pathname.startsWith("/api/")){
      let body={};try{body=JSON.parse(init.body||"{}")}catch{}
      try{const result=process(url.href,method,body);return new Response(JSON.stringify(result),{status:200,headers:{"Content-Type":"application/json"}});}
      catch(e){console.warn("[Craft Conductor demo]",e.message);return new Response(JSON.stringify({error:e.message}),{status:422,headers:{"Content-Type":"application/json"}});}
    }
    if(url.origin!==location.origin)return new Response("External fetch disabled in public demonstration",{status:403});
    // Production assets sometimes use /i18n/...; never fetch a path outside this demo.
    const base="/craft-conductor/demo/";
    if(!url.pathname.startsWith(base)){url.pathname=base+url.pathname.replace(/^\/+/,"");return nativeFetch(url.href,init);}
    return nativeFetch(input,init);
  };
  const NativeXHR=window.XMLHttpRequest;
  window.XMLHttpRequest=class SafeDemoXHR extends NativeXHR{
    open(method,url,...rest){const p=new URL(url,location.href);if(p.pathname.startsWith("/api/")){this._blockedDemo=true;return;}super.open(method,url,...rest);}
    send(body){if(this._blockedDemo){queueMicrotask(()=>this.dispatchEvent(new Event("error")));return;}return super.send(body);}
    setRequestHeader(...args){if(!this._blockedDemo)super.setRequestHeader(...args);}
  };
  function addJoinRequest(){const s=selected();if(!s||s.state!=="running")return;const names=["Sam_Builds","Robin","TaylorMC","BlockBuilder"];const name=names.find(x=>!s.requests.some(r=>r.name===x)&&!s.whitelist.includes(x));if(!name)return;s.requests.push({name,time:now()});appendLog(s,name+" requested whitelist access");}
  // Inject a distinct demo toolbar, outside the application UI. Never make it appear part of a real CC installation.
  document.addEventListener("DOMContentLoaded",()=>{
    const toolbar=document.createElement("aside");toolbar.className="demo-toolbar";toolbar.setAttribute("aria-label","Demonstration controls");
    const make=(txt,cb)=>{const b=document.createElement("button");b.type="button";b.textContent=txt;b.addEventListener("click",cb);toolbar.append(b);return b;};
    const label=document.createElement("span");label.textContent="DEMO MODE · Fictional data";toolbar.append(label);
    make("Fake join request",()=>{addJoinRequest();alert("A fictional player requested whitelist access. Open Players or Dashboard.");});
    make("Reset demo",()=>{sessionStorage.removeItem(storeKey);location.replace(location.pathname+"?scenario=example");});
    make("Phone / QR",()=>{
      let panel=document.getElementById("demo-phone-panel");
      if(panel){panel.remove();return;}
      panel=document.createElement("div");panel.id="demo-phone-panel";panel.className="demo-phone-panel";
      const url=new URL("?",location.href);url.search="?scenario=example&phone=1";url.hash="";
      const h=document.createElement("h3");h.textContent="Craft Conductor mobile demo";panel.append(h);
      const p=document.createElement("p");p.textContent="Click the QR code to open a phone-sized preview, or scan it on a separate device.";panel.append(p);
      const a=document.createElement("a");a.href=url.href;a.target="_blank";a.rel="noopener noreferrer";a.addEventListener("click",e=>{if(window.parent!==window){e.preventDefault();window.parent.postMessage({type:"cc-demo-open-mobile"},location.origin);}});
      const im=document.createElement("img");im.src="phone-qr.svg";im.alt="QR code opening the standalone mobile Craft Conductor demo";a.append(im);panel.append(a);
      const close=document.createElement("button");close.textContent="Close";close.addEventListener("click",()=>panel.remove());panel.append(close);document.body.append(panel);
    });
    document.body.append(toolbar);
    if(params.get("phone")==="1")document.documentElement.classList.add("demo-phone");
    if(params.get("scenario")==="example"&&state.servers.length)location.hash="#s/"+state.servers[0].id+"/dashboard";
    if(params.get("scenario")==="fresh")location.hash="#new";
  });
  window.addEventListener("message",()=>{});
  window.CC_DEMO_TEST={hub,process,state,selected,addJoinRequest};
})();