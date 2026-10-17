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
 page.on("pageerror",e=>errors.push(e.stack||e.message));
 try{
  const origin="http://127.0.0.1:"+srv.address().port;
  await page.goto(origin+"/craft-conductor/",{waitUntil:"domcontentloaded"});
  assert.match(await page.title(),/Craft Conductor/);
  fs.mkdirSync(path.resolve(__dirname,"../.site-test/report"),{recursive:true});
  await page.screenshot({path:path.resolve(__dirname,"../.site-test/report/homepage.png"),fullPage:true});
  await page.getByRole("button",{name:/Try the interactive demo/}).click();
  assert.equal(await page.locator("#demo-layer").isVisible(),true);
  await page.locator('[data-scenario="example"]').click();
  const frame=page.frameLocator("#demo-frame");
  await frame.locator("#app").waitFor({state:"visible",timeout:20000});
  await page.waitForTimeout(800); // let the real app's theme transition settle before visual capture
  const appearance=await frame.locator("#stage").evaluate(el=>({
    theme:document.documentElement.dataset.theme,
    body:getComputedStyle(document.body).backgroundColor,
    stage:getComputedStyle(el).backgroundColor,
    main:getComputedStyle(el.querySelector("main")).backgroundColor
  }));
  console.log("Demo appearance:",JSON.stringify(appearance));
  await page.screenshot({path:path.resolve(__dirname,"../.site-test/report/demo-dashboard.png")});
  const nav=await frame.locator("#nav").innerText();
  assert.match(nav,/DASHBOARD/i);assert.match(nav,/PLAYERS/i);
  await frame.locator("#nav a").filter({hasText:"Players"}).first().click();
  await frame.locator("#main").getByText("Whitelist",{exact:false}).first().waitFor({timeout:15000});
  const iframe=await page.locator("#demo-frame").elementHandle();
  const child=await iframe.contentFrame();
  for(const view of ["dashboard","console","players","updates","mods","friends","backups","java","settings"]){
    const before=errors.length;
    await child.evaluate(v=>{location.hash="#s/family-survival/"+v;},view);
    await page.waitForTimeout(400);
    const newErrors=errors.slice(before);
    if(newErrors.length)console.error("View "+view+" errors:\n"+newErrors.join("\n"));
  }
  for(const view of ["servers","craft-conductor","help","manual","new"]){
    const before=errors.length;
    await child.evaluate(v=>{location.hash="#"+v;},view);
    await page.waitForTimeout(400);
    const newErrors=errors.slice(before);
    if(newErrors.length)console.error("Global view "+view+" errors:\n"+newErrors.join("\n"));
  }
  await child.evaluate(()=>location.hash="#s/family-survival/dashboard");
  await frame.getByRole("button",{name:/Phone \/ QR/}).click();
  await frame.locator("#demo-phone-panel img").waitFor();
  assert.match(await frame.locator("#demo-phone-panel a").getAttribute("href"),/phone=1/);
  await frame.locator("#demo-phone-panel a").click();
  await page.locator("#phone-layer").waitFor({state:"visible",timeout:10000});
  await page.frameLocator("#phone-frame").locator("#app").waitFor({state:"visible",timeout:20000});
  await page.locator("#phone-close").click();
  assert.equal(await page.locator("#phone-layer").isVisible(),false);

  assert.deepEqual(errors,[],"Browser JavaScript errors:\n"+errors.join("\n"));
  await page.locator("#leave-demo").click();
  assert.equal(await page.locator("#demo-layer").isVisible(),false);
  // Verify the first-server path renders the real setup controls.
  await page.getByRole("button",{name:/Try the interactive demo/}).click();
  await page.locator('[data-scenario="fresh"]').click();
  await frame.locator("#app").waitFor({state:"visible",timeout:20000});
  await frame.locator('button[aria-label^="Vanilla:"]').click();
  await frame.locator("#setup-version").waitFor({timeout:10000});
  await frame.locator('label').filter({hasText:"I accept the"}).locator("input[type=checkbox]").check();
  await frame.getByRole("button",{name:"Create my server",exact:true}).click();
  await page.waitForTimeout(700);
  assert.equal(await frame.locator("#app").isVisible(),true);
  await page.locator("#leave-demo").click();
  console.log("Public site demo browser smoke tests passed");
 }finally{await browser.close();await new Promise(resolve=>srv.close(resolve));}
})().catch(e=>{console.error(e);process.exitCode=1;});
