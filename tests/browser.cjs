// Isolated end-to-end smoke test. Uses a temporary board; never posts to port 8765.
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert/strict');
const {spawn, spawnSync} = require('child_process');
const {chromium, python, launchOptions}=require('./support.cjs');
const root = path.resolve(__dirname,'..');
const data = fs.mkdtempSync(path.join(os.tmpdir(),'agents-talk-browser-'));
const screenshots = path.join(root,'.runtime');
fs.mkdirSync(screenshots,{recursive:true});
const env = {...process.env,AGENTS_TALK_DATA:data,AGENTS_TALK_CONFIG:path.join(root,'config.example.json'),PYTHONUTF8:'1',PYTHONDONTWRITEBYTECODE:'1'};
const port = 18765, base = 'http://127.0.0.1:'+port;
let server, browser;
function start() { server=spawn(python,[path.join(root,'hub.py'),'serve','--port',String(port),'--no-open'],{env,windowsHide:true,stdio:'pipe'}); }
async function ready() {for(let i=0;i<80;i++){if(server.exitCode!==null)throw Error('Test server exited; the test port may be occupied');try{const r=await fetch(base+'/api/state');await r.arrayBuffer();if(r.ok)return;}catch{}await new Promise(r=>setTimeout(r,100));}throw Error('Test server did not start');}
async function stop(){if(server&&!server.killed){server.kill();await new Promise(resolve=>server.once('exit',resolve));}}
function post(who,type,...args) {const r=spawnSync(python,[path.join(root,'hub.py'),'post','--from',who,'--session','main','--type',type,...args],{env,encoding:'utf8',windowsHide:true});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout);}

// All race fixtures live in memory. Every request on this page is intercepted;
// no mock message reaches either the isolated server or a real board.
async function raceTests(browser) {
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[], requests=[], gates=[];
  page.on('pageerror',e=>errors.push(e.message));
  const ids=['claude','codex','reasonix','zcode'];
  const agents=Object.fromEntries(ids.map(id=>[id,{id,name:id==='zcode'?'ZCode':id,capabilities:{},msgs:0,status:'fixture',online:false}]));
  const sessions=new Map(['a','b'].map(id=>[id,{id,title:'Race '+id,status:'active',mode:'leader',lead:'claude',participants:['claude','codex','reasonix'],shared_context:false}]));
  const messages=new Map(), tasks=new Map(), uploaded=new Map();let revision=1,uploadId=0;
  const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
  function hold(match,result) {
    const arrived=deferred(), release=deferred(), finished=deferred();
    const gate={match,result,arrived,release,finished,used:false};gates.push(gate);
    return {arrived:()=>Promise.race([arrived.promise,new Promise((_,reject)=>{const t=setTimeout(()=>reject(Error('Request gate was not reached: '+match.toString()+'; recent requests: '+JSON.stringify(requests.slice(-8).map(r=>({path:r.pathname,session:r.body?.session||r.query.get('session'),method:r.method}))))),10000);t.unref();})]),release:async()=>{release.resolve();await finished.promise;}};
  }
  const stateFor=id=>({session:{...sessions.get(id),migration_required:!ids.includes(sessions.get(id).lead),retired_participants:sessions.get(id).lead==='pi'?['pi']:[]},sessions:[...sessions.values()],agents,revision,csrf:'token-'+id,total:(messages.get(id)||[]).length,messages:messages.get(id)||[],tasks:tasks.get(id)||[],locks:{},receipts:{}});
  function response(entry) {
    const {pathname,query,body}=entry;const id=query.get('session')||'a';
    if(pathname==='/api/state')return {json:structuredClone(stateFor(id))};
    if(pathname==='/api/session') {
      revision++;
      if(body.action==='create') {const id='created-'+revision;sessions.set(id,{...sessions.get('a'),id,title:body.title});return {json:{session:id}};}
      const s=sessions.get(body.session);assert(s,'session snapshot must exist');
      if(body.action==='settings') {for(const key of ['mode','lead','participants','shared_context'])if(key in body)s[key]=body[key];}
      else if(['active','paused','ended'].includes(body.action))s.status=body.action;
      return {json:{session:body.session}};
    }
    if(pathname==='/api/post') {const list=messages.get(body.session)||[];if(!list.some(m=>m.request_id===body.request_id)){list.push({...body,attachments:body.attachments.map(id=>uploaded.get(id)),id:'message-'+(++revision),from:'human',ts:'2026-09-11T00:00:00Z'});messages.set(body.session,list);}return {json:{id:list.at(-1).id}};}
    if(pathname==='/api/upload'){const a={id:'upload-'+(++uploadId),name:query.get('name'),mime:'text/plain',size:1};uploaded.set(a.id,a);return {json:a};}
    if(pathname==='/api/skills')return {json:Object.fromEntries(ids.map(a=>[a,'Guide '+id+' '+a]))};
    if(pathname==='/api/context')return {json:{context:{scope:'focused',task_count:0,next_task_offset:null},fixture:id}};
    if(pathname==='/api/export')return {json:stateFor(id)};
    throw Error('Unexpected mock API: '+pathname);
  }
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url());let gate;
    try {
      if(!url.pathname.startsWith('/api/')) {
        const file=url.pathname==='/'?'index.html':url.pathname.slice(1);
        assert(['index.html','app.js','style.css','observatory.css'].includes(file),'Unexpected asset '+file);
        return await route.fulfill({body:fs.readFileSync(path.join(root,'web',file)),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html'});
      }
      const req=route.request(),entry={pathname:url.pathname,query:url.searchParams,method:req.method(),token:req.headers()['x-agents-token'],body:url.pathname==='/api/upload'?null:req.postDataJSON()};
      requests.push(entry);gate=gates.find(g=>!g.used&&g.match(entry));if(gate)gate.used=true;
      const result=gate?.result||response(entry);
      if(gate){gate.arrived.resolve(entry);await gate.release.promise;}
      await route.fulfill({status:result.status||200,contentType:'application/json',body:JSON.stringify(result.json)});
    } catch(e) {errors.push(e.message);await route.abort().catch(()=>{});}
    finally {gate?.finished.resolve();}
  });
  // Deliberately let cancelled state responses arrive, to exercise the generation
  // checks as well as the AbortController path.
  await page.addInitScript(()=>{const realFetch=window.fetch;window.fetch=(url,options)=>realFetch(url,String(url).startsWith('/api/state')?{...options,signal:undefined}:options);});
  const idle=()=>page.waitForFunction(()=>document.querySelector('#message-form').getAttribute('aria-busy')==='false');
  const select=async id=>{await page.locator(`[data-session="${id}"]`).click();await page.waitForFunction(id=>document.querySelector('#session-title').textContent==='Race '+id,id);await page.waitForFunction(()=>!document.querySelector('#lead-select').disabled);};
  const refresh=()=>page.evaluate(()=>{void sync({fresh:true});});
  const writes=()=>requests.filter(r=>r.method==='POST').length;
  const changed=async(selector,value)=>{await page.locator(selector).evaluate((el,value)=>{if(el.type==='checkbox')el.checked=value;else el.value=value;el.dispatchEvent(new Event('change',{bubbles:true}));},value);};
  try {
    await page.goto('http://127.0.0.1:19876/');await idle();await page.waitForFunction(()=>!document.querySelector('#send-button').disabled);
    assert.equal(await page.locator('option[value="pi"], [data-participant="pi"]').count(),0);
    assert.equal(await page.locator('[data-participant="zcode"]').isChecked(),false);
    await page.locator('#message-body').fill('draft a');

    const old=hold(r=>r.pathname==='/api/state'&&r.query.get('session')==='a');await refresh();await old.arrived();
    await select('b');await page.locator('#message-body').fill('draft b');
    const newer=hold(r=>r.pathname==='/api/state'&&r.query.get('session')==='a');
    await page.locator('[data-session="a"]').click();await newer.arrived();
    const before=writes();
    assert.equal(await page.locator('#pause-resume').isDisabled(),true);
    await changed('#mode-select','roundtable');
    await page.locator('#pause-resume').dispatchEvent('click');
    await page.locator('#finish-form').dispatchEvent('submit');
    assert.equal(writes(),before,'loading a session must block every write entry');
    await old.release();await page.evaluate(()=>new Promise(r=>requestAnimationFrame(r)));
    assert.equal(await page.locator('#session-title').textContent(),'Race b','A/B/A must discard the first A response');
    assert.equal(await page.locator('#lead-select').isDisabled(),true);
    await newer.release();await page.waitForFunction(()=>!document.querySelector('#send-button').disabled);
    assert.equal(await page.locator('#message-body').inputValue(),'draft a');
    console.log('PASS race: immediate switch, A/B/A stale state, loading write guards, drafts');

    const sendA=hold(r=>r.pathname==='/api/post'&&r.body.session==='a');
    await page.locator('#send-button').click();await sendA.arrived();
    const sendCount=writes();await page.locator('#message-form').dispatchEvent('submit');
    await page.locator('#session-form').dispatchEvent('submit');await changed('#shared-context',true);
    assert.equal(writes(),sendCount,'send/create/settings must be mutually exclusive');
    assert.equal(await page.locator('#tab-media').isDisabled(),true);
    assert.equal(await page.locator('#new-session').isDisabled(),true);
    await select('b');assert.equal(await page.locator('#message-body').inputValue(),'draft b');
    const sendB=hold(r=>r.pathname==='/api/post'&&r.body.session==='b');
    await page.locator('#send-button').click();await sendB.arrived();await sendA.release();
    assert.equal(await page.locator('#message-body').inputValue(),'draft b');
    assert.equal(await page.locator('#send-button').isDisabled(),true,'old send must not release the new session lock');
    await sendB.release();await idle();assert.equal(await page.locator('#message-body').inputValue(),'');
    assert.deepEqual(messages.get('a').map(m=>m.body),['draft a']);assert.deepEqual(messages.get('b').map(m=>m.body),['draft b']);
    assert.equal(await page.evaluate(()=>localStorage.getItem('agents-talk.draft.a')),'');
    console.log('PASS race: send snapshots, duplicate guard, cross-session draft and lock isolation');

    await select('a');
    const uploadA=hold(r=>r.pathname==='/api/upload'&&r.query.get('name')==='a1.txt');
    await page.locator('#file-input').setInputFiles(['a1.txt','a2.txt'].map(name=>({name,mimeType:'text/plain',buffer:Buffer.from('a')})));await uploadA.arrived();
    const uploadsBefore=writes();await page.locator('#message-form').dispatchEvent('submit');await changed('#lead-select','codex');assert.equal(writes(),uploadsBefore);
    await select('b');await page.locator('#message-body').fill('b while uploading');
    const uploadB=hold(r=>r.pathname==='/api/upload'&&r.query.get('name')==='b.txt');
    await page.locator('#file-input').setInputFiles({name:'b.txt',mimeType:'text/plain',buffer:Buffer.from('b')});await uploadB.arrived();await uploadA.release();
    await page.waitForFunction(()=>!operations.has('a'));
    assert.equal(await page.locator('#attachment-list').textContent(),'');
    assert.equal(await page.locator('#message-body').inputValue(),'b while uploading');
    assert.equal(await page.locator('#send-button').isDisabled(),true);
    assert.equal(requests.find(r=>r.pathname==='/api/upload'&&r.query.get('name')==='a2.txt').token,'token-a','multi-file upload must keep the original token');
    await uploadB.release();await idle();assert((await page.locator('#attachment-list').textContent()).includes('b.txt'));
    await select('a');assert.equal(await page.locator('.pending-attachment').count(),2);
    console.log('PASS race: upload snapshots, batch token, attachment and lock isolation');

    const staleState=hold(r=>r.pathname==='/api/state'&&r.query.get('session')==='a');await refresh();await staleState.arrived();
    const freshState=hold(r=>r.pathname==='/api/state'&&r.query.get('session')==='a');
    await page.selectOption('#mode-select','roundtable');await freshState.arrived();
    const settingsBefore=writes();await changed('#lead-select','codex');await changed('#shared-context',true);
    assert.equal(writes(),settingsBefore);assert.equal(await page.locator('#send-button').isDisabled(),true);
    await staleState.release();await page.evaluate(()=>new Promise(r=>requestAnimationFrame(r)));
    assert.equal(await page.locator('#mode-select').isDisabled(),true,'settings must wait for a fresh state after POST');
    await freshState.release();await idle();assert.equal(await page.locator('#mode-select').inputValue(),'roundtable');
    const modeWrite=requests.filter(r=>r.pathname==='/api/session'&&r.body.mode==='roundtable').at(-1);
    assert.equal('lead' in modeWrite.body,false,'mode change must not overwrite a concurrent lead change');
    const settingA=hold(r=>r.pathname==='/api/session'&&r.body.session==='a');
    await page.locator('#shared-context').check();await settingA.arrived();await select('b');
    const settingB=hold(r=>r.pathname==='/api/session'&&r.body.session==='b');
    await page.selectOption('#lead-select','codex');await settingB.arrived();await settingA.release();
    assert.equal(await page.locator('#lead-select').isDisabled(),true);assert.equal(await page.locator('#shared-context').isChecked(),false);
    await settingB.release();await idle();assert.equal(await page.locator('#lead-select').inputValue(),'codex');
    console.log('PASS race: fresh post-write sync, settings exclusion, field patches and session snapshots');

    await select('a');await page.locator('#message-body').fill('failed send a');
    const fail=hold(r=>r.pathname==='/api/post'&&r.body.session==='a',{status:500,json:{error:'old failure'}});
    await page.locator('#send-button').click();await fail.arrived();await select('b');await fail.release();await page.waitForFunction(()=>!operations.has('a'));
    assert.equal(await page.locator('#composer-error').isHidden(),true);assert.equal(await page.locator('#message-body').inputValue(),'b while uploading');
    await select('a');assert.equal(await page.locator('#message-body').inputValue(),'failed send a');
    const retryId=requests.filter(r=>r.pathname==='/api/post'&&r.body.session==='a').at(-1).body.request_id;
    await page.locator('#send-button').click();await idle();assert.equal(requests.filter(r=>r.pathname==='/api/post'&&r.body.session==='a').at(-1).body.request_id,retryId);
    console.log('PASS race: stale errors and idempotent retry');

    const create=hold(r=>r.pathname==='/api/session'&&r.body.action==='create');
    await page.locator('#new-session').click();await page.locator('#new-session-title').fill('Late creation');await page.locator('#create-session-submit').click();await create.arrived();
    const createBefore=writes();await page.locator('#session-form').dispatchEvent('submit');assert.equal(writes(),createBefore);
    await page.locator('#session-dialog .modal-close').first().click();await select('b');await create.release();await page.waitForFunction(()=>!creating);
    assert.equal(await page.locator('#session-title').textContent(),'Race b');assert.equal(await page.locator('#message-body').inputValue(),'b while uploading');
    console.log('PASS race: create mutual exclusion and stale navigation');

    await select('a');const guide=hold(r=>r.pathname==='/api/skills'&&r.query.get('session')==='a');
    await page.locator('#skills-open').click();await guide.arrived();await page.locator('#skills-dialog .modal-close').click();await select('b');
    await page.locator('#skills-open').click();await page.waitForFunction(()=>document.querySelector('#skill-code').textContent.includes('Guide b'));
    await guide.release();assert((await page.locator('#skill-code').textContent()).includes('Guide b'));await page.locator('#skills-dialog .modal-close').click();
    const context=hold(r=>r.pathname==='/api/context',{status:500,json:{error:'old context failure'}});
    await page.locator('#context-preview-open').click();await context.arrived();await page.locator('#context-dialog .modal-close').click();await select('a');
    await page.locator('#context-preview-open').click();await page.waitForFunction(()=>document.querySelector('#context-preview').textContent.includes('"fixture": "a"'));
    await context.release();assert.equal(await page.locator('#context-preview-error').isHidden(),true);await page.locator('#context-dialog .modal-close').click();
    console.log('PASS race: stale skill and context responses');

    const createFailure=hold(r=>r.pathname==='/api/session'&&r.body.action==='create',{status:500,json:{error:'create retry fixture'}});
    await page.locator('#new-session').click();await page.locator('#new-session-title').fill('Retry title');await page.locator('#create-session-submit').click();
    const firstCreate=(await createFailure.arrived()).body;await createFailure.release();await idle();
    const sameFailure=hold(r=>r.pathname==='/api/session'&&r.body.action==='create',{status:500,json:{error:'create retry fixture'}});
    await page.locator('#create-session-submit').click();const sameCreate=(await sameFailure.arrived()).body;await sameFailure.release();await idle();
    assert.equal(sameCreate.request_id,firstCreate.request_id);
    // Even changing and restoring text starts a new creation intent.
    await page.locator('#new-session-title').fill('Changed title');await page.locator('#new-session-title').fill('Retry title');
    const changedFailure=hold(r=>r.pathname==='/api/session'&&r.body.action==='create',{status:500,json:{error:'create retry fixture'}});
    await page.locator('#create-session-submit').click();const changedCreate=(await changedFailure.arrived()).body;await changedFailure.release();await idle();
    assert.notEqual(changedCreate.request_id,firstCreate.request_id);await page.locator('#session-dialog .modal-close').first().click();
    console.log('PASS race: create retry UUID and input-change reset');

    sessions.get('a').lead='pi';revision++;
    tasks.set('a',[{id:'LEGACY',title:'Historical task',body:'Historical task',owner:'pi',state:'待办',log:[],depends_on:['PRE'],waiting_for:['PRE'],ready:false}]);
    await refresh();await page.waitForFunction(()=>!document.querySelector('#migration-warning').hidden);
    assert((await page.locator('[data-task="LEGACY"] .task-owner').textContent()).includes('历史 Pi'));
    assert.equal(await page.locator('option[value="pi"], [data-participant="pi"], [data-filter="pi"]').count(),0);
    assert((await page.locator('.task-dependencies').textContent()).includes('等待：PRE'));
    assert.equal(await page.locator('[data-reassign="LEGACY"]').isDisabled(),true);
    assert.equal(await page.locator('#lead-select').inputValue(),'');
    await page.locator('#tab-media').click();assert.equal(await page.locator('#send-button').isDisabled(),true);
    await page.selectOption('#lead-select','codex');await idle();assert.equal(await page.locator('#migration-warning').isHidden(),true);
    tasks.get('a')[0].waiting_for=[];tasks.get('a')[0].ready=true;revision++;await refresh();
    await page.waitForFunction(()=>document.querySelector('.task-dependencies').textContent.includes('依赖已满足'));
    await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    assert.deepEqual(errors,[]);console.log('PASS race: historical Pi, ZCode selectors, migration, dependency status, narrow layout');
  } finally {for(const gate of gates)gate.release.resolve();await page.close();}
}
(async()=>{
  try {
    start(); await ready();
    browser=await chromium.launch(launchOptions);
    await raceTests(browser);
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base); await page.waitForFunction(()=>!document.querySelector('#send-button').disabled);
    assert.equal(await page.locator('#reader-reconnect').textContent(),'开始接入');
    assert(await page.locator('#reader-warning').evaluate(el=>el.classList.contains('onboarding-notice')));
    assert.equal(await page.locator('[data-participant="zcode"]').isChecked(),false);
    assert.equal(await page.locator('#recipient-select option[value="zcode"]').evaluate(el=>el.disabled),true);
    await page.locator('[data-participant="zcode"]').check();
    await page.waitForFunction(()=>!document.querySelector('#recipient-select option[value="zcode"]').disabled);
    await page.reload();await page.waitForFunction(()=>!document.querySelector('#send-button').disabled);
    assert.equal(await page.locator('[data-participant="zcode"]').isChecked(),true);
    post('claude','join','--body','已接入，负责拆解本次测试任务。');
    post('codex','join','--body','已接入，等待明确的执行范围。');
    post('codex','usage','--usage-id','browser-request-1','--input-tokens','1000','--output-tokens','300','--provider','fixture','--model','fixture-model','--usage-source','isolated browser test response');
    post('codex','usage','--usage-id','browser-request-1','--input-tokens','1000','--output-tokens','300','--provider','fixture','--model','fixture-model','--usage-source','isolated browser test response');
    await page.waitForFunction(()=>document.querySelector('#usage-total').textContent==='1,300');
    assert((await page.locator('[data-usage-agent="reasonix"]').textContent()).includes('未报告'));
    post('reasonix','say','--body','建议先验证输入边界，再开展实现。');
    post('zcode','join','--body','负责独立检查交付内容。');
    await page.waitForFunction(()=>!document.querySelector('#reader-warning').hidden);
    assert.equal(await page.locator('#reader-reconnect').textContent(),'恢复接入');
    await page.locator('#reader-reconnect').click();
    await page.waitForFunction(()=>document.querySelector('#skill-code').textContent.includes('listen'));
    await page.locator('#skills-dialog .modal-close').click();
    for(const aid of ['claude','codex','reasonix','zcode']) {
      const r=spawnSync(python,[path.join(root,'hub.py'),'read','--agent',aid,'--session','main'],{env,encoding:'utf8',windowsHide:true});
      assert.equal(r.status,0,r.stderr);
    }
    await page.waitForFunction(()=>document.querySelector('#reader-warning').hidden);
    const presencePath=path.join(data,'.presence/main.reasonix.json');
    const presence=JSON.parse(fs.readFileSync(presencePath,'utf8'));presence.read_time-=130;
    fs.writeFileSync(presencePath,JSON.stringify(presence));
    await page.waitForFunction(()=>document.querySelector('#reader-warning-text').textContent.includes('超过 120 秒未读取'));
    post('claude','task','--task','ZCODE-TODO','--to','zcode','--body','检查未参与成员的旧待办转交');
    await page.locator('[data-participant="zcode"]').uncheck();
    await page.waitForFunction(()=>document.querySelector('#recipient-select option[value="zcode"]').disabled);
    await page.locator('[data-reassign="ZCODE-TODO"]').click();
    await page.waitForFunction(()=>!document.querySelector('[data-reassign="ZCODE-TODO"]'));
    assert.equal((await (await fetch(base+'/api/state')).json()).tasks.find(t=>t.id==='ZCODE-TODO').owner,'claude');
    post('claude','task','--task','CTX-OWN','--to','codex','--body','当前成员任务');
    post('claude','task','--task','CTX-PEER','--to','reasonix','--body','其他成员的独立交付');
    post('claude','task','--task','DEP-PRE','--to','codex','--body','完成并审查前置任务');
    post('claude','task','--task','DEP-NEXT','--to','reasonix','--depends-on','DEP-PRE','--body','等待前置审查通过');
    await page.waitForFunction(()=>document.querySelector('[data-task="DEP-NEXT"] .task-dependencies')?.textContent.includes('等待：DEP-PRE'));
    post('codex','claim','--task','DEP-PRE','--body','执行前置任务');
    post('codex','done','--task','DEP-PRE','--body','前置任务待审查');
    assert.equal((await (await fetch(base+'/api/state')).json()).tasks.find(t=>t.id==='DEP-NEXT').ready,false);
    post('claude','review','--task','DEP-PRE','--verdict','pass','--body','前置审查通过');
    await page.waitForFunction(()=>document.querySelector('[data-task="DEP-NEXT"] .task-dependencies')?.textContent.includes('依赖已满足'));
    assert.equal(await page.locator('#shared-context').isChecked(),false);
    await page.locator('#context-preview-open').click();
    await page.waitForFunction(()=>document.querySelector('#context-preview').textContent.includes('CTX-OWN'));
    assert(!(await page.locator('#context-preview').textContent()).includes('CTX-PEER'));
    await page.locator('#context-dialog .modal-close').click();
    await page.locator('#shared-context').check();
    await page.waitForFunction(()=>document.querySelector('#context-mode-label').textContent.includes('开启'));
    await page.reload();await page.waitForFunction(()=>!document.querySelector('#shared-context').disabled);
    assert.equal(await page.locator('#shared-context').isChecked(),true);
    await page.locator('#context-preview-open').click();
    await page.waitForFunction(()=>document.querySelector('#context-preview').textContent.includes('CTX-PEER'));
    await page.locator('#context-dialog .modal-close').click();
    await page.locator('#shared-context').uncheck();
    await page.waitForFunction(()=>document.querySelector('#context-mode-label').textContent.includes('关闭'));
    await page.locator('#message-body').fill('保留历史，优先验证文件冲突。<script>window.bad=true</script>');
    await page.selectOption('#message-type','intervention'); await page.locator('#send-button').click();
    await page.waitForFunction(()=>document.querySelector('#messages').textContent.includes('保留历史'));
    let st=await (await fetch(base+'/api/state')).json();const intervention=st.messages.find(m=>m.type==='intervention');
    post('codex','ack','--reply-to',intervention.id,'--body','收到，先检查并发占用规则。');
    await page.waitForFunction(()=>[...document.querySelectorAll('.receipt')].some(n=>n.textContent.includes('Codex 已确认')));
    assert.equal(await page.evaluate(()=>window.bad),undefined);
    await page.locator('#pause-resume').click();
    await page.waitForFunction(()=>document.querySelector('#session-status').textContent==='已发出暂停');
    await page.locator('#tab-media').click();assert.equal(await page.locator('#send-button').isDisabled(),true);
    await page.locator('#pause-resume').click();
    await page.waitForFunction(()=>document.querySelector('#session-status').textContent==='协作中');
    assert.deepEqual(await page.locator('#media-recipient option').evaluateAll(es=>es.map(e=>e.value).sort()),['claude','codex']);
    await page.locator('#message-body').fill('绘制一张协作流程插图');
    await page.selectOption('#media-recipient','codex');
    await page.locator('#send-button').click();
    await page.waitForFunction(()=>document.querySelector('#task-list').textContent.includes('绘制一张'));
    await page.locator('#tab-message').click();
    const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6kZsAAAAASUVORK5CYII=','base64');
    await page.locator('#file-input').setInputFiles({name:'reference.png',mimeType:'image/png',buffer:png});
    await page.waitForFunction(()=>document.querySelector('#attachment-list img'));
    await page.locator('#message-body').fill('参考图已附上。');await page.locator('#send-button').click();
    await page.waitForSelector('#messages .attachment-media');
    await page.locator('#search-input').fill('保留历史');assert.equal(await page.locator('#messages article').count(),1);
    await page.locator('#clear-filters').click();
    await page.locator('#skills-open').click();await page.waitForFunction(()=>document.querySelector('#skill-code').textContent.includes('main'));
    await page.locator('#skills-dialog .modal-close').click();
    const download=page.waitForEvent('download');await page.selectOption('#export-format','json');const file=await download;const exported=JSON.parse(fs.readFileSync(await file.path(),'utf8'));assert(exported.messages.length>=9);
    await page.locator('#message-body').fill('重连之后继续保留的草稿');
    await stop();await page.waitForFunction(()=>!document.querySelector('#connection-error').hidden,{},{timeout:20000});
    start();await ready();await page.waitForFunction(()=>document.querySelector('#connection-error').hidden);
    assert.equal(await page.locator('#message-body').inputValue(),'重连之后继续保留的草稿');
    await page.locator('#search-input').fill('');
    await page.waitForTimeout(4200);
    await page.locator('#message-scroll').evaluate(el=>el.scrollTop=0);
    await page.evaluate(()=>{document.activeElement?.blur();window.scrollTo(0,0);});
    await page.screenshot({path:path.join(screenshots,'desktop-qa.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:path.join(screenshots,'mobile-qa.png'),fullPage:true});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile horizontal overflow');
    await page.locator('#context-preview-open').click();await page.waitForFunction(()=>document.querySelector('#context-preview').textContent.includes('CTX-OWN'));
    assert(!(await page.locator('#context-preview').textContent()).includes('CTX-PEER'));
    await page.locator('#context-dialog .modal-close').click();
    const sessionCount=(await (await fetch(base+'/api/state')).json()).sessions.length;
    let lostCreate, retriedCreate;
    const loseCreateResponse=async route=>{
      const payload=route.request().postDataJSON();
      if(payload.action==='create'&&!lostCreate) {
        const response=await route.fetch();assert(response.ok());
        lostCreate={payload,result:await response.json()};await route.abort('failed');
      } else {if(payload.action==='create')retriedCreate=payload;await route.continue();}
    };
    await page.route('**/api/session',loseCreateResponse);
    await page.locator('#menu-toggle').click();await page.locator('#new-session').click();
    await page.locator('#new-session-title').fill('第二个隔离会话');await page.locator('#create-session-submit').click();
    await page.waitForFunction(()=>!document.querySelector('#session-form-error').hidden&&!document.querySelector('#create-session-submit').disabled);
    assert.equal((await (await fetch(base+'/api/state')).json()).sessions.length,sessionCount+1);
    await page.locator('#create-session-submit').click();
    await page.waitForFunction(()=>document.querySelector('#session-title').textContent==='第二个隔离会话');
    assert.equal(retriedCreate.request_id,lostCreate.payload.request_id);
    st=await (await fetch(base+'/api/state')).json();assert.equal(st.session.id,lostCreate.result.session);assert.equal(st.sessions.length,sessionCount+1);
    await page.unroute('**/api/session',loseCreateResponse);
    console.log('PASS integration: lost create response retries without creating a duplicate session');
    assert.equal(await page.locator('#usage-total').textContent(),'未报告');
    await page.selectOption('#usage-scope','all');assert.equal(await page.locator('#usage-total').textContent(),'1,300');
    assert.equal(await page.locator('#sidebar-scrim').isHidden(),true);
    assert.equal(await page.locator('#messages article').count(),1);
    await page.locator('#finish-session').click();await page.locator('#confirm-finish').click();
    await page.waitForFunction(()=>document.querySelector('#session-status').textContent==='已结束');
    assert.equal(await page.locator('#reader-warning').isHidden(),true);
    assert.equal(await page.locator('#send-button').isDisabled(),true);
    assert.equal(await page.locator('#shared-context').isDisabled(),true);
    assert.deepEqual(errors,[]);
    console.log('PASS: real message sync, intervention ACK, pause/resume, provider choices, media task, upload preview, search, skill guide, export, reconnect/draft, mobile layout, session isolation, finish.');
    console.log('UI screenshots: '+screenshots);
  } finally {if(browser)await browser.close();await stop();const target=path.resolve(data);assert.equal(path.dirname(target),path.resolve(os.tmpdir()));assert(path.basename(target).startsWith('agents-talk-browser-'));fs.rmSync(target,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
