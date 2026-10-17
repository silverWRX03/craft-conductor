"use strict";
const assert=require("node:assert/strict"),http=require("node:http"),fs=require("node:fs"),path=require("node:path");
const {chromium}=require("../.site-test/node_modules/playwright");
const root=path.resolve(__dirname,"../_site");
const mime={".html":"text/html",".js":"text/javascript",".css":"text/css",".json":"application/json",".png":"image/png",".svg":"image/svg+xml",".md":"text/plain"};
const srv=http.createServer((req,res)=>{
 const u=new URL(req.url,"http://localhost");
 let rel=decodeURIComponent(u.pathname).replace(/^\/craft-conductor\/?/,"");
 if(!rel||rel.endsWith("/"))rel+="index.html";
 const f=path.resolve(root,rel);
 if(!f.startsWith(root+path.sep)){res.writeHead(403);return res.end();}
 fs.readFile(f,(err,data)=>{if(err){res.writeHead(404);return res.end("Not found");}res.writeHead(200,{"Content-Type":mime[path.extname(f)]||"application/octet-stream"});res.end(data);});
});
(async()=>{
 await new Promise(resolve=>srv.listen(0,"127.0.0.1",resolve));
 const browser=await chromium.launch({headless:true});
 const page=await browser.newPage();const errors=[];
 page.on("pageerror",e=>errors.push(e.message));
 try{
  const origin="http://127.0.0.1:"+srv.address().port;
  await page.goto(origin+"/craft-conductor/",{waitUntil:"domcontentloaded"});
  assert.match(await page.title(),/Craft Conductor/);
  await page.getByRole("button",{name:/Try the interactive demo/}).click();
  assert.equal(await page.locator("#demo-layer").isVisible(),true);
  await page.locator('[data-scenario="example"]').click();
  const frame=page.frameLocator("#demo-frame");
  await frame.locator("#app").waitFor({state:"visible",timeout:20000});
  const nav=await frame.locator("#nav").innerText();
  assert.match(nav,/DASHBOARD/i);assert.match(nav,/PLAYERS/i);
  await frame.locator("#nav a").filter({hasText:"Players"}).first().click();
  await frame.locator("#main").getByText("Whitelist",{exact:false}).first().waitFor({timeout:15000});
  assert.deepEqual(errors,[],"Browser JavaScript errors: "+errors.join(" | "));
  await page.locator("#leave-demo").click();
  assert.equal(await page.locator("#demo-layer").isVisible(),false);
  console.log("Public site demo browser smoke tests passed");
 }finally{await browser.close();await new Promise(resolve=>srv.close(resolve));}
})().catch(e=>{console.error(e);process.exitCode=1;});
