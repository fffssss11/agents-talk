// Same-client instance management and collaboration against an isolated real server.
const fs=require('fs'),os=require('os'),path=require('path'),assert=require('assert/strict');
const {spawn,spawnSync}=require('child_process');
const {chromium, python, launchOptions}=require('./support.cjs');
const root=path.resolve(__dirname,'..'),data=fs.mkdtempSync(path.join(os.tmpdir(),'agents-talk-instance-ui-'));
const env={...process.env,AGENTS_TALK_DATA:data,AGENTS_TALK_CONFIG:path.join(root,'config.example.json'),PYTHONUTF8:'1',PYTHONDONTWRITEBYTECODE:'1'};
const base='http://127.0.0.1:18767',shots=path.join(root,'.runtime');let server,browser;
const delay=ms=>new Promise(r=>setTimeout(r,ms));
function start(){server=spawn(python,[path.join(root,'hub.py'),'serve','--port','18767','--no-open'],{env,windowsHide:true,stdio:'pipe'});}
async function stop(){if(server&&!server.killed&&server.exitCode===null){const ended=new Promise(r=>server.once('exit',r));server.kill();await ended;}}
async function ready(){for(let i=0;i<100;i++){if(server.exitCode!==null)throw Error('isolated server exited');try{const r=await fetch(base+'/api/state');await r.arrayBuffer();if(r.ok)return;}catch{}await delay(100);}throw Error('timeout');}
async function state(sid='main'){return (await fetch(base+'/api/state?session='+sid)).json();}
async function action(data){const st=await state(data.session||'main');const r=await fetch(base+'/api/session',{method:'POST',headers:{'Content-Type':'application/json','X-Agents-Token':st.csrf},body:JSON.stringify(data)});const result=await r.json();assert(r.ok,JSON.stringify(result));return result;}
function post(who,type,...args){const r=spawnSync(python,[path.join(root,'hub.py'),'post','--from',who,'--session','main','--type',type,...args],{env,encoding:'utf8',windowsHide:true});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout);}
(async()=>{
 try{
  start();await ready();browser=await chromium.launch(launchOptions);
  const page=await browser.newPage({viewport:{width:1600,height:1050},reducedMotion:'reduce'}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);await page.waitForFunction(()=>!document.querySelector('#instances-open').disabled);
  const settled=()=>page.waitForFunction(()=>!document.querySelector('#instance-save').disabled&&!document.querySelector('#instance-result').hidden);
  async function fill(label,role='worker',client='codex'){
   await page.selectOption('#instance-client',client);await page.locator('#instance-name').fill(label);
   await page.locator('#instance-model').fill('gpt6');await page.selectOption('#instance-role',role);
  }
  await page.locator('#instances-open').click();
  await page.locator('[data-instance-edit="codex"]').click();
  assert(await page.locator('#instance-client').isDisabled());
  await page.locator('#instance-name').fill('Codex 统筹');await page.locator('#instance-model').fill('gpt6');await page.selectOption('#instance-role','lead');
  await page.locator('#instance-save').click();await settled();
  assert.equal((await state()).lead,'codex');assert.equal((await state()).agents.codex.model,'gpt6');
  await fill('Codex 实现');await page.locator('#instance-save').click();await settled();
  const worker=Object.entries((await state()).agents).find(([,a])=>a.name==='Codex 实现')[0];
  assert(worker!=='codex'&&worker.startsWith('codex-'));
  assert.equal((await state()).agents[worker].online,false);
  assert.equal(await page.locator(`#lead-select option[value="${worker}"]`).count(),1);
  assert.equal(await page.locator(`#recipient-select option[value="${worker}"]`).count(),1);
  assert.equal(await page.locator(`#context-agent option[value="${worker}"]`).count(),1);
  assert.equal(await page.locator(`#media-recipient option[value="${worker}"]`).count(),1);
  let lost,retry;
  const intercept=async route=>{const body=route.request().postDataJSON();if(body.action==='instance_create'&&!lost){const r=await route.fetch();assert(r.ok());lost={body,result:await r.json()};await route.abort('failed');}else{if(body.action==='instance_create')retry=body;await route.continue();}};
  await page.route('**/api/session',intercept);
  await fill('Codex 独立验收','reviewer');await page.locator('#instance-save').click();
  await page.waitForFunction(()=>!document.querySelector('#instance-error').hidden&&!document.querySelector('#instance-save').disabled);
  const reviewer=lost.result.instance;
  await page.waitForFunction(id=>document.querySelector(`[data-instance="${id}"]`),reviewer);
  assert.equal(Object.keys((await state()).agents).length,6);
  await page.locator('#instance-save').click();await settled();
  assert.equal(retry.request_id,lost.body.request_id);assert.equal(Object.keys((await state()).agents).length,6);
  await page.unroute('**/api/session',intercept);
  await page.screenshot({path:path.join(shots,'instances-desktop-qa.png')});
  await page.locator(`[data-instance-guide="${worker}"]`).click();
  await page.waitForFunction(id=>document.querySelector('#skill-code').textContent.includes(id),worker);
  const guide=await page.locator('#skill-code').textContent();assert(guide.includes('gpt6')&&guide.includes('--from '+worker)&&guide.includes('独立对话'));
  assert.equal(await page.locator('#skill-tabs [data-skill]').count(),6);
  await page.locator('#skills-dialog .modal-close').click();
  post('codex','task','--task','CODE','--to',worker,'--reviewer',reviewer,'--body','实现模块并提交测试结果');
  post('codex','task','--task','PRIVATE','--to',reviewer,'--body','PRIVATE_OTHER_CODEX_CONTEXT');
  post(worker,'claim','--task','CODE','--body','只处理本实例任务');
  post(worker,'say','--to','codex','--body','执行实例：正在验证实现。');
  post(reviewer,'say','--to','codex','--body','验收实例：等待交付证据。');
  await page.waitForFunction(id=>document.querySelector(`#messages [data-sender="${id}"]`),worker);
  assert(!(await page.locator(`#messages [data-sender="${worker}"] .avatar`).first().textContent()).includes('?'));
  await page.locator('#context-preview-open').click();await page.selectOption('#context-agent',worker);
  await page.waitForFunction(()=>document.querySelector('#context-preview').textContent.includes('CODE'));
  assert(!(await page.locator('#context-preview').textContent()).includes('PRIVATE_OTHER_CODEX_CONTEXT'));
  await page.locator('#context-dialog .modal-close').click();
  post(worker,'done','--task','CODE','--body','实现与验证结果已交付');post(reviewer,'review','--task','CODE','--verdict','pass','--body','独立复核证据，通过');
  await page.locator('#workflow-open').click();
  await page.waitForFunction(()=>document.querySelector('[data-flow-task="CODE"]').dataset.state==='已完成');
  const flow=await page.locator('[data-flow-task="CODE"]').textContent();assert(flow.includes(worker)&&flow.includes(reviewer)&&flow.includes('gpt6'));
  await page.locator('#team-tab').click();assert.equal(await page.locator('[data-stage-agent]').count(),6);
  assert((await page.locator(`[data-stage-agent="${worker}"]`).textContent()).includes('gpt6'));
  await page.screenshot({path:path.join(shots,'same-client-team-qa.png')});
  await page.keyboard.press('Escape');
  for(const aid of ['codex',worker,reviewer])post(aid,'usage','--usage-id','same-native-number','--input-tokens','10','--output-tokens','5','--provider','fixture','--model','actual-usage-model','--usage-source','isolated fixture');
  await page.waitForFunction(()=>document.querySelector('#usage-total').textContent==='45');
  assert.equal(await page.locator(`#usage-list [data-usage-agent="${worker}"] .usage-heading>b`).textContent(),'15');
  await page.selectOption('#usage-group','client');assert.equal(await page.locator('#usage-list [data-usage-agent="codex"] .usage-heading>b').textContent(),'45');
  await page.selectOption('#usage-group','instance');
  await page.locator('#instances-open').click();await page.locator(`[data-instance-edit="${worker}"]`).click();
  await page.locator('#instance-model').fill('unsaved local intent');
  let st=await state();await action({action:'instance_update',session:'main',instance:worker,name:'Codex 实现（外部更新）',model:'external label',role:'worker',expected_revision:st.session.instance_revision});
  await page.waitForFunction(()=>!document.querySelector('#instance-stale').hidden);
  assert.equal(await page.locator('#instance-model').inputValue(),'unsaved local intent','poll must preserve local form');
  await page.locator('#instance-save').click();await page.waitForFunction(()=>!document.querySelector('#instance-error').hidden);
  assert.equal((await state()).agents[worker].model,'external label');
  await page.locator(`[data-instance-edit="${worker}"]`).click();assert.equal(await page.locator('#instance-model').inputValue(),'external label');
  await page.locator('#instance-model').fill('gpt6');await page.locator('#instance-save').click();await settled();
  await page.setViewportSize({width:390,height:844});await page.locator('#instances-dialog').evaluate(e=>e.scrollTop=0);
  await page.screenshot({path:path.join(shots,'instances-mobile-qa.png')});
  assert(await page.locator('#instances-dialog').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.locator('#instances-dialog .modal-close').click();
  await page.locator('#team-open').click();await page.screenshot({path:path.join(shots,'same-client-team-mobile-qa.png')});
  assert((await page.locator('#team-scroll').boundingBox()).height>100);
  await page.keyboard.press('Escape');await page.setViewportSize({width:1600,height:1050});
  await page.locator(`[data-participant="${worker}"]`).uncheck();
  await page.waitForFunction(id=>document.querySelector(`#recipient-select option[value="${id}"]`).disabled,worker);
  assert(!(await state()).session.participants.includes(worker));assert((await state()).session.participants.includes(reviewer));
  await page.locator('#instances-open').click();await page.locator('#instance-name').fill('跨重启保留表单');
  await stop();await page.waitForFunction(()=>!document.querySelector('#connection-error').hidden);
  assert(await page.locator('#instance-save').isDisabled());start();await ready();
  await page.waitForFunction(()=>document.querySelector('#connection-error').hidden);
  assert.equal(await page.locator('#instance-name').inputValue(),'跨重启保留表单');assert((await state()).agents[worker]);
  await page.locator('#instances-dialog .modal-close').click();
  const other=await action({action:'create',title:'实例隔离会话',mode:'leader',request_id:'other-session'});
  await page.locator('#instances-open').click();await fill('延迟新增响应');
  let release,arrived;const wait=new Promise(r=>release=r),seen=new Promise(r=>arrived=r);
  const hold=async route=>{const body=route.request().postDataJSON();if(body.action!=='instance_create')return route.continue();const r=await route.fetch();arrived(await r.json());await wait;await route.fulfill({response:r});};
  await page.route('**/api/session',hold);await page.locator('#instance-save').click();const delayed=await seen;
  await page.locator('#instance-form').dispatchEvent('submit');
  await page.evaluate(id=>switchSession(id),other.session);await page.waitForFunction(()=>document.querySelector('#session-title').textContent==='实例隔离会话');
  await page.locator('#instances-open').click();await page.locator('#instance-name').fill('新会话自己的表单');
  release();await delay(250);
  assert.equal(await page.locator('#instance-name').inputValue(),'新会话自己的表单');
  assert.equal(await page.locator('#instance-list [data-instance]').count(),4);
  assert.equal(await page.locator(`#recipient-select option[value="${delayed.instance}"]`).count(),0);
  await page.unroute('**/api/session',hold);
  await page.locator('#instances-dialog .modal-close').click();await page.selectOption('#usage-scope','all');
  assert.equal(await page.locator('#usage-total').textContent(),'45');assert.equal(await page.locator(`#usage-list [data-usage-agent="${worker}"]`).count(),1);
  await page.locator('#finish-session').click();await page.locator('#confirm-finish').click();await page.waitForFunction(()=>document.querySelector('#session-status').textContent==='已结束');
  await page.locator('#instances-open').click();assert(await page.locator('#instance-save').isDisabled());
  assert.deepEqual(errors,[]);
  console.log('PASS instances: same-model roles, unique identities, idempotent create, stale edit guards, dynamic selectors/guides, focused scope, same-client review, token grouping, narrow UI, restart, session races and ended guard.');
 }finally{if(browser)await browser.close();await stop();const target=path.resolve(data);assert.equal(path.dirname(target),path.resolve(os.tmpdir()));assert(path.basename(target).startsWith('agents-talk-instance-ui-'));fs.rmSync(target,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
