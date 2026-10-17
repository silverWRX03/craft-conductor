"use strict";
const nav=document.getElementById("site-nav"), scrim=document.getElementById("nav-scrim"),menu=document.getElementById("mobile-menu");
function setNav(open){nav.classList.toggle("open",open);scrim.classList.toggle("open",open);menu.setAttribute("aria-expanded",String(open));}
menu.addEventListener("click",()=>setNav(!nav.classList.contains("open")));scrim.addEventListener("click",()=>setNav(false));nav.querySelectorAll("a").forEach(a=>a.addEventListener("click",()=>setNav(false)));
const theme=document.getElementById("theme-toggle");
let remembered="";try{remembered=localStorage.getItem("cc-site-theme")||""}catch{}
function setTheme(v){document.body.dataset.theme=v;theme.setAttribute("aria-pressed",String(v==="dark"));theme.textContent=v==="dark"?"☾ Switch to light":"☀ Switch to dark";}
setTheme(remembered||"dark");theme.addEventListener("click",()=>{const v=document.body.dataset.theme==="dark"?"light":"dark";setTheme(v);try{localStorage.setItem("cc-site-theme",v)}catch{}});
const layer=document.getElementById("demo-layer"),picker=document.getElementById("demo-picker"),frame=document.getElementById("demo-frame"),leave=document.getElementById("leave-demo");
let opener=null;
function launch(){opener=document.activeElement;layer.hidden=false;layer.setAttribute("aria-hidden","false");document.body.classList.add("no-scroll");picker.hidden=false;frame.hidden=true;frame.removeAttribute("src");leave.focus();}
function exit(){frame.removeAttribute("src");layer.hidden=true;layer.setAttribute("aria-hidden","true");document.body.classList.remove("no-scroll");if(opener&&opener.isConnected)opener.focus();}
document.querySelectorAll("[data-demo]").forEach(b=>b.addEventListener("click",launch));leave.addEventListener("click",exit);document.getElementById("demo-backdrop").addEventListener("click",exit);
document.querySelectorAll("[data-scenario]").forEach(b=>b.addEventListener("click",()=>{picker.hidden=true;frame.hidden=false;frame.src="demo/?scenario="+encodeURIComponent(b.dataset.scenario);}));
const phoneLayer=document.getElementById("phone-layer"),phoneFrame=document.getElementById("phone-frame");function closePhone(){phoneLayer.hidden=true;phoneFrame.removeAttribute("src");}
document.getElementById("phone-close").addEventListener("click",closePhone);
window.addEventListener("message",(ev)=>{if(ev.origin!==location.origin)return;if(ev.data&&ev.data.type==="cc-demo-open-mobile"){phoneLayer.hidden=false;phoneFrame.src="demo/?scenario=example&phone=1";}});
document.addEventListener("keydown",ev=>{if(ev.key==="Escape"){if(!phoneLayer.hidden)closePhone();else if(!layer.hidden)exit();}});
fetch("demo/release.json").then(r=>r.ok?r.json():null).then(v=>{if(v&&v.version)document.getElementById("site-version").textContent="Demo: "+v.version+" · Open source";}).catch(()=>{});
