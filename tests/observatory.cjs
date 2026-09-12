// Observation windows against an isolated real server. Never writes to port 8765.
const fs=require('fs'),os=require('os'),path=require('path'),assert=require('assert/strict');
const {spawn,spawnSync}=require('child_process');
const {chromium, python, launchOptions}=require('./support.cjs');
const root=path.resolve(__dirname,'..'),data=fs.mkdtempSync(path.join(os.tmpdir(),'agents-talk-observation-'));
const env={...process.env,AGENTS_TALK_DATA:data,AGENTS_TALK_CONFIG:path.join(root,'config.example.json'),PYTHONUTF8:'1',PYTHONDONTWRITEBYTECODE:'1'};
const port=18766,base='http://127.0.0.1:'+port,shots=path.join(root,'.runtime');
let server,browser;
function run(args){const r=spawnSync(python,args,{cwd:root,env,encoding:'utf8',windowsHide:true});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout);}
function post(who,type,...args){return run([path.join(root,'hub.py'),'post','--from',who,'--session','main','--type',type,...args]);}
function start(){server=spawn(python,[path.join(root,'hub.py'),'serve','--port',String(port),'--no-open'],{env,windowsHide:true,stdio:'pipe'});}
async function ready(){for(let i=0;i<100;i++){if(server.exitCode!==null)throw Error('Isolated server exited');try{const r=await fetch(base+'/api/state');await r.arrayBuffer();if(r.ok)return;}catch{}await new Promise(r=>setTimeout(r,100));}throw Error('server timeout');}
async function stop(){if(server&&!server.killed&&server.exitCode===null&&server.signalCode===null){const ended=new Promise(r=>server.once('exit',r));server.kill();await ended;}}
async function state(){return (await fetch(base+'/api/state')).json();}
(async()=>{
  try{
    // Fixture history exists only in the temporary data folder.
    run(['-c',`import hub,json
for i in range(312):
 hub.post({'session':'main','from':['claude','codex','reasonix'][i%3],'type':'say','body':f'隔离验证记录 {i}：对齐接口与验收证据。'})
print(json.dumps(True))`]);
    post('claude','task','--task','API','--to','codex','--reviewer','reasonix','--summary','实现数据接口','--body','实现本地数据接口\n提交接口定义与自动化测试结果。');
    post('claude','task','--task','UI','--to','reasonix','--reviewer','codex','--body','完成桌面与窄屏界面\n共享组件与布局验证。');
    post('claude','task','--task','MERGE','--to','claude','--reviewer','codex','--stage','integration','--depends-on','API,UI','--integration-plan','组合数据接口与界面，执行端到端验证，交付 workspace/release。','--body','整合并交付可运行版本');
    post('claude','task','--task','OLD','--to','reasonix','--body','旧任务：保留未指定安排');
    post('codex','claim','--task','API','--body','开始实现接口');
    post('codex','done','--task','API','--result','数据接口与测试已提交','--body','等待独立审查。');
    post('reasonix','review','--task','API','--verdict','pass','--body','核对接口契约与测试，审查通过。');
    post('reasonix','claim','--task','UI','--body','开始界面实现');
    post('reasonix','done','--task','UI','--body','界面已提交，请验证桌面与窄屏布局。');
    post('claude','say','--body','正在协调最终整合，待 UI 独立验收通过后开始。');
    start();await ready();
    browser=await chromium.launch(launchOptions);
    const page=await browser.newPage({viewport:{width:1600,height:1050},reducedMotion:'reduce'}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base);await page.waitForFunction(()=>!document.querySelector('#send-button').disabled);
    const initial=await page.locator('#message-scroll').boundingBox();assert(initial.height>500,`message viewport too small: ${initial.height}`);
    await page.locator('#message-body').fill('保留我的干预草稿');
    await page.locator('#conversation-expand').click();
    assert(await page.locator('#focus-dialog').evaluate(e=>e.open));
    const focused=await page.locator('#conversation').boundingBox();assert(focused.width>1500&&focused.height>1000);
    await page.keyboard.press('Escape');await page.waitForFunction(()=>document.querySelector('.workbench > #conversation'));
    assert.equal(await page.locator('#message-body').inputValue(),'保留我的干预草稿');
    assert.equal(await page.locator('#conversation').count(),1);
    await page.selectOption('#agent-filter','reasonix');await page.locator('#search-input').fill('审查通过');
    await page.locator('#team-open').click();
    await page.waitForSelector('#team-messages article');
    assert.equal(await page.locator('[data-stage-agent]').count(),4);
    assert((await page.locator('[data-stage-agent="zcode"]').textContent()).includes('未参与'));
    for(const name of ['Claude Code','Codex','Reasonix'])assert((await page.locator('#team-messages').textContent()).includes(name));
    assert.equal(await page.locator('#team-messages article').count(),300,'all-team view must ignore main filters');
    await page.locator('#team-older').click();await page.waitForFunction(()=>document.querySelectorAll('#team-messages article').length>300);
    assert.equal(await page.locator('#team-follow').isChecked(),false);
    await page.locator('#team-scroll').evaluate(e=>e.scrollTop=120);
    const anchor=await page.locator('#team-scroll').evaluate(e=>e.scrollTop);
    const retained=await page.locator('#team-messages article').first().getAttribute('data-id');
    await page.locator('#team-messages article').first().evaluate(e=>e.dataset.retained='yes');
    post('codex','say','--body','实时增量：数据接口已通过独立审查。');
    await page.waitForFunction(()=>document.querySelector('#team-messages').textContent.includes('实时增量'));
    assert(Math.abs(await page.locator('#team-scroll').evaluate(e=>e.scrollTop)-anchor)<5,'new message must not yank history scroll');
    assert.equal(await page.locator(`#team-messages [data-id="${retained}"]`).getAttribute('data-retained'),'yes');
    await page.locator('#team-latest').click();assert(await page.locator('#team-follow').isChecked());
    await page.screenshot({path:path.join(shots,'team-desktop-qa.png')});
    await page.locator('#workflow-tab').click();
    assert.equal(await page.locator('[data-flow-task]').count(),4);
    assert.equal(await page.locator('[data-flow-task="MERGE"]').count(),1,'fan-in must not duplicate integration');
    assert.equal(await page.locator('.flow-level').count(),2);
    const merge=page.locator('[data-flow-task="MERGE"]');
    assert((await merge.textContent()).includes('组合数据接口与界面'));
    assert((await merge.textContent()).includes('尚待验收：UI'));
    assert((await page.locator('[data-flow-task="OLD"]').textContent()).includes('未指定'));
    await page.locator('#workflow-search').fill('MERGE');assert.equal(await page.locator('[data-flow-task]').count(),1);
    await page.locator('[data-flow-target="API"]').click();assert.equal(await page.locator('[data-flow-task]').count(),4);
    assert.equal(await page.evaluate(()=>document.activeElement.dataset.flowTask),'API');
    await page.locator('#workflow-search').fill('<script>');assert.equal(await page.locator('[data-flow-task]').count(),0);
    await page.locator('#workflow-search').fill('');
    const rev=run([path.join(root,'hub.py'),'read','--agent','claude','--session','main','--task','OLD']).tasks[0].revision;
    post('claude','workflow','--task','OLD','--task-revision',String(rev),'--reviewer','codex','--body','补充预定验收人，不改历史交付');
    await page.waitForFunction(()=>document.querySelector('[data-flow-task="OLD"] .flow-assignment').textContent.includes('Codex'));
    await page.locator('[data-flow-task="OLD"] summary').click();
    const oldEvidence=await page.locator('[data-flow-task="OLD"] .flow-evidence').textContent();
    assert.equal((oldEvidence.match(/预定验收：Codex/g)||[]).length,1,'new arrangement must not be attributed to original task');
    post('codex','review','--task','UI','--verdict','pass','--body','完成桌面与窄屏复核，通过。');
    await page.waitForFunction(()=>document.querySelector('[data-flow-task="MERGE"]').textContent.includes('前置交付均已验收通过'));
    assert(await page.locator('[data-flow-task="OLD"] details').evaluate(e=>e.open),'refresh preserves evidence disclosure');
    post('claude','claim','--task','MERGE','--body','合并前置交付并验证');
    post('claude','done','--task','MERGE','--result','workspace/release：整合包与验证报告','--body','整合提交，待独立验收。');
    await page.waitForFunction(()=>document.querySelector('[data-flow-task="MERGE"]').dataset.state==='待审查');
    assert(!(await merge.locator('.flow-review').textContent()).includes('验收通过'));
    post('codex','review','--task','MERGE','--verdict','pass','--body','核对整合包、运行入口与验证报告，通过。');
    await page.waitForFunction(()=>document.querySelector('[data-flow-task="MERGE"]').dataset.state==='已完成');
    assert((await page.locator('#workflow-summary').textContent()).includes('整合验收通过 1 / 1'));
    await page.locator('#workflow-scroll').evaluate(e=>e.scrollTop=0);
    await page.screenshot({path:path.join(shots,'workflow-desktop-qa.png')});
    await stop();await page.waitForFunction(()=>document.querySelector('#observatory-status').textContent.includes('连接中断'));
    assert.equal(await page.locator('[data-flow-task]').count(),4);
    assert(await page.locator('#observatory-intervene').isDisabled());
    start();await ready();await page.waitForFunction(()=>document.querySelector('#observatory-status').dataset.connected==='true');
    await page.setViewportSize({width:390,height:844});
    await page.locator('#workflow-scroll').evaluate(e=>e.scrollTop=0);
    await page.screenshot({path:path.join(shots,'workflow-mobile-qa.png')});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    assert(await page.locator('#workflow-scroll').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
    await page.locator('#team-tab').click();await page.screenshot({path:path.join(shots,'team-mobile-qa.png')});
    assert(await page.locator('#team-scroll').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
    await page.locator('#observatory-intervene').click();
    assert(await page.locator('#focus-dialog').evaluate(e=>e.open));
    assert.equal(await page.locator('#message-type').inputValue(),'intervention');
    assert.equal(await page.locator('#message-body').inputValue(),'保留我的干预草稿');
    await page.locator('#message-body').fill('人工要求：交付前附上验证证据。');
    await page.locator('#send-button').click();
    await page.waitForFunction(()=>document.querySelector('#message-body').value==='');
    assert((await state()).messages.some(m=>m.type==='intervention'&&m.body.includes('人工要求')));
    await page.keyboard.press('Escape');
    await page.setViewportSize({width:1600,height:1050});
    await page.locator('#clear-filters').click();
    await page.evaluate(()=>{document.activeElement?.blur();window.scrollTo(0,0);});
    await page.screenshot({path:path.join(shots,'workspace-observation-qa.png'),fullPage:true});
    // Exercise session switching while a modal is open, even though normal UI closes it first.
    const st=await state();const response=await fetch(base+'/api/session',{method:'POST',headers:{'Content-Type':'application/json','X-Agents-Token':st.csrf},body:JSON.stringify({action:'create',title:'观察窗切换隔离验证',mode:'leader',request_id:'observation-session'})});
    const created=await response.json();assert(response.ok);
    await page.locator('#workflow-open').click();await page.evaluate(id=>switchSession(id),created.session);
    await page.waitForFunction(()=>document.querySelector('#session-title').textContent==='观察窗切换隔离验证');
    assert.equal(await page.locator('#observatory-dialog').evaluate(e=>e.open),false);
    await page.locator('#workflow-open').click();assert.equal(await page.locator('[data-flow-task]').count(),0);
    assert(!(await page.locator('#workflow-tree').textContent()).includes('MERGE'));
    await page.keyboard.press('Escape');
    await page.locator('#finish-session').click();await page.locator('#confirm-finish').click();
    await page.waitForFunction(()=>document.querySelector('#session-status').textContent==='已结束');
    await page.locator('#team-open').click();assert(await page.locator('#observatory-intervene').isDisabled());
    await page.setViewportSize({width:844,height:390});
    assert((await page.locator('#team-scroll').boundingBox()).height>80,'short landscape must retain readable timeline');
    assert.deepEqual(errors,[]);
    console.log('PASS observation: enlarged messages, modal drafts/Esc, unfiltered team/pagination/live scroll, source-backed DAG/review/integration, reconnect, narrow/landscape, intervention, session isolation and ended guard.');
  }finally{
    if(browser)await browser.close();await stop();
    const target=path.resolve(data);assert.equal(path.dirname(target),path.resolve(os.tmpdir()));assert(path.basename(target).startsWith('agents-talk-observation-'));fs.rmSync(target,{recursive:true,force:true});
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
