"use strict";
/* Public website demo adapter. Executes BEFORE the authentic Craft Conductor frontend.
 * Network policy: API calls are handled here, never sent to a Minecraft control panel.
 * Browser state is stored only in this origin's sessionStorage and scoped to the demo.
 */
(function () {
  const search = new URLSearchParams(location.search);
  const mode = search.get("mode") === "new" ? "new" : "existing";
  const KEY = "cc-public-demo-state-v2";
  const version = "demo";
  const tick = () => Math.floor(Date.now() / 1000);
  const names = ["Alex", "Mia", "KaiCrafts", "Sam_Builds", "JordanMC"];
  function fixtureServer() {
    return { id: "family-survival", name: "Family Survival", motd: "Family Survival",
      state: "running", minecraft: "1.21.1", loader: "fabric", port: 25565,
      max_players: 20, folder: "[DEMO] /servers/family-survival", memory: "4G",
      online: ["Alex", "Mia", "KaiCrafts"], known: names.slice(0, 4),
      whitelist: ["Alex", "Mia", "KaiCrafts"], whitelist_enabled: true,
      bans: [], ops: ["Alex"], requests: ["Sam_Builds"],
      mods: [{key:"modrinth:fabric-api",name:"Fabric API",version:"0.107.0",required:true},
        {key:"modrinth:lithium",name:"Lithium",version:"0.14.3",required:false}],
      backups: [], update: null, settings: {}, log: [], events: [] };
  }
  function initial() {
    const s = { version: 2, servers: mode === "new" ? [] : [fixtureServer()],
      games: [], selected: mode, guide: false, created: tick() };
    if (s.servers.length) {
      const f = s.servers[0];
      log(f, "Done (6.482s)! For help, type \"help\"");
      log(f, "Alex joined the game");
      log(f, "Mia joined the game");
      log(f, "KaiCrafts joined the game");
      log(f, "Sam_Builds requested whitelist access");
    }
    return s;
  }
  let state;
  try { state = JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch {}
  if (!state || state.version !== 2 || state.selected !== mode) state = initial();
  function persist() { try { sessionStorage.setItem(KEY, JSON.stringify(state)); } catch {} }
  function log(s, message, level = "info") {
    const t = tick();
    const line = "[" + new Date().toLocaleTimeString("en-GB",{hour12:false}) + "] [Server/INFO]: " + message;
    s.log.push({ seq: s.log.length + 1, text: line, user: false });
    s.events.push({ seq: s.events.length + 1, level, time: t, message });
    if (s.log.length > 300) s.log.splice(0,s.log.length-300);
    if (s.events.length > 300) s.events.splice(0,s.events.length-300);
  }
  function serverFrom(path) {
    const match = path.match(/^\/api\/servers\/([a-z0-9-]+)(\/.*)?$/);
    const id = match ? match[1] : ((location.hash.match(/^#s\/([^/]+)/) || [])[1]);
    const found = state.servers.find(s => s.id === id);
    return { s: found || state.servers[0] || null, path: match ? "/api" + (match[2] || "/") : path };
  }
  const previewHub = () => ({
    version, local:false, single:false, role:"owner", notice_accepted:true,
    auth:{default:false,managed:false}, self_update:null, health:[],
    guide:{active:false,asked:true,steps:[]}, memory_gb:16, servers:state.servers.map(s=>({
      id:s.id,name:s.name,motd:s.motd,state:s.state,setup_pending:false,
      loader:s.loader,minecraft:s.minecraft,port:s.port,folder:s.folder,
      players:s.state==="running"?s.online.length:0,max_players:s.max_players,
      join_requests:s.requests.length,job:null,update:s.update,problem:null
    }))
  });
  function describe(s) {
    return { id:s.id,motd:s.motd,minecraft:s.minecraft,loader:s.loader,port:s.port,
      state:s.state,players:s.state==="running"?s.online.slice():[],
      max_players:s.max_players,online:s.state==="running"?s.online:[],
      cpu_percent:s.state==="running"?24:0,memory_used_gb:s.state==="running"?2.8:0,
      memory_gb:4,uptime:s.state==="running"?620:0,setup_pending:false,
      memory:"4G",job:null,update:s.update,mods:s.mods.length,problem:null,
      strategy:"latest-compatible",disk:{used_bytes:9019431322,total_bytes:107374182400,free_bytes:98354751078},
      runtime:{java:"21",memory:"4G",port:s.port,loader:s.loader},
      health:[],java_major:21,resources:s.state==="running"?{cpu_percent:24,cpus:8,memory_bytes:3006477107,memory_max_bytes:4294967296,system_memory_bytes:17179869184}:null,memory_percent:s.state==="running"?62:0
    };
  }
  function players(s) {
    return {running:s.state==="running",online:s.state==="running"?s.online:[],
      known:s.known.map(name=>({name})),ops:s.ops.map(name=>({name,level:4})),
      whitelist:s.whitelist.map(name=>({name})),bans:s.bans.map(name=>({name,reason:"Demo"})),
      ip_bans:[],whitelist_enabled:s.whitelist_enabled,online_mode:true,
      max_players:s.max_players};
  }
  function offlineOnline(s) {
    return {players:(s.state==="running"?s.online:[]).map(name=>({
      name,op:s.ops.includes(name),op_level:4,ping_ms:null
    })),whitelist:s.whitelist.slice(),whitelist_enabled:s.whitelist_enabled,
    ping:{available:false,reason:"Ping is not reported by this Minecraft server."}};
  }
  function settings(s) {
    return Object.assign({
      strategy:"latest-compatible",mod_channel:"release",check_interval:"6h",
      warn_minutes:[5,1],auto_upgrade:true,wait_for_empty:true,
      minecraft:s.minecraft,memory:s.memory,port:s.port,motd:s.motd,
      name:s.name,backups_keep:10,backup_include:["world","mods","config","players"],
      backup_copy_to:"",backup_copy_keep:10,properties:{},
      properties_schema:[],schedule_restart:"",aikar_flags:false,
      choices:{strategy:["latest-compatible","latest","mods-only"],mod_channel:["release","beta","alpha"]}
    },s.settings);
  }
  function setupFixture() {
    return { loaders:[
      {name:"fabric",label:"Fabric"},{name:"neoforge",label:"NeoForge"},
      {name:"forge",label:"Forge"},{name:"quilt",label:"Quilt"},
      {name:"paper",label:"Paper"},{name:"purpur",label:"Purpur"},
      {name:"vanilla",label:"Vanilla"}],
      versions:["1.21.1","1.21.4","1.21"],betas:[],memory_gb:4,network_access:false,
      port:25566,properties_schema:[],current:null,newest:"1.21.4",
      network_option:false};
  }
  function sampleMod(name, key) {
    return {name,slug:key.split(":").pop(),key,downloads:11200000,description:"Community mod in the offline demonstration catalog.",channel:"release",environment:"both",icon:null,version:"1.0.0",
      required:false,source:"modrinth",filename:name.toLowerCase().replaceAll(" ","-")+".jar",
      project:key,build:"release",type:"release"};
  }
  function mods(s) {
    return {minecraft:s.minecraft,loader:s.loader,plugins:false,
      configured:s.mods.map(m=>({ ...sampleMod(m.name,m.key), ...m,id:m.key.split(":").pop(),slug:m.key.split(":").pop(),deps:[]})),
      installed:s.mods.map(m=>({name:m.name,key:m.key,source:"modrinth",version:m.version,filename:m.key.split(":").pop()+".jar"})),
      players_mods:[],held:{},available:[],pending:[],updates:[],local:[],unmanaged:[],disabled:[],skipped:[],known_conflicts:[],summary:null
    };
  }
  function client(s) {return {enabled:false,link_days:7,link_day_choices:[1,7,30,0],
    mods:[],local_mods:[],held:{},pack:null,links:{},downloads:[],
    local_link:"",internet_link:"",port:8766,server:s.id};}
  function join(s) {
    return {whitelist_on:s.whitelist_enabled,requests:s.requests.map((name,i)=>({id:"req-"+i,name,minecraft_name:name,created:tick()-60,ip:"demo",time:tick()-60})),count:s.requests.length};
  }
  function handle(method, rawPath, body) {
    const parts = serverFrom(rawPath);const p = parts.path,s = parts.s;
    if (p==="/api/hub") return previewHub();
    if (p==="/api/auth") return {version,default:false,local:true,mode:"password",managed:false};
    if (p==="/api/notice") return {accepted:true};
    if (p==="/api/hub/guide") return {active:false,asked:true,steps:[]};
    if (p==="/api/hub/memory") return {fits:true,total_gb:16,running_gb:state.servers.filter(x=>x.state==="running").length*4};
    if (p==="/api/hub/setup") return setupFixture();
    if (p==="/api/hub/setup/newest") return {minecraft:"1.21.4"};
    if (p==="/api/hub/port") return {free:true,available:true};
    if (p==="/api/hub/singleplayer") return {games:state.games};
    if (p==="/api/hub/remote") return {enabled:false,local:true};
    if (p==="/api/hub/phone" || p==="/api/hub/phone?tailscale=1")
      return {devices:[],strong:true,enabled:false};
    if (p==="/api/hub/phone/prefs") return {enabled:false};
    if (p.startsWith("/api/hub/firewall-rules")) return {rules:[]};
    if (p==="/api/hub/firewall/remove") return {message:"Demo only: no firewall rules were changed."};
    if (p==="/api/hub/curseforge") return {set:false,available:false};
    if (p==="/api/hub/discord") return {set:false};
    if (p==="/api/hub/users") return {users:[],invite:null};
    if (p==="/api/hub/conflicts") return {enabled:false,reports:[]};
    if (p==="/api/hub/share") return {address:"",port:8766};
    if (p==="/api/hub/network") return {enabled:false};
    if (p==="/api/hub/self-update" || p==="/api/self-update/check") return {self_update:null,version};
    if (p==="/api/hub/create" && method==="POST") {
      const id = "server-"+(state.servers.length+1);
      const n = String(body.name||body.motd||"New Survival Server").slice(0,48);
      const chosen = fixtureServer();
      chosen.id=id;chosen.name=n;chosen.motd=n;chosen.state="stopped";
      chosen.minecraft=body.minecraft==="latest"?"1.21.4":body.minecraft||"1.21.4";
      chosen.loader=body.loader||"fabric";chosen.online=[];chosen.known=[];chosen.whitelist=[];
      chosen.ops=[];chosen.bans=[];chosen.requests=[];chosen.mods=[];
      chosen.port=body.port||25566;chosen.folder="[DEMO] /servers/"+id;
      state.servers.push(chosen);log(chosen,"Created "+chosen.name+" (simulation only).");
      return {id,ok:true};
    }
    if (p==="/api/hub/delete" && method==="POST") {
      const id=body.id;state.servers=state.servers.filter(x=>x.id!==id);
      return {message:"Removed example server from this browser only."};
    }
    if (p==="/api/hub/singleplayer/delete" && method==="POST") {
      state.games=state.games.filter(g=>g.id!==body.id);return {message:"Removed demo game."};
    }
    if (p==="/api/hub/singleplayer" && method==="POST") {
      const game={...body,id:"demo-game-"+Date.now()};
      state.games.push(game);return {id:game.id};
    }

    if (/^\/api\/(?:hub\/)?browse\/(categories|search|project)/.test(p)) {
      const kind = p.includes("categories") ? "categories" : p.includes("search") ? "search" : "project";
      const q = new URLSearchParams(p.split("?")[1]||"");
      if (kind==="categories") return {categories:[{id:"adventure",name:"Adventure"},{id:"optimization",name:"Optimization"},{id:"utility",name:"Utility"}]};
      const base=[
        {id:"fabric-api",slug:"fabric-api",name:"Fabric API",summary:"Essential APIs for Fabric mods",channel:"release",environment:"both",downloads:240000000,source:"modrinth",author:"modmuss50"},
        {id:"lithium",slug:"lithium",name:"Lithium",summary:"Server performance optimization",channel:"release",environment:"server",downloads:90000000,source:"modrinth",author:"CaffeineMC"},
        {id:"terralith",slug:"terralith",name:"Terralith",summary:"New biomes and exploration",channel:"release",environment:"both",downloads:50000000,source:"modrinth",author:"Stardust Labs"},
        {id:"simple-voice-chat",slug:"simple-voice-chat",name:"Simple Voice Chat",summary:"Talk to players nearby",channel:"release",environment:"both",downloads:60000000,source:"modrinth",author:"henkelmax"},
        {id:"biomes-o-plenty",slug:"biomes-o-plenty",name:"Biomes O' Plenty",summary:"More biomes for adventures; requires GlitchCore on NeoForge",channel:"release",environment:"both",downloads:67000000,source:"modrinth",author:"Forstride"}
      ];
      const projects=q.get("type")==="modpack"
        ? [{id:"family-exploration",slug:"family-exploration",name:"Family Exploration (Demo Pack)",summary:"Fictional example pack for exploring the demo",source:"modrinth",channel:"release",downloads:12000,environment:"both"}]
        : base;
      if(kind==="search"){
        const term=(q.get("q")||"").toLowerCase();
        const filtered=projects.filter(x=>!term||x.name.toLowerCase().includes(term)||x.summary.toLowerCase().includes(term));
        return {results:filtered,hidden:0,early_hidden:0,next:null};
      }
      const found=projects.find(x=>x.id===q.get("id"))||base.find(x=>x.id===q.get("id"))||projects[0];
      return {...found,icon:null,follows:0,categories:[],gallery:[],links:{},
        versions:found.id==="family-exploration"?[{id:"demo-pack-v1",name:"Demo pack",minecraft:["1.21.1"],loaders:["fabric"]}]:[],
        body:"This is sample content for an offline website demo. No mods or modpacks are downloaded.",
        body_format:"plain",url:"https://modrinth.com/"};
    }
    if(p.startsWith("/api/hub/mods/requires")||p.startsWith("/api/mods/requires"))
      return {deps:[],compatible:true,reason:""};
    if(p.startsWith("/api/hub/mods/versions"))return {versions:[],builds:[]};
    if(p.startsWith("/api/hub/modpack/preview"))return {minecraft:"1.21.1",loader:"fabric",mods:[],client_mods:[]};
    if(p==="/api/browse/added")return {keys:(s?s.mods:[]).map(m=>m.key)};
    if(p==="/api/mods/add-many"&&method==="POST"){
      const added=[];
      for(const m of body.mods||[]){const key=(m.source||"modrinth")+":"+(m.id||m.slug);
        if(!s.mods.some(x=>x.key===key)){s.mods.push({key,name:m.name,version:"1.0",required:true});added.push(m.name)}
      }
      return {added,skipped:[]};
    }
    if (!s) throw Error("Create a demo server first.");
    if (p==="/api/status") return describe(s);
    if (p==="/api/console") return {last:s.log.length,lines:s.log.filter(x=>x.seq>Number(new URLSearchParams(rawPath.split("?")[1]||"").get("since")||0))};
    if (p.startsWith("/api/console?")) {const since=+(p.split("since=")[1]||0);return {last:s.log.length,lines:s.log.filter(x=>x.seq>since)};}
    if (p.startsWith("/api/events?")) {const since=+(p.split("since=")[1]||0);return {last:s.events.length,events:s.events.filter(x=>x.seq>since)};}
    if (/^\/api\/server\/(start|stop|restart)$/.test(p) || /^\/api\/server\/(start|stop|restart)$/.test(p.replace("/api/","/api/"))) {
      const action=p.split("/").pop();
      s.state=action==="stop"?"stopped":"running";
      if (action!=="start") s.online=[];
      log(s,action==="stop"?"Stopping the server":action==="restart"?"Restarting the server":"Starting the Minecraft server");
      if (s.state==="running") { log(s,"Done (2.418s)! For help, type \"help\""); if (!s.requests.length && !s.known.length) {s.requests.push("JordanMC"); log(s,"JordanMC requested whitelist access");} }
      return {ok:true,message:"Server "+s.state+" (demo)."};
    }
    if (p==="/api/settings") {
      if (method==="POST") {
        s.settings=Object.assign(s.settings,body); if(body.memory)s.memory=body.memory;
        if(body.name)s.name=body.name;if(body.motd)s.motd=body.motd;
        if(body.port)s.port=body.port;
        return {ok:true,message:"Demo settings saved."};
      }
      return settings(s);
    }
    if (p==="/api/players") return players(s);
    if (p.startsWith("/api/players/online")) return offlineOnline(s);
    if (p.startsWith("/api/players/activity")) return {players:[],week:Array.from({length:7},()=>Array(24).fill(0)),busiest:null};
    if (p==="/api/join-requests") return join(s);
    if (p==="/api/join-requests/answer" && method==="POST") {
      const request=s.requests.find(x=>x===body.name)||s.requests[0];
      if (!request) throw Error("No pending requests.");
      s.requests=s.requests.filter(x=>x!==request);
      if (body.action==="allow"||body.answer==="allow"||body.allow===true) {
        if(!s.whitelist.includes(request))s.whitelist.push(request);
        if (s.state==="running"&&!s.online.includes(request))s.online.push(request);
        if (!s.known.includes(request))s.known.push(request);
        log(s,request+" joined the game");
      } else log(s,request+"'s request was ignored.");
      return {ok:true,message:"Request handled in demo."};
    }
    if (p==="/api/players/action" && method==="POST") {
      const action=body.action,n=String(body.name||"").trim();
      if(action==="whitelist-on")s.whitelist_enabled=true;
      else if(action==="whitelist-off")s.whitelist_enabled=false;
      else if(action==="whitelist-add"){if(n&&!s.whitelist.includes(n))s.whitelist.push(n);}
      else if(action==="whitelist-remove")s.whitelist=s.whitelist.filter(x=>x!==n);
      else if(action==="kick"){s.online=s.online.filter(x=>x!==n);log(s,n+" left the game");}
      else if(action==="ban"||action==="ban-ip"){if(n&&!s.bans.includes(n))s.bans.push(n);s.online=s.online.filter(x=>x!==n);log(s,n+" was banned");}
      else if(action==="pardon"||action==="pardon-ip")s.bans=s.bans.filter(x=>x!==n);
      else if(action==="op"){if(n&&!s.ops.includes(n))s.ops.push(n);}
      else if(action==="deop")s.ops=s.ops.filter(x=>x!==n);
      return {ok:true,message:"Player action completed in this simulation."};
    }
    if (p==="/api/command" && method==="POST") {
      const cmd=String(body.command||"").trim();
      if (/[\r\n]/.test(cmd)) throw Error("Commands must be a single line.");
      log(s,"> "+cmd);
      if(cmd==="list")log(s,"There are "+s.online.length+" of a max of "+s.max_players+" players online: "+s.online.join(", "));
      else if(cmd.startsWith("say "))log(s,"[Server] "+cmd.slice(4));
      else if(cmd==="help")log(s,"Demo commands: help, list, say, whitelist add <name>");
      else if(cmd.startsWith("whitelist add ")) {const n=cmd.slice(14).trim();if(n&&!s.whitelist.includes(n))s.whitelist.push(n);log(s,"Added "+n+" to the whitelist");}
      else log(s,"This demo command was not executed against a real server.");
      return {ok:true,message:"Demo command handled."};
    }
    if(p==="/api/broadcast"&&method==="POST"){log(s,"[Server] "+String(body.message||"").slice(0,256));return {ok:true,message:"Demo broadcast sent."};}
    if(p==="/api/backups"){
      return {backups:s.backups.slice().reverse()};
    }
    if(p==="/api/backups/create"&&method==="POST"){
      const name="backup-"+Date.now()+".tar.gz";
      s.backups.push({name,time:tick(),size:52428800,holds:["world","mods"],snapshot:true,
        minecraft:s.minecraft,mods:s.mods.length,changes:[],check:{ok:true,detail:"Simulated backup verified"}});
      log(s,"Backup created: "+name);return {message:"Demo backup created.",name};
    }
    if(p==="/api/backups/check"&&method==="POST")return {ok:true,message:"Demo backup verified."};
    if(p==="/api/backups/restore"&&method==="POST"){log(s,"Restored demo backup "+body.name);return {ok:true,message:"Demo backup restored."};}
    if(p.startsWith("/api/backups/changes"))return {snapshot:true,undo:[]};
    if(p==="/api/backups/area")return {ok:true,message:"Demo area restore simulated."};
    if(p==="/api/mods")return mods(s);
    if(p==="/api/mods/add"&&method==="POST"){
      const value=body.key||"modrinth:"+(body.id||body.slug||"lithium");
      if(!s.mods.some(m=>m.key===value))s.mods.push({key:value,name:body.name||value.split(":").pop(),version:"1.0",required:false});
      return {message:"Mod added to the demo server."};
    }
    if(p==="/api/mods/remove"&&method==="POST"){
      const key=body.key||"modrinth:"+(body.id||body.slug||"");
      s.mods=s.mods.filter(m=>m.key!==key);return {message:"Mod removed from the demo server."};
    }
    if(p==="/api/mods/pin"&&method==="POST")return {message:"Version preference saved for demo."};
    if(p.startsWith("/api/mods/search"))return {results:[sampleMod("Fabric API","modrinth:fabric-api"),sampleMod("Lithium","modrinth:lithium")],mods:[],hidden:0,early_hidden:0};
    if(p.startsWith("/api/mods/versions"))return {versions:[],builds:[]};
    if(p==="/api/client"){
      if(method==="POST")return client(s);
      return client(s);
    }
    if(p==="/api/join-requests/answer")return {message:"Demo request updated."};
    if(p==="/api/performance")return {running:s.state==="running",supported:true,status:"ok",words:"Keeping up",current:s.state==="running"?{tps:20,mspt:24}:null,samples:[],spark:false};
    if(p==="/api/performance/lag")return {finder:null,findings:[]};
    if(p==="/api/updates")return {check:{installed:s.minecraft,latest:s.minecraft,target:null,
      up_to_date:true,manual:[],changes:[],blocked:[],dropped:[],lagging:null,checked_at:tick(),
      loader_version:"",packs:[]}};
    if(p==="/api/updates/check" && method==="POST")return {ok:true,message:"Demo update check complete."};
    if(p==="/api/updates/rehearsal")return {job:null,report:null};
    if(p==="/api/beta")return {betas:[],copies:false};
    if(p==="/api/java")return {required:21,forced:null,auto_install:true,
      choice:{source:"shared",major:21,release:"21.0.4",also:[],newer:[],wanted:21},
      shared:[{major:21,releases:[{release:"21.0.4",newest:true,bytes:214748364,used_by:[s.name]}],used_by:[s.name]}],
      found:[],store:"[DEMO] /java"};
    if(p==="/api/webmap")return {configured:false,kind:null,answers:false};
    if(p==="/api/bedrock")return {geyser:false,floodgate:false,installed:false,port:19132};
    if(p==="/api/doctor")return {checks:[{title:"Simulated server",status:"ok",detail:"This demonstration cannot access your computer or network."}]};
    if(p==="/api/tunnel")return {address:""};
    if(p==="/api/play-here")return {installed:true,server_gb:4,game_gb:4,system_gb:16,mods:s.mods.length,max_players:20};
    if(p==="/api/configs")return {mods:[],other:[],files:[]};
    if(p==="/api/modsets")return {sets:[]};
    if(p==="/api/hub/manual/needed")return {items:[]};
    if(p==="/api/licenses")return {licenses:[]};
    if(p==="/api/hub/users")return {users:[]};
    if(p==="/api/updates/readiness")return {minecraft:s.minecraft,loader:{state:"green",name:s.loader},counts:{green:0,yellow:0,red:0,unknown:0},mods:[]};
    if (method !== "GET") {
      const unsafe=/\/(apply|install|remove|delete|restore|upload|stage|connect|open|quit|start|stop|join|pair|test|check|update|save|add|create|fix|invite|new-link)/.test(p);
      return {ok:!unsafe,message:unsafe?"Demo only: this action cannot access your computer or outside services.":"Demo action acknowledged."};
    }
    throw Error("Demo preview does not yet support "+p+". No real request was made.");
  }
  const realFetch = window.fetch.bind(window);
  window.fetch = async function (input, init={}) {
    const raw = typeof input==="string"?input:input.url;
    const parsed = new URL(raw,location.href);
    const path = parsed.pathname;
    // All requests starting /api are handled locally, including unknown APIs.
    if(path==="/api"||path.startsWith("/api/")){
      let body={};try{if(init.body&&typeof init.body==="string")body=JSON.parse(init.body);}catch{}
      try {
        const result = handle((init.method||"GET").toUpperCase(),path+parsed.search,body);
        persist();
        return new Response(JSON.stringify(result),{status:200,headers:{"Content-Type":"application/json"}});
      } catch(error) {
        return new Response(JSON.stringify({error:error.message}),{status:501,headers:{"Content-Type":"application/json"}});
      }
    }
    // The demo has no legitimate reason to contact arbitrary third-party services.
    if(parsed.origin!==location.origin)throw new TypeError("External network requests are disabled in the demo.");
    return realFetch(input,init);
  };
  // Do not permit browser upload operations to contact any real API via XMLHttpRequest.
  const RealXHR=window.XMLHttpRequest;
  window.XMLHttpRequest=function(){
    const xhr=new RealXHR();const oldOpen=xhr.open;
    xhr.open=function(method,url){const p=new URL(url,location.href).pathname;if(p.startsWith("/api/"))throw Error("File uploads cannot run in this public demo.");return oldOpen.apply(this,arguments)};
    return xhr;
  };
  // Manual demo events for people exploring player moderation.
  window.CraftDemo={
    reset(){try{sessionStorage.removeItem(KEY)}catch{}location.reload();},
    joinRequest(name="JordanMC"){const s=serverFrom("").s;if(!s)return;const safe=String(name).replace(/[^A-Za-z0-9_]/g,"").slice(0,16);if(safe&&!s.requests.includes(safe)){s.requests.push(safe);log(s,safe+" requested whitelist access");persist();}},
    playerJoin(name="JordanMC"){const s=serverFrom("").s;if(!s||s.state!=="running")return;const safe=String(name).replace(/[^A-Za-z0-9_]/g,"").slice(0,16);if(safe&&!s.online.includes(safe)){s.online.push(safe);if(!s.known.includes(safe))s.known.push(safe);log(s,safe+" joined the game");persist();}}
  };
  if(!location.hash)location.hash=mode==="new"?"#new":"#s/family-survival/dashboard";
  persist();
})();