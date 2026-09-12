'use strict';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const palette = {claude:['#efe1d3','#9d6c48','✳'],codex:['#deeadb','#54774d','⌘'],reasonix:['#dce5ef','#5b7294','R'],zcode:['#e9e0ef','#876f98','Z'],pi:['#ece9e4','#80766c','π'],human:['#f5e7cd','#a17b40','你']};
const types = {join:'接入',say:'发言',plan:'方案',task:'任务',claim:'认领',progress:'进度',done:'待审查',review:'审查',question:'提问',answer:'回答',decision:'定案',lock:'占用',unlock:'释放',idle:'等待',intervention:'优先干预',ack:'已确认',control:'人工控制',session:'新会话',settings:'设置',capability:'能力报告',blocked:'受阻'};
types.reassign='转交';
types.workflow='协作安排';
types.instance='实例设置';
types.usage='Token 用量';
types.leave='退出读取';
const kinds = {image_generate:'图像生成',image_edit:'图像编辑',video_generate:'视频生成'};
const availability = {available:'可用（成员已报告）',unavailable:'不可用',unverified:'未验证'};
let state, selected = localStorage.getItem('agents-talk.session') || '', limit = 300, mediaTab = false;
let connected = false, activeSync = null, timer, renderKey = '', skills = {}, skillAgent = 'claude';
let pollingGeneration = 0, contextOffset = 0, contextNext = null, contextGeneration = 0, skillsGeneration = 0;
let creating = false, finishSnapshot = null;
let observationMode='team', observationKey='', conversationHome=null;
let editingInstance=null, instanceEditorRevision=-1, instanceEditorView=null, rosterKey='';
const drafts = new Map(), operations = new Map(), sessionRequests = new Map();
function getDraft(id) {
  if(!drafts.has(id)) drafts.set(id,{body:localStorage.getItem('agents-talk.draft.'+id)||'',attachments:[],requestKey:null});
  return drafts.get(id);
}
let draft = getDraft(selected);
function sessionReady() { return connected && !!selected && state?.session.id===selected; }
function snapshot() { return {session:selected,generation:pollingGeneration,csrf:state?.csrf||''}; }
function isCurrent(s) { return s.session===selected && s.generation===pollingGeneration; }
function beginOperation(kind) {
  if(!sessionReady() || operations.has(selected) || (state.session.status==='ended'&&kind!=='create')) return null;
  const op={...snapshot(),kind,draft}; operations.set(op.session,op); updateComposer(); return op;
}
function endOperation(op) {
  if(operations.get(op.session)===op) operations.delete(op.session);
  if(state) render(); else updateComposer();
}
function agentIds() { return Object.keys(state?.agents||{}).filter(id=>id!=='pi'); }
function clientId(id) {return state?.agents?.[id]?.client||state?.usage_agents_all_sessions?.[id]?.client||id;}
function avatar(id) { const [bg, ink, mark] = palette[clientId(id)] || ['#e9eadd','#778063','?']; return `<span class="avatar" style="--avatar-bg:${bg};--avatar-ink:${ink};background:${bg};color:${ink}" aria-hidden="true">${mark}</span>`; }
function name(id) { return id === 'pi' ? '历史 Pi' : id === 'human' ? '你' : id === 'all' ? '所有成员' : state?.agents?.[id]?.name || state?.usage_agents_all_sessions?.[id]?.name || id; }
function instanceLabel(id) {const a=state?.agents?.[id];return name(id)+(a?.model?' · '+a.model:'')+(clientId(id)!==id?' ['+id+']':'');}
function instanceRole(id) {return id===state?.session.lead?'主导':state?.agents[id]?.role==='reviewer'?'验收':'协同';}
function mediaAgents() {return agentIds().filter(id=>['claude','codex'].includes(clientId(id)));}
function displayAgentIds() {
  const rank=id=>id===state.session.lead?0:!state.session.participants.includes(id)?3:clientId(id)===clientId(state.session.lead)?1:2;
  return agentIds().sort((a,b)=>rank(a)-rank(b));
}
function setAgentOptions(id,ids,prefix=[]) {
  const select=$(id),value=select.value;
  const html=[...prefix,...ids.map(a=>[a,instanceLabel(a)])].map(([value,label])=>`<option value="${esc(value)}">${esc(label)}</option>`).join('');
  if(select.dataset.options!==html){select.innerHTML=html;select.dataset.options=html;if([...select.options].some(o=>o.value===value))select.value=value;}
}
function toast(msg, error=false) { const el = document.createElement('div'); el.className='toast'+(error?' error':''); el.textContent=msg; $('toast-region').append(el); while($('toast-region').children.length>2)$('toast-region').firstElementChild.remove();setTimeout(()=>el.remove(),4000); }
function errorAt(id,msg='') { $(id).textContent=msg; $(id).hidden=!msg; }
async function api(path, data, options={}) {
  const response = await fetch(path,{method:data===undefined?'GET':'POST',headers:data===undefined?{}:{'Content-Type':'application/json','X-Agents-Token':options.csrf??state?.csrf??''},body:data===undefined?undefined:JSON.stringify(data),signal:options.signal||AbortSignal.timeout(12000)});
  const result = await response.json();
  if(!response.ok) throw Error(result.error || `请求失败 (${response.status})`);
  return result;
}
async function sessionAPI(op,data) {
  // Keep the latest failed intent stable; changing its payload starts a new intent.
  const key=op.session+':'+(data.action==='create'?'create':data.action.startsWith('instance_')?'instance':'control'), signature=JSON.stringify(data);
  let pending=sessionRequests.get(key);
  if(!pending||pending.signature!==signature) {pending={signature,id:crypto.randomUUID()};sessionRequests.set(key,pending);}
  const result=await api('/api/session',{...data,request_id:pending.id},op);
  if(sessionRequests.get(key)===pending)sessionRequests.delete(key);
  return result;
}
function updateConnection(ok, msg='') {
  connected=ok; $('connection-status').classList.toggle('disconnected',!ok);
  $('connection-status').classList.toggle('connected',ok);
  $('connection-status').querySelector('span').textContent=ok?'实时同步 · 1 秒':'连接中断';
  $('connection-error').hidden=ok; $('connection-error-text').textContent=msg;
  $('sync-label').textContent=ok?'同步于 '+new Date().toLocaleTimeString('zh-CN'):'连接恢复后自动同步';
  $('observatory-status').textContent=ok?'每秒同步':'连接中断 · 暂存画面';
  $('observatory-status').dataset.connected=String(ok);
  updateComposer();
  renderObservatory();
  renderInstances();
}
function sync({fresh=false}={}) {
  if(fresh && activeSync) {activeSync.controller.abort(); activeSync=null;}
  if(activeSync) return activeSync.promise;
  clearTimeout(timer);
  const run={...snapshot(),controller:new AbortController()};
  activeSync=run;
  run.promise=(async()=>{
    try {
      const d=await api('/api/state?limit='+limit+(run.session?'&session='+encodeURIComponent(run.session):''),undefined,{signal:AbortSignal.any([run.controller.signal,AbortSignal.timeout(12000)])});
      if(activeSync!==run || !isCurrent(run)) return false;
      if(run.session && d.session.id!==run.session) throw Error('会话响应不匹配');
      state=d;
      if(selected!==d.session.id) {selected=d.session.id;draft=getDraft(selected);$('message-body').value=draft.body;renderAttachments();}
      localStorage.setItem('agents-talk.session',selected);
      updateConnection(true); render(); return true;
    } catch(e) {
      if(activeSync!==run || !isCurrent(run)) return false;
      if(e.message==='会话不存在' && selected) {switchSession('');return false;}
      updateConnection(false,'暂时无法同步：'+e.message+'。输入内容会保留，正在自动重连。');
      return false;
    } finally {
      if(activeSync===run) {activeSync=null;timer=setTimeout(()=>sync(),1000);}
    }
  })();
  return run.promise;
}
function switchSession(id) {
  closeMenu();
  saveDraft(); selected=id; pollingGeneration++; limit=300; renderKey=''; draft=getDraft(id);
  contextGeneration++; skillsGeneration++; finishSnapshot=null;
  for(const id of ['context-dialog','skills-dialog','finish-dialog','session-dialog','observatory-dialog','focus-dialog','instances-dialog']) $(id).close();
  instanceEditorView=null;
  restoreConversation(); observationKey=''; $('team-messages').replaceChildren(); $('workflow-tree').replaceChildren();
  $('workflow-search').value='';$('team-follow').checked=true;
  $('export-format').value='';
  $('message-body').value=draft.body;
  errorAt('composer-error');renderAttachments();
  connected=false;updateComposer();sync({fresh:true});
}
function saveDraft() {if(selected) {draft.body=$('message-body').value;localStorage.setItem('agents-talk.draft.'+selected,draft.body);}}
function render() {
  if(state.session.id!==selected) {updateComposer();return;}
  const s=state.session;
  $('session-title').textContent=s.title;
  $('session-subtitle').textContent='共享消息实时可见。成员需在各自客户端接入并持续读取黑板。';
  const statuses={active:'协作中',paused:'已发出暂停',ended:'已结束'};
  $('session-status').textContent=statuses[s.status];
  $('pause-resume').textContent=s.status==='paused'?'恢复':'暂停';
  $('mode-select').value=s.mode;
  setAgentOptions('lead-select',agentIds());
  setAgentOptions('agent-filter',agentIds(),[['all','全部成员'],['human','你']]);
  setAgentOptions('recipient-select',agentIds(),[['all','所有成员']]);
  setAgentOptions('media-recipient',mediaAgents());
  setAgentOptions('context-agent',agentIds());
  const nextRoster=JSON.stringify([selected,s.instance_revision]);
  if(rosterKey&&rosterKey!==nextRoster){
    skillsGeneration++;contextGeneration++;
    if($('skills-dialog').open)openSkills();
    if($('context-dialog').open){contextOffset=0;previewContext();}
  }
  rosterKey=nextRoster;
  $('lead-select').value=s.lead;
  if(s.migration_required) $('lead-select').value='';
  $('migration-warning').hidden=!s.migration_required;
  $('migration-warning').textContent=s.migration_required?`${name(s.lead)} 已停用，请选择新的主导成员后继续任务。`:'';
  const members=s.participants||['claude','codex','reasonix'];
  const options=agentIds().map(id=>`<label title="${esc(instanceLabel(id))}"><input type="checkbox" data-participant="${esc(id)}" ${members.includes(id)?'checked':''}> <span>${esc(name(id))}${id===s.lead?' · 主导':''}${clientId(id)!==id?`<small class="participant-instance">${esc(id)}</small>`:''}</span></label>`).join('');
  const memberKey=JSON.stringify([members,s.lead,s.status,options]);
  if($('participant-options').dataset.key!==memberKey){$('participant-options').innerHTML=options;$('participant-options').dataset.key=memberKey;}
  for(const id of ['lead-select','recipient-select','media-recipient']){
    const select=$(id);
    for(const option of select.options)option.disabled=option.value!=='all'&&!members.includes(option.value);
    if(select.selectedOptions[0]?.disabled)select.value=[...select.options].find(o=>!o.disabled)?.value||'';
  }
  $('shared-context').checked=!!s.shared_context;
  $('context-mode-label').textContent=s.shared_context?'开启 · 全队成果摘要':'关闭 · 聚焦主导与自己';
  $('context-description').textContent=s.shared_context?'每个成员可读取全队任务成果、验证与待解决问题，详细记录按需展开。':'其他成员仅接收主导成员和自己的任务信息；主导成员保留全队摘要。';
  $('mode-description').textContent=s.mode==='leader'?'由主导成员拆分任务，成员执行，独立审查。':'成员讨论方案，由主导成员收敛结论。';
  $('agent-count').textContent=Object.values(state.agents).filter(a=>a.online&&members.includes(a.id)).length+' / '+members.length;
  const stalled=Object.values(state.agents).filter(a=>a.needs_attention);
  const onboarding=stalled.length>0&&state.tasks.length===0&&Object.values(state.agents).filter(a=>members.includes(a.id)).every(a=>!a.last_read&&!a.detached&&!a.msgs);
  $('reader-warning').hidden=stalled.length===0;
  $('reader-warning').classList.toggle('onboarding-notice',onboarding);
  $('reader-reconnect').textContent=onboarding?'开始接入':'恢复接入';
  $('reader-warning-text').textContent=onboarding?'尚未接入协作窗口。先选择参与实例，再把各实例的接入说明发到对应客户端；报到和读取后会显示在线状态。':stalled.map(a=>name(a.id)+(a.detached?'已退出读取':a.last_read?'超过 120 秒未读取':'尚无读取记录')).join('；')+'。长工具执行也可能触发，请确认原窗口状态。';
  const agentHTML=displayAgentIds().map(id=>state.agents[id]).map(a=>`<button class="agent-card ${a.online?'online':''}" data-filter="${esc(a.id)}" type="button">${avatar(a.id)}<span class="agent-info"><strong>${esc(name(a.id))}${a.id===s.lead?'<small>主导</small>':''}</strong><span>${esc(a.status)} · ${a.msgs} 条发言</span>${a.model?`<span class="agent-model">模型标注 ${esc(a.model)}</span>`:''}${clientId(a.id)!==a.id?`<span class="agent-instance-id">${esc(a.id)}</span>`:''}</span><i class="agent-presence ${a.online?'online':''}" title="${a.online?'最近 120 秒有心跳':'暂无近期心跳'}"></i></button>`).join('');
  if($('agent-list').innerHTML!==agentHTML) $('agent-list').innerHTML=agentHTML;
  $('session-count').textContent=state.sessions.length;
  const sessionHTML=[...state.sessions].reverse().map(x=>`<button class="session-item ${x.id===selected?'active':''}" data-session="${x.id}" type="button"><span>◌</span><span>${esc(x.title)}<small>${statuses[x.status]}</small></span></button>`).join('');
  if($('session-list').innerHTML!==sessionHTML) $('session-list').innerHTML=sessionHTML;
  $('message-count').textContent=state.total;
  $('conversation-meta').textContent=`${state.total} 条消息 · 已加载 ${state.messages.length}`;
  const key=JSON.stringify([state.revision,selected,limit,$('search-input').value,$('agent-filter').value]);
  if(key!==renderKey) {renderMessages(); renderTasks(); renderCapabilities(); renderUsage(); renderWorkflowSummary(); renderKey=key;}
  renderObservatory();
  renderInstances();
  updateComposer();
}
function bodyHTML(text) {
  return String(text).split(/```/).map((part,i)=>{
    if(i%2===0) return `<span class="body-text">${esc(part)}</span>`;
    const newline=part.indexOf('\n'); const language=newline>=0?part.slice(0,newline):'';
    const code=newline>=0?part.slice(newline+1):part;
    return `<details class="code-block" open><summary>${esc(language||'代码')}<button type="button" class="copy-code">复制</button></summary><pre><code>${esc(code)}</code></pre></details>`;
  }).join('');
}
function mediaHTML(a) {
  const url='/media/'+encodeURIComponent(a.id);
  let view='';
  if(a.mime.startsWith('image/')) view=`<img class="attachment-media" src="${url}" alt="${esc(a.name)}" loading="lazy">`;
  if(a.mime.startsWith('video/')) view=`<video class="attachment-media" src="${url}" controls preload="metadata"></video>`;
  return `<div class="message-attachment">${view}<a class="attachment-link" href="${url}" download="${esc(a.name)}">${esc(a.name)}<small>${(a.size/1024).toFixed(1)} KB · 下载附件</small></a></div>`;
}
function renderMessages(team=false) {
  const scroll=$(team?'team-scroll':'message-scroll'), container=$(team?'team-messages':'messages');
  const nearBottom=team?$('team-follow').checked:scroll.scrollHeight-scroll.scrollTop-scroll.clientHeight<90;
  const search=$('search-input').value.toLocaleLowerCase(), filter=$('agent-filter').value;
  const visible=team?state.messages:state.messages.filter(m=>(filter==='all'||m.from===filter)&&[m.body,m.task,name(m.from),types[m.type]].join(' ').toLocaleLowerCase().includes(search));
  if(!team) {
  $('clear-filters').hidden=!search&&filter==='all'; $('empty-conversation').hidden=state.total>0;
  $('no-results').hidden=visible.length>0||state.total===0;
  $('load-older').hidden=state.messages.length>=state.total||limit>=10000;
  } else {
    $('team-empty').hidden=state.total>0;
    $('team-older').hidden=state.messages.length>=state.total||limit>=10000;
    $('team-meta').textContent=`全部成员 · 已加载 ${state.messages.length} / ${state.total} 条${limit>=10000&&state.total>10000?' · 更早历史请导出查看':''}`;
  }
  const oldNodes=new Map([...container.children].map(n=>[n.dataset.id,n]));
  const anchor=[...container.children].find(n=>n.getBoundingClientRect().bottom>scroll.getBoundingClientRect().top);
  const anchorTop=anchor?.getBoundingClientRect().top;
  const nextNodes=[];
  for(const m of visible) {
    let el=oldNodes.get(m.id);
    if(!el) {
      const [bg,ink]=palette[clientId(m.from)]||palette.human;
      el=document.createElement('article'); el.className='message '+(m.type==='intervention'||m.type==='control'?'intervention':''); el.dataset.id=m.id;
      el.dataset.sender=m.from;
      el.style.setProperty('--avatar-bg',bg); el.style.setProperty('--avatar-ink',ink);
      el.innerHTML=`${avatar(m.from)}<div class="message-main"><div class="message-header"><span class="message-author">${esc(name(m.from))}</span><span class="message-instance" title="当前实例编号和模型标注；实际调用模型以 usage 来源为准"></span><span class="message-recipient">→ ${esc((m.to||['all']).map(instanceLabel).join('、'))}</span><span class="message-type">${esc(types[m.type]||m.type)}</span><time class="message-time" title="${esc(m.ts)}">${new Date(m.ts).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'})}</time></div><div class="message-body">${bodyHTML(m.body||'')}${m.files?.length?'<div class="message-files">'+m.files.map(f=>`<span class="file-chip">${esc(f)}</span>`).join('')+'</div>':''}${m.task?`<div class="message-task">任务 ${esc(m.task)}${m.verdict?' · '+esc(m.verdict):''}</div>`:''}${m.attachments?.length?'<div class="message-attachments">'+m.attachments.map(mediaHTML).join('')+'</div>':''}</div><div class="receipt"></div></div>`;
    }
    el.querySelector('.message-author').textContent=name(m.from);
    el.querySelector('.message-instance').textContent=[state.agents[m.from]?.model?'标注 '+state.agents[m.from].model:'',clientId(m.from)!==m.from?m.from:''].filter(Boolean).join(' · ');
    el.querySelector('.message-recipient').textContent='→ '+(m.to||['all']).map(instanceLabel).join('、');
    if(['intervention','control'].includes(m.type)) {
      const targets=((m.to||['all']).includes('all')?Object.keys(state.agents):m.to).filter(a=>(state.session.participants||Object.keys(state.agents)).includes(a));
      // ACKs may be outside the loaded message window, so the server supplies receipts.
      const acked=state.receipts?.[m.id]||state.messages.filter(a=>a.type==='ack'&&a.reply_to===m.id).map(a=>a.from);
      el.querySelector('.receipt').textContent=targets.map(a=>name(a)+(acked.includes(a)?' 已确认':' 待确认')).join(' · ');
    }
    nextNodes.push(el);
  }
  // Keep unchanged nodes attached so a new message does not interrupt video playback.
  const wanted=new Set(nextNodes);
  for(const node of [...container.children]) if(!wanted.has(node)) node.remove();
  nextNodes.forEach((node,index)=>{const current=container.children[index];if(current!==node)container.insertBefore(node,current||null);});
  if(!nearBottom&&anchor?.isConnected) scroll.scrollTop+=anchor.getBoundingClientRect().top-anchorTop;
  const view=snapshot();
  if(nearBottom) requestAnimationFrame(()=>{if(!isCurrent(view)||(team&&(!$('team-follow').checked||!$('observatory-dialog').open)))return;scroll.scrollTop=scroll.scrollHeight;if(!team)$('jump-latest').hidden=true;});
  else if(!team&&visible.length) $('jump-latest').hidden=false;
}
function renderTasks() {
  const expanded=new Map([...$('task-list').querySelectorAll('details[data-task]')].map(d=>[d.dataset.task,d.open]));
  const tasks=state.tasks, done=tasks.filter(t=>t.state==='已完成').length;
  $('task-count').textContent=$('task-total').textContent=tasks.length;
  $('task-summary-label').textContent=tasks.length?'已完成任务':'等待任务';
  $('task-progress-label').textContent=`${done} / ${tasks.length}`;
  const pct=tasks.length?Math.round(done/tasks.length*100):0;
  $('task-progress').setAttribute('aria-valuenow',pct); $('task-progress').firstElementChild.style.width=pct+'%';
  $('task-list').innerHTML=tasks.length?[...tasks].reverse().map(t=>`<details class="task-item" data-task="${esc(t.id)}" ${(expanded.get(t.id)??true)?'open':''}><summary class="task-item-heading"><span class="task-state-icon ${t.state==='已完成'?'complete':''}">${t.state==='已完成'?'✓':'◷'}</span><h3>${esc(t.title)}</h3></summary><p>${esc(t.body)}</p><div class="task-item-footer"><span class="task-owner">${avatar(t.owner)}<span>${esc(instanceLabel(t.owner))}</span></span><span>${esc(t.state)}</span></div><div class="task-kind">${esc(t.id)}${t.kind?' · '+kinds[t.kind]:''}</div>${t.log.map(e=>`<p class="task-log">${esc(types[e.type])} · ${esc(e.body)}</p>`).join('')}</details>`).join(''):'<div class="compact-empty"><span>▦</span><h3>下一步，逐渐清晰</h3><p>成员创建任务后，负责人和进度会在这里更新。</p></div>';
  const locks=Object.entries(state.locks); $('lock-count').textContent=locks.length;
  for(const t of tasks){
    const taskNode=[...$('task-list').querySelectorAll('[data-task]')].find(el=>el.dataset.task===t.id);
    if(taskNode && (t.depends_on?.length || typeof t.ready==='boolean')) {
      const dependency=document.createElement('div');dependency.className='task-dependencies';
      const waiting=t.waiting_for||[];
      dependency.dataset.ready=String(t.ready);
      dependency.textContent=[t.depends_on?.length?'依赖：'+t.depends_on.join('、'):'',waiting.length?'等待：'+waiting.join('、'):t.ready===true?'依赖已满足':t.ready===false?'依赖未就绪':''].filter(Boolean).join(' · ');
      taskNode.append(dependency);
    }
    if(state.session.status==='ended'||state.session.participants?.includes(t.owner)||!['待办','受阻','被打回'].includes(t.state))continue;
    if(taskNode){const button=document.createElement('button');button.type='button';button.className='text-button';button.dataset.reassign=t.id;button.textContent='负责人未参与 · 转交主导成员';taskNode.append(button);}
  }
  $('lock-list').innerHTML=locks.length?locks.map(([p,o])=>`<div class="lock-entry"><code>${esc(p)}</code><span>${esc(name(o.agent))} · 会话 ${esc(o.session)}</span></div>`).join(''):'<p class="context-empty">暂无占用中的文件</p>';
}
function renderWorkflowSummary() {
  const tasks=state.tasks, integrations=tasks.filter(t=>t.stage==='integration');
  const pending=tasks.filter(t=>t.state==='待审查').length;
  $('workflow-summary').innerHTML=`<div class="workflow-lead">${avatar(state.session.lead)}<div><small>当前主导</small><strong>${esc(name(state.session.lead))}</strong></div></div><div class="workflow-metrics"><span><b>${tasks.length}</b>任务</span><span><b>${pending}</b>待验收</span><span><b>${integrations.length}</b>整合节点</span></div><p>${integrations.length?`整合验收通过 ${integrations.filter(t=>t.state==='已完成').length} / ${integrations.length}`:'最终整合安排：未指定'}</p>`;
}
function setObservationMode(mode) {
  observationMode=mode; observationKey='';
  for(const [id,on] of [['team',mode==='team'],['workflow',mode==='workflow']]) {
    $(id+'-view').hidden=!on; $(id+'-tab').setAttribute('aria-selected',String(on));$(id+'-tab').tabIndex=on?0:-1;
  }
  renderObservatory();
}
function openObservatory(mode) {
  if(!state||state.session.id!==selected)return;
  closeMenu(); $('observatory-dialog').showModal();setObservationMode(mode);
}
function renderObservatory() {
  if(!$('observatory-dialog').open||!state||state.session.id!==selected)return;
  $('observatory-session').textContent=state.session.title+' · '+({active:'协作中',paused:'已暂停',ended:'已结束'}[state.session.status]||state.session.status);
  $('observatory-intervene').disabled=!sessionReady()||state.session.status==='ended'||operations.has(selected);
  if(observationMode==='team') {
    // Presence changes independently from board revision. Never invent typing or work activity.
    const members=state.session.participants||[], recent=new Map();
    for(const m of state.messages) if(m.body)recent.set(m.from,m);
    const html=displayAgentIds().map(id=>{
      const a=state.agents[id],m=recent.get(id),active=members.includes(id);
      return `<article class="stage-agent ${active?'':'not-participating'}" data-stage-agent="${esc(id)}"><div class="stage-agent-heading">${avatar(id)}<div><strong>${esc(name(id))}</strong><small>${active?instanceRole(id):'未参与'}${a.model?' · 标注 '+esc(a.model):''}</small></div><i class="stage-presence ${connected&&active&&a.online?'online':''}" title="${connected?'近期心跳以成员上报为准':'服务断线，状态未更新'}"></i></div>${clientId(id)!==id?`<p class="stage-instance-id">${esc(id)}</p>`:''}<p class="stage-status">${esc(active?a.status:'本会话未启用')}${!connected?' · 状态未更新':''}</p><p class="stage-quote">${m?esc((m.body||'').slice(0,130)):active?'已加载记录中暂无共享发言':'未分配新任务'}</p><small>${m?'最近共享 · '+esc(types[m.type]||m.type)+' · '+esc(new Date(m.ts).toLocaleTimeString('zh-CN')):'等待共享记录'}</small></article>`;
    }).join('');
    if($('team-stage').innerHTML!==html)$('team-stage').innerHTML=html;
  }
  const key=JSON.stringify([selected,observationMode,observationMode==='team'?[state.revision,limit]:[state.session.lead,state.session.instance_revision,state.tasks,$('workflow-search').value]]);
  if(key===observationKey)return;
  if(observationMode==='team')renderMessages(true);else renderWorkflowTree();
  observationKey=key;
}
function renderWorkflowTree() {
  const tasks=state.tasks, byId=new Map(tasks.map(t=>[t.id,t])), level=new Map(), remaining=new Map(byId);
  // Each task appears once; dependency chips connect fan-in/fan-out across levels.
  // Old or damaged graphs remain visible without recursive traversal.
  while(remaining.size) {
    let changed=false;
    for(const [id,t] of remaining) {
      const deps=t.depends_on||[];
      if(deps.every(d=>level.has(d))) {level.set(id,deps.length?Math.max(...deps.map(d=>level.get(d)))+1:0);remaining.delete(id);changed=true;}
    }
    if(!changed)break;
  }
  const search=$('workflow-search').value.trim().toLocaleLowerCase();
  const matches=t=>[t.id,t.title,t.body,t.from,name(t.from),t.owner,name(t.owner),t.reviewer,name(t.reviewer),t.integration_plan].join(' ').toLocaleLowerCase().includes(search);
  const visible=tasks.filter(matches), expanded=new Set([...$('workflow-tree').querySelectorAll('details[open]')].map(n=>n.dataset.evidence));
  $('workflow-meta').textContent=`${tasks.length} 项任务 · ${tasks.filter(t=>t.state==='已完成').length} 项验收通过${search?' · 匹配 '+visible.length+' 项':''} · 点击依赖编号定位`;
  function member(id) {return id?`<span class="flow-person" title="${esc(instanceLabel(id))}">${avatar(id)}<span>${esc(name(id))}${clientId(id)!==id?`<small>${esc(id)}</small>`:''}${state.agents[id]?.model?`<small>标注 ${esc(state.agents[id].model)}</small>`:''}</span></span>`:'<span class="unspecified">未指定</span>';}
  function link(id) {return `<button type="button" class="dependency-link" data-flow-target="${esc(id)}">${esc(id)}</button>`;}
  function card(t) {
    const logs=t.log||[],review=[...logs].reverse().find(e=>e.type==='review'),done=[...logs].reverse().find(e=>e.type==='done');
    const reassign=[...logs].reverse().find(e=>e.type==='reassign');
    const integrations=tasks.filter(n=>n.stage==='integration'&&(n.depends_on||[]).includes(t.id));
    const currentReview=review&&t.state==='已完成'&&review.verdict==='pass';
    const deps=t.depends_on||[], waiting=t.waiting_for||[];
    const record=[{from:t.from,body:t.body,id:t.source_id,type:'task',...(t.initial_workflow||{})},...logs].filter(e=>['task','workflow','reassign','done','review','blocked'].includes(e.type));
    return `<article class="flow-task ${t.stage==='integration'?'integration-task':''}" data-flow-task="${esc(t.id)}" tabindex="-1" data-state="${esc(t.state)}"><header><span class="flow-id">${esc(t.id)} · ${t.stage==='integration'?'整合':'执行'}</span><span class="flow-state">${esc(t.state)}</span></header><h3>${esc(t.title)}</h3><div class="flow-assignment"><div><small>原始派发</small>${member(t.from)}</div><span aria-hidden="true">→</span><div><small>当前执行${reassign?' · 已转交':''}</small>${member(t.owner)}</div><span aria-hidden="true">→</span><div><small>预定验收</small>${member(t.reviewer)}</div></div><div class="flow-review"><strong>${currentReview?'验收通过':review?'最近审查记录':'尚无审查记录'}</strong>${review?`<span>${esc(name(review.from))} · ${review.verdict==='pass'?'通过':'退回'}${!currentReview?' · 以当前任务状态为准':''}</span>`:'<span>等待执行交付与独立审查</span>'}</div>${deps.length?`<div class="flow-dependencies"><small>前置交付</small>${deps.map(link).join('')}<p>${waiting.length?'尚待验收：'+esc(waiting.join('、')):'前置交付均已验收通过'}</p></div>`:''}<div class="flow-integration"><small>${t.stage==='integration'?'整合方式与最终交付':'后续整合'}</small><p>${t.integration_plan?esc(t.integration_plan):t.stage==='integration'?'<span class="unspecified">整合方式未指定</span>':integrations.length?integrations.map(n=>link(n.id)+' · '+esc(name(n.owner))).join('；'):'<span class="unspecified">未指定</span>'}</p></div>${done?`<p class="flow-result"><small>最近提交${t.state==='已完成'?'':' · 未代表当前验收通过'}</small>${esc((done.result||done.body||'').slice(0,180))}</p>`:''}<details class="flow-evidence" data-evidence="${esc(t.id)}" ${expanded.has(t.id)?'open':''}><summary>查看任务与记录依据 · ${record.length}</summary>${record.map(e=>`<div><small>${esc(types[e.type]||e.type)} · ${esc(name(e.from))} · ${esc(e.id||'旧记录未标识')}</small><p>${esc(e.body)}</p>${'reviewer' in e?`<p>预定验收：${esc(e.reviewer?name(e.reviewer):'未指定')}</p>`:''}${'stage' in e?`<p>阶段类型：${e.stage==='integration'?'整合':'执行'}</p>`:''}${'integration_plan' in e?`<p>整合说明：${esc(e.integration_plan||'未指定')}</p>`:''}</div>`).join('')}</details></article>`;
  }
  const groups=[...new Set(visible.map(t=>level.has(t.id)?level.get(t.id):-1))].sort((a,b)=>a<0?1:b<0?-1:a-b);
  $('workflow-tree').innerHTML=`<div class="flow-root">${avatar(state.session.lead)}<div><small>当前统筹</small><strong>${esc(name(state.session.lead))}</strong><p>各任务保留实际派发记录；待审查不计入已完成。</p></div><span>${tasks.filter(t=>t.state==='已完成').length} / ${tasks.length}</span></div>${groups.map(l=>`<section class="flow-level"><h3>${l<0?'依赖记录异常，需主导核对':'阶段 '+(l+1)}<small>${l===0?'无前置依赖':l>0?'前置交付通过后推进':''}</small></h3><div class="flow-grid">${visible.filter(t=>(level.get(t.id)??-1)===l).map(card).join('')}</div></section>`).join('')}${!visible.length?`<p class="observation-empty">${tasks.length?'没有匹配的任务。清空关键词查看完整工作树。':'尚未发布任务。主导创建正式任务后，派工与验收流程将在这里展开。'}</p>`:''}${!tasks.some(t=>t.stage==='integration')?'<div class="integration-unset">最终整合安排未指定。主导需发布带 depends_on 的整合任务并标记 stage=integration，记录整合负责人、方案和独立验收人。</div>':''}`;
}
function restoreConversation() {
  if(!conversationHome)return;
  conversationHome.replaceWith($('conversation'));conversationHome=null;
  $('conversation-expand').textContent='放大阅读 ↗';$('conversation-expand').setAttribute('aria-expanded','false');
}
function renderInstances() {
  if(!$('instances-dialog').open||!state||state.session.id!==selected)return;
  const html=displayAgentIds().map(id=>{const a=state.agents[id],busy=operations.has(selected),enabled=state.session.participants.includes(id);
    return `<article class="instance-entry" data-instance="${esc(id)}"><div class="instance-entry-main">${avatar(id)}<div><strong>${esc(name(id))}<span class="count-badge">${instanceRole(id)}</span></strong><code>${esc(id)}</code><p>${esc(state.clients?.[clientId(id)]?.name||clientId(id))} · 模型标注 ${esc(a.model||'未填写')} · ${enabled?'已参与':'未参与'}</p></div></div><div class="instance-entry-actions"><button type="button" class="button button-white small-button" data-instance-edit="${esc(id)}" ${!sessionReady()||busy||state.session.status==='ended'?'disabled':''}>编辑</button><button type="button" class="button button-white small-button" data-instance-guide="${esc(id)}" ${!sessionReady()||busy?'disabled':''}>接入说明</button></div></article>`;
  }).join('');
  if($('instance-list').innerHTML!==html)$('instance-list').innerHTML=html;
  $('instance-stale').hidden=!instanceEditorView||(state.session.instance_revision??-1)===instanceEditorRevision;
}
function editInstance(id=null) {
  if(!sessionReady()||operations.has(selected))return;
  const a=id?state.agents[id]:null;if(id&&!a)return;
  editingInstance=id;instanceEditorRevision=state.session.instance_revision??-1;instanceEditorView=snapshot();
  sessionRequests.delete(selected+':instance');
  $('instance-editor-title').textContent=id?'编辑 '+name(id):'新增实例';$('instance-save').textContent=id?'保存实例':'创建实例';
  $('instance-client').value=a?clientId(id):(state.agents[state.session.lead]?.client||'codex');
  $('instance-name').value=a?.name||'';$('instance-model').value=a?.model||'';
  $('instance-role').value=id===state.session.lead?'lead':a?.role==='reviewer'?'reviewer':'worker';
  errorAt('instance-error');$('instance-result').hidden=true;renderInstances();updateComposer();
}
$('instances-open').onclick=()=>{if(!sessionReady())return;closeMenu();$('instances-dialog').showModal();editInstance();renderInstances();};
$('instance-new').onclick=()=>editInstance();
$('instances-dialog').onclose=()=>{if(!$('instances-dialog').open)instanceEditorView=null;};
$('instance-list').onclick=e=>{
  const edit=e.target.closest('[data-instance-edit]'),guide=e.target.closest('[data-instance-guide]');
  if(edit){editInstance(edit.dataset.instanceEdit);$('instance-name').focus();}
  if(guide&&sessionReady()&&!operations.has(selected)){skillAgent=guide.dataset.instanceGuide;$('instances-dialog').close();openSkills();}
};
$('instance-form').onsubmit=async e=>{
  e.preventDefault();if(!$('instances-dialog').open||!instanceEditorView||!isCurrent(instanceEditorView))return;
  const op=beginOperation('instance');if(!op)return;
  const data={action:editingInstance?'instance_update':'instance_create',session:op.session,expected_revision:instanceEditorRevision,
    name:$('instance-name').value,model:$('instance-model').value,role:$('instance-role').value};
  if(editingInstance)data.instance=editingInstance;else data.client=$('instance-client').value;
  errorAt('instance-error');$('instance-result').hidden=true;
  try {
    const result=await sessionAPI(op,data);
    if(isCurrent(op)){renderKey='';await sync({fresh:true});if(isCurrent(op)){
      // Release the local form lock before initializing the next, independent intent.
      endOperation(op);if($('instances-dialog').open&&sessionReady())editInstance();
      $('instance-result').textContent=`已记录实例 ${result.instance}。点击该实例“接入说明”，复制到对应客户端的独立对话中；此操作未启动模型调用。`;
      $('instance-result').hidden=false;
    }}
  }catch(e){if(isCurrent(op))errorAt('instance-error',e.message+'。请求结果不确定时保留表单重试，修改前先核对列表，避免重复创建。');}
  finally{endOperation(op);}
};
function renderCapabilities() {
  $('capability-list').innerHTML=mediaAgents().map(id=>`<div class="capability-agent"><div class="capability-agent-heading">${avatar(id)}${esc(instanceLabel(id))}</div><div class="capability-tags">${Object.entries(kinds).map(([kind,title])=>{const c=state.agents[id]?.capabilities[kind];return `<div class="capability-row" title="${esc(c?.detail||'成员尚未验证当前工具')}"><span>${title}</span><span class="capability-value ${c?.status==='available'?'':'unverified'}">${availability[c?.status||'unverified']}</span></div>`;}).join('')}</div></div>`).join('');
}
function renderUsage(){
  const all=$('usage-scope').value==='all',group=$('usage-group').value==='client';
  const data=(group?(all?state.token_usage_clients_all_sessions:state.token_usage_clients):(all?state.token_usage_all_sessions:state.token_usage))||{};
  const actors=(group?state.clients:all?state.usage_agents_all_sessions:state.agents)||state.agents;
  const fmt=n=>n==null?'未报告':Number(n).toLocaleString('zh-CN');
   const rows=Object.entries(actors).filter(([id])=>id!=='pi').map(([id,a])=>[id,a,data[id]||{}]);
  const reports=rows.reduce((n,[,,u])=>n+(u.reports||0),0);
  $('usage-total').textContent=reports?fmt(rows.reduce((n,[,,u])=>n+(u.total||0),0)):'未报告';
  $('usage-list').innerHTML=rows.map(([id,a,u])=>`<div class="usage-row" data-usage-agent="${esc(id)}"><div class="usage-heading">${avatar(id)}<strong>${esc(a.name)}</strong><b>${fmt(u.total)}</b></div>${!group&&a.client&&a.client!==id?`<div class="usage-meta">${esc(id)}</div>`:''}<div class="usage-numbers"><span>输入 <b>${fmt(u.input)}</b></span><span>输出 <b>${fmt(u.output)}</b></span></div><div class="usage-meta">${u.reports||0} 次调用已报告 · 看板发言估算 ≈${fmt(u.board_output_estimate||0)}</div>${u.reports?`<details class="usage-sources"><summary>来源与明细</summary><p>缓存输入 ${fmt(u.cached_input)} · 推理输出 ${fmt(u.reasoning_output)}</p>${(u.sources||[]).map(s=>`<p>${esc(s.provider)} / ${esc(s.model)}<br>${esc(s.source)}</p>`).join('')}</details>`:''}</div>`).join('');
}
$('usage-scope').onchange=$('usage-group').onchange=()=>{if(state)renderUsage();};
function updateComposer() {
  const ready=sessionReady(), busy=operations.has(selected);
  const ended=state?.session.status==='ended';
  const locked=!ready||busy||ended;
  $('instances-open').disabled=!ready||busy;
  for(const id of ['instance-name','instance-model','instance-role','instance-save','instance-new'])$(id).disabled=locked;
  $('instance-client').disabled=locked||!!editingInstance;
  $('observatory-intervene').disabled=locked;
  $('send-button').disabled=locked;
  $('attach-button').disabled=$('file-input').disabled=locked;
  $('message-body').disabled=busy||!selected||(ready&&ended);
  for(const id of ['mode-select','lead-select','shared-context','pause-resume','finish-session','confirm-finish','tab-message','tab-media','media-kind','media-recipient','recipient-select','message-type']) $(id).disabled=locked;
  $('participant-options').querySelectorAll('input').forEach(el=>el.disabled=locked||el.dataset.participant===state?.session.lead);
  $('task-list').querySelectorAll('[data-reassign]').forEach(el=>el.disabled=locked||!!state?.session.migration_required);
  for(const id of ['skills-open','empty-guide','reader-reconnect','context-preview-open','export-format']) $(id).disabled=!ready;
  $('new-session').disabled=$('create-session-submit').disabled=!ready||busy||creating;
  $('new-session-title').disabled=$('new-session-mode').disabled=creating;
  $('message-form').setAttribute('aria-busy',String(busy));
  $('send-label').textContent=busy?'正在发送…':mediaTab?'创建媒体任务':'发送消息';
  const cap=state?.agents[$('media-recipient').value]?.capabilities[$('media-kind').value];
  $('media-capability').textContent=availability[cap?.status||'unverified'];
  let note=ended?'会话已结束，仍可查看与导出记录。':state?.session.status==='paused'?'协作暂停中，可补充要求；恢复后成员才能继续工作。':mediaTab?'将创建待办任务。成员确认工具可用后才会认领，面板不会自行调用生成服务。':$('message-type').value==='intervention'?'成员下次读取时收到要求，需明确确认。正在执行的外部工具无法即时中断。':'';
  $('composer-notice').textContent=note; $('composer-notice').hidden=!note;
  if(mediaTab && state?.session.status==='paused') $('send-button').disabled=true;
  if(mediaTab && state?.session.migration_required) {$('send-button').disabled=true;$('composer-notice').textContent='请先选择新的主导成员，再创建媒体任务。';$('composer-notice').hidden=false;}
  if(mediaTab && !$('media-recipient').value)$('send-button').disabled=true;
}
function setTab(media) {
  if(operations.has(selected)) return;
  mediaTab=media; draft.requestKey=null; $('message-options').hidden=media; $('media-options').hidden=!media;
  for(const [id,on] of [['tab-message',!media],['tab-media',media]]) {$(id).classList.toggle('selected',on); $(id).setAttribute('aria-selected',on); $(id).tabIndex=on?0:-1;}
  updateComposer();
}
function renderAttachments() {
  $('attachment-list').innerHTML=draft.attachments.map((a,i)=>`<div class="pending-attachment">${a.mime.startsWith('image/')?`<img src="/media/${encodeURIComponent(a.id)}" alt="${esc(a.name)}">`:'<div class="file-icon">▧</div>'}<span class="pending-attachment-name">${esc(a.name)}</span><span class="pending-attachment-status">已上传 · ${(a.size/1024).toFixed(1)} KB</span><button class="remove-attachment" type="button" data-remove="${i}" aria-label="移除 ${esc(a.name)}">×</button></div>`).join('');
}
$('message-form').addEventListener('submit',async e=>{
  e.preventDefault(); if(!sessionReady()||operations.has(selected)||state.session.status==='ended'||(mediaTab&&(state.session.status==='paused'||state.session.migration_required))) return;
  const body=$('message-body').value.trim(); if(!body) return errorAt('composer-error','请写下需求或消息内容。');
  saveDraft(); const op=beginOperation('send'); if(!op)return;
  errorAt('composer-error');
  const data={session:op.session,type:mediaTab?'task':$('message-type').value,to:[mediaTab?$('media-recipient').value:$('recipient-select').value],body,attachments:op.draft.attachments.map(a=>a.id)};
  if(mediaTab)data.kind=$('media-kind').value;
  const signature=JSON.stringify(data);
  if(!op.draft.requestKey||op.draft.requestPayload!==signature)op.draft.requestKey=crypto.randomUUID();
  op.draft.requestPayload=signature;data.request_id=op.draft.requestKey;
  if(mediaTab)data.task='M-'+data.request_id.slice(0,12);
  try {
    await api('/api/post',data,op);
    // Commit only to the captured draft, including its storage key.
    op.draft.body='';op.draft.attachments=[];op.draft.requestKey=null;
    localStorage.setItem('agents-talk.draft.'+op.session,'');
    if(draft===op.draft) {$('message-body').value='';renderAttachments();}
    if(isCurrent(op)) {toast(data.kind?'媒体任务已创建，等待成员接单。':'消息已发布。');renderKey='';await sync({fresh:true});}
  } catch(e) {if(isCurrent(op))errorAt('composer-error',e.message);}
  finally {endOperation(op);}
});
$('message-body').addEventListener('input',()=>{saveDraft();draft.requestKey=null;});
$('message-body').addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){e.preventDefault();$('message-form').requestSubmit();}});
$('tab-message').onclick=()=>setTab(false); $('tab-media').onclick=()=>setTab(true);
for(const id of ['tab-message','tab-media']) $(id).addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();setTab(!mediaTab);$(mediaTab?'tab-media':'tab-message').focus();}});
for(const id of ['media-kind','media-recipient','recipient-select','message-type']) $(id).onchange=()=>{if(!operations.has(selected))draft.requestKey=null;updateComposer();};
$('attach-button').onclick=()=>$('file-input').click();
$('file-input').onchange=async()=>{
  const files=[...$('file-input').files];$('file-input').value='';
  if(!files.length||!sessionReady()||operations.has(selected))return;
  if(draft.attachments.length+files.length>8) return errorAt('composer-error','单条消息最多 8 个附件。');
  const op=beginOperation('upload');if(!op)return;errorAt('composer-error');
  try {for(const file of files) {if(file.size>32*1024*1024) throw Error(file.name+' 超过 32 MB');const r=await fetch('/api/upload?name='+encodeURIComponent(file.name),{method:'POST',headers:{'X-Agents-Token':op.csrf},body:file,signal:AbortSignal.timeout(60000)});const a=await r.json();if(!r.ok) throw Error(a.error);op.draft.attachments.push(a);op.draft.requestKey=null;if(draft===op.draft)renderAttachments();}}
  catch(e){if(isCurrent(op))errorAt('composer-error',e.message);}
  finally{endOperation(op);}
};
$('attachment-list').onclick=e=>{const b=e.target.closest('[data-remove]');if(b&&!operations.has(selected)){draft.attachments.splice(Number(b.dataset.remove),1);draft.requestKey=null;renderAttachments();}};
$('messages').onclick=$('team-messages').onclick=async e=>{const b=e.target.closest('.copy-code');if(b){e.preventDefault();try{await navigator.clipboard.writeText(b.closest('.code-block').querySelector('code').textContent);b.textContent='已复制';setTimeout(()=>b.textContent='复制',2000);}catch{b.textContent='请手动复制';}}};
$('search-input').oninput=$('agent-filter').onchange=()=>{renderKey='';if(state)render();};
$('clear-filters').onclick=()=>{$('search-input').value='';$('agent-filter').value='all';renderKey='';render();};
$('agent-list').onclick=e=>{const b=e.target.closest('[data-filter]');if(b){$('agent-filter').value=b.dataset.filter;renderKey='';render();}};
$('session-list').onclick=e=>{const b=e.target.closest('[data-session]');if(b)switchSession(b.dataset.session);};
$('load-older').onclick=()=>{limit=Math.min(10000,limit+300);renderKey='';sync({fresh:true});};
$('team-older').onclick=()=>{$('team-follow').checked=false;limit=Math.min(10000,limit+300);observationKey='';sync({fresh:true});};
$('team-latest').onclick=()=>{$('team-follow').checked=true;$('team-scroll').scrollTop=$('team-scroll').scrollHeight;};
$('team-follow').onchange=()=>{if($('team-follow').checked)$('team-latest').click();};
$('team-scroll').onscroll=()=>{const s=$('team-scroll');if(s.scrollHeight-s.scrollTop-s.clientHeight>90)$('team-follow').checked=false;};
for(const id of ['team-open','team-nav'])$(id).onclick=()=>openObservatory('team');
for(const id of ['workflow-open','workflow-nav','workflow-preview-open'])$(id).onclick=()=>openObservatory('workflow');
$('team-tab').onclick=()=>setObservationMode('team');$('workflow-tab').onclick=()=>setObservationMode('workflow');
for(const id of ['team-tab','workflow-tab'])$(id).onkeydown=e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();setObservationMode(observationMode==='team'?'workflow':'team');$(observationMode+'-tab').focus();}};
$('workflow-search').oninput=()=>{observationKey='';renderObservatory();};
$('workflow-tree').onclick=e=>{
  const link=e.target.closest('[data-flow-target]');if(!link)return;
  $('workflow-search').value='';observationKey='';renderObservatory();
  const target=[...$('workflow-tree').querySelectorAll('[data-flow-task]')].find(n=>n.dataset.flowTask===link.dataset.flowTarget);
  if(target){target.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});target.focus({preventScroll:true});}
};
$('conversation-expand').onclick=()=>{
  if($('focus-dialog').open){$('focus-dialog').close();restoreConversation();return;}
  const scroll=$('message-scroll'),top=scroll.scrollTop;
  conversationHome=document.createComment('conversation home');$('conversation').before(conversationHome);
  $('focus-dialog').append($('conversation'));$('focus-dialog').showModal();
  $('conversation-expand').textContent='退出放大 ×';$('conversation-expand').setAttribute('aria-expanded','true');scroll.scrollTop=top;
};
$('focus-dialog').onclose=()=>{if(!$('focus-dialog').open)restoreConversation();};
$('observatory-intervene').onclick=()=>{
  if(!sessionReady()||state.session.status==='ended'||operations.has(selected))return;
  $('observatory-dialog').close();setTab(false);$('message-type').value='intervention';$('recipient-select').value='all';updateComposer();
  $('conversation-expand').click();$('message-body').focus();
};
$('jump-latest').onclick=()=>{$('message-scroll').scrollTop=$('message-scroll').scrollHeight;$('jump-latest').hidden=true;};
$('message-scroll').onscroll=()=>{const s=$('message-scroll');if(s.scrollHeight-s.scrollTop-s.clientHeight<90)$('jump-latest').hidden=true;};
$('retry-connection').onclick=sync;
async function control(action,extra={},message='') {
  const op=beginOperation('settings');if(!op)return;
  try {
    await sessionAPI(op,{action,session:op.session,...extra});
    if(isCurrent(op)) {renderKey='';await sync({fresh:true});if(isCurrent(op)&&message)toast(message);}
  } catch(e) {if(isCurrent(op))toast(e.message,true);}
  finally {endOperation(op);}
}
$('task-list').addEventListener('click',async e=>{
  const b=e.target.closest('[data-reassign]');if(!b)return;
  if(!sessionReady()||state.session.migration_required)return;
  await control('reassign',{task:b.dataset.reassign,to:state.session.lead},'任务已转交主导成员，历史记录已保留。');
});
$('participant-options').onchange=async e=>{
  if(!e.target.dataset.participant)return;
  const members=[...$('participant-options').querySelectorAll('input:checked')].map(el=>el.dataset.participant);
  await control('settings',{participants:members},'参与成员已更新，未勾选成员不再接收新派工。');
};
$('pause-resume').onclick=()=>control(state.session.status==='paused'?'active':'paused',{},'控制信号已发布，请查看成员确认回执。');
for(const [id,field] of [['mode-select','mode'],['lead-select','lead']]) $(id).onchange=()=>control('settings',{[field]:$(id).value});
$('shared-context').onchange=async()=>{
  const enabled=$('shared-context').checked;
  await control('settings',{shared_context:enabled},enabled?'全局协作上下文已开启，成员下次读取时更新。':'已切换到聚焦读取，客户端已有内容不会被清除。');
};
async function previewContext(){
  if(!sessionReady())return;
  const generation=++contextGeneration, view=snapshot(), agent=$('context-agent').value;
  errorAt('context-preview-error');$('context-preview').textContent='正在读取…';$('context-next').hidden=true;
  try{
    const d=await api('/api/context?session='+encodeURIComponent(view.session)+'&agent='+agent+'&offset='+contextOffset);
    if(generation!==contextGeneration||!isCurrent(view))return;
    const text=JSON.stringify(d,null,2);$('context-preview').textContent=text;
    $('context-preview-meta').textContent=`${name(agent)} · ${d.context.scope==='team'?'全局摘要':'聚焦读取'}${d.context.lead_overview?' · 主导成员全队概览':''} · ${d.context.task_count} 个可见任务 · 本页 ${text.length} 字符`;
    contextNext=d.context.next_task_offset;$('context-next').hidden=contextNext===null;
  }catch(e){if(generation===contextGeneration&&isCurrent(view)){$('context-preview').textContent='';errorAt('context-preview-error',e.message);}}
}
$('context-dialog').onclose=()=>{contextGeneration++;};
$('context-preview-open').onclick=()=>{if(!sessionReady())return;contextOffset=0;$('context-dialog').showModal();previewContext();};
$('context-agent').onchange=()=>{contextOffset=0;previewContext();};
$('context-next').onclick=()=>{contextOffset=contextNext;previewContext();};
$('new-session').onclick=()=>{if(!sessionReady()||operations.has(selected)||creating)return;errorAt('session-form-error');$('session-dialog').showModal();$('new-session-title').focus();};
for(const id of ['new-session-title','new-session-mode']) $(id).addEventListener('input',()=>sessionRequests.delete(selected+':create'));
$('session-form').onsubmit=async e=>{
  e.preventDefault();if(creating)return;
  const op=beginOperation('create');if(!op)return;creating=true;updateComposer();
  try {
    const r=await sessionAPI(op,{action:'create',title:$('new-session-title').value,mode:$('new-session-mode').value});
    if(isCurrent(op)) {$('session-dialog').close();$('session-form').reset();switchSession(r.session);}
  } catch(e) {if(isCurrent(op))errorAt('session-form-error',e.message);}
  finally {creating=false;endOperation(op);}
};
$('finish-session').onclick=()=>{if(!sessionReady()||operations.has(selected))return;finishSnapshot=snapshot();$('finish-dialog').showModal();errorAt('finish-error');};
$('finish-form').onsubmit=async e=>{
  e.preventDefault();if(!finishSnapshot||!isCurrent(finishSnapshot))return;
  const op=beginOperation('finish');if(!op)return;
  try {await sessionAPI(op,{action:'ended',session:op.session});if(isCurrent(op)){$('finish-dialog').close();renderKey='';await sync({fresh:true});}}
  catch(e){if(isCurrent(op))errorAt('finish-error',e.message);}
  finally{endOperation(op);}
};
document.querySelectorAll('.modal-close').forEach(b=>b.onclick=()=>b.closest('dialog').close());
async function openSkills(){
  if(!sessionReady())return;
  const view=snapshot(), generation=++skillsGeneration;
  skills={};$('skill-code').textContent='';$('skill-tabs').textContent='';$('copy-skill').disabled=true;
  $('skills-dialog').showModal();errorAt('skill-error');
  try {const d=await api('/api/skills?session='+encodeURIComponent(view.session));if(generation!==skillsGeneration||!isCurrent(view))return;skills=d;renderSkills();$('copy-skill').disabled=false;}
  catch(e){if(generation===skillsGeneration&&isCurrent(view))errorAt('skill-error',e.message);}
}
$('skills-dialog').onclose=()=>{skillsGeneration++;};
function renderSkills(){ const ids=agentIds().filter(id=>id in skills);if(!ids.includes(skillAgent))skillAgent=ids[0];$('skill-tabs').innerHTML=ids.map(id=>`<button class="skill-tab ${id===skillAgent?'selected':''}" role="tab" aria-selected="${id===skillAgent}" data-skill="${id}" type="button">${esc(name(id))}</button>`).join('');$('skill-name').textContent=skillAgent?name(skillAgent):'';$('skill-code').textContent=skills[skillAgent]||'';}
$('skills-open').onclick=$('empty-guide').onclick=openSkills;
$('reader-reconnect').onclick=()=>{skillAgent=Object.values(state.agents).find(a=>a.needs_attention)?.id||state.session.lead;openSkills();};
$('skill-tabs').onclick=e=>{const b=e.target.closest('[data-skill]');if(b){skillAgent=b.dataset.skill;renderSkills();}};
$('copy-skill').onclick=async()=>{try{await navigator.clipboard.writeText($('skill-code').textContent);toast('调用说明已复制');}catch{errorAt('skill-error','复制失败，请手动选择上方文本。');}};
$('export-format').onchange=async()=>{const format=$('export-format').value;if(!format||!sessionReady())return;const view=snapshot();try{const r=await fetch('/api/export?session='+encodeURIComponent(view.session)+'&format='+format,{signal:AbortSignal.timeout(12000)});if(!r.ok)throw Error('导出失败');const blob=await r.blob();if(!isCurrent(view))return;const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='agents-talk-'+view.session+'.'+format;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);}catch(e){if(isCurrent(view))toast(e.message,true);}finally{if(isCurrent(view))$('export-format').value='';}};
function closeMenu(){$('sidebar').classList.remove('open');$('sidebar-scrim').hidden=true;$('menu-toggle').setAttribute('aria-expanded','false');}
$('menu-toggle').onclick=()=>{$('sidebar').classList.add('open');$('sidebar-scrim').hidden=false;$('menu-toggle').setAttribute('aria-expanded','true');};
$('sidebar-scrim').onclick=closeMenu;
$('tasks-nav').onclick=()=>{$('task-panel').scrollIntoView({behavior:'smooth',block:'start'});$('task-panel').focus();closeMenu();};
$('conversation-nav').onclick=()=>{$('conversation').scrollIntoView({behavior:'smooth',block:'start'});$('conversation').focus();closeMenu();};
window.addEventListener('beforeunload',saveDraft);
$('message-body').value=draft.body;
updateComposer();
sync();
