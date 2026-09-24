/* Offline actual-media browser smoke. Fixture backend + nginx on loopback only.
 * Requires playwright-core, system Chromium, /verify/media.mp4 (H264/AAC, 180s).
 * Media is fulfilled in the browser, leaving production SSRF protections intact.
 */
const {chromium}=require('/verify/node_modules/playwright-core');
const fs=require('node:fs');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
 try {
 const bytes=fs.readFileSync('/verify/media.mp4'), pages=[], resolutions=[], errors=[];
 const delay=Number(process.env.WS_DELAY_MS||0);
 for(const profile of [1,2]) {
  const context=await browser.newContext();
  context.setDefaultTimeout(15000);
  if(delay) await context.routeWebSocket('**/api/watch-together/rooms/*/ws',ws=>{
   const server=ws.connectToServer();
   ws.onMessage(message=>setTimeout(()=>server.send(message),delay));
   server.onMessage(message=>setTimeout(()=>ws.send(message),delay));
  });
  await context.addInitScript(id=>localStorage.setItem('media-app.selected-profile.v1',String(id)),profile);
  await context.route('https://media.example/**',async route=>{
   const range=route.request().headers()['range'];
   const match=range?.match(/bytes=(\d+)-(\d*)/);
   const start=match?Number(match[1]):0,end=match?.[2]?Math.min(Number(match[2]),bytes.length-1):bytes.length-1;
   await route.fulfill({status:match?206:200,headers:{'Content-Type':'video/mp4','Access-Control-Allow-Origin':'*','Accept-Ranges':'bytes',...(match?{'Content-Range':`bytes ${start}-${end}/${bytes.length}`}:{})},body:bytes.subarray(start,end+1)});
  });
  const page=await context.newPage();pages.push(page);
  page.on('pageerror',e=>errors.push(String(e)));
  page.on('response',async r=>{if(r.url().endsWith('/resolve')&&r.ok())try{const j=await r.json();if(j.playback) resolutions.push({profile,...j.playback});}catch{}});
  await page.goto(`http://127.0.0.1/watch/${profile}/tv/42/season/1/episode/1`);
  await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2,{},{timeout:30000});
 }
 const [a,b]=pages;
 await a.getByRole('button',{name:'Create room',exact:true}).click();
 await a.getByRole('button',{name:'Play room',exact:true}).waitFor();
 const panel=p=>p.locator('section').filter({has:p.getByRole('heading',{name:'Watch Together',exact:true})});
 const room=await panel(a).locator('code').innerText();
 await b.getByLabel('Room ID').fill(room);
 await b.getByRole('button',{name:'Join room',exact:true}).click();
 const ready=async()=>{for(const p of pages) await p.waitForFunction(()=>[...document.querySelectorAll('section')].some(s=>s.querySelector('h2')?.textContent==='Watch Together'&&s.textContent.includes('Smoke A (host): ready')&&s.textContent.includes('Smoke B: ready')),{},{timeout:30000});};
 await ready();
 await a.getByRole('button',{name:'Play room',exact:true}).click();
 for(const p of pages) await p.waitForFunction(()=>{const v=document.querySelector('video');return v&&!v.paused&&v.currentTime>2;});
 await a.getByRole('button',{name:'Pause room',exact:true}).click();
 for(const p of pages) await p.waitForFunction(()=>document.querySelector('video')?.paused);
 await a.waitForTimeout(1000);
 await a.evaluate(()=>document.querySelector('video').currentTime=40);
 await b.waitForFunction(()=>Math.abs(document.querySelector('video').currentTime-40)<.2);
 await a.getByRole('button',{name:'Play room',exact:true}).click();
 await b.waitForFunction(()=>!document.querySelector('video').paused);
 await b.evaluate(()=>document.querySelector('video').currentTime-=.8);
 await b.waitForFunction(()=>document.querySelector('video').playbackRate!==1,{},{timeout:8000});
 await b.evaluate(()=>document.querySelector('video').currentTime=5);
 await b.waitForFunction(()=>document.querySelector('video').currentTime>35,{},{timeout:8000});
 const reconnected=b.waitForResponse(r=>r.url().endsWith('/resolve')&&r.ok());
 await b.getByRole('button',{name:'Reconnect / retry source',exact:true}).click();
 await reconnected;
 await ready();
 for(const expected of ['/season/1/episode/2','/season/2/episode/1']) {
  await a.getByRole('button',{name:'Next episode for room',exact:true}).click();
  for(const p of pages) {
   try { await p.waitForURL('**'+expected); }
   catch(error) {
    console.error(JSON.stringify({expected,url:p.url(),panel:await panel(p).innerText(),resolved:resolutions.map(r=>({profile:r.profile,season:r.state.season_number,episode:r.state.episode_number}))}));
    throw error;
   }
  }
  await ready();
 }
 const ownA=resolutions.filter(r=>r.profile===1),ownB=resolutions.filter(r=>r.profile===2);
 assert(ownA.length>=3&&ownB.length>=3);
 assert(ownA.every(r=>r.selected_source.provider_id==='smoke-a'));
 assert(ownB.every(r=>r.selected_source.provider_id==='smoke-b'));
 assert(!ownA.some(x=>ownB.some(y=>x.source_session_id===y.source_session_id)));
 await a.screenshot({path:'/artifacts/orbis-v1-watch-browser.png'});
 await a.getByRole('button',{name:'Close room',exact:true}).click();
 for(const p of pages) await p.getByRole('button',{name:'Create room',exact:true}).waitFor();
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({result:'PASS',clients:2,media:'H264/AAC',checks:['play','pause','seek','rate correction','large drift seek','reconnect','next episode','season boundary','independent sources','close'],resolutions:resolutions.length,pageErrors:errors.length}));
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
