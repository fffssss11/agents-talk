/* Deterministic motion design. Real screenshots contain isolated demo data only. */
'use strict';
const canvas=document.querySelector('canvas'), main=canvas.getContext('2d');
const W=1920,H=1080,DURATION=54;
const C={white:'#edfff5',mint:'#baffd9',dim:'#94b8aa',ink:'#061712',blue:'#a2c8ff',purple:'#d9bfff'};
const assets={};
const clamp=v=>Math.max(0,Math.min(1,v));
const smooth=v=>{v=clamp(v);return v*v*v*(v*(v*6-15)+10);};
function text(g,value,x,y,size=40,color=C.white,weight=400){g.font=`${weight} ${size}px "Microsoft YaHei",sans-serif`;g.fillStyle=color;g.textBaseline='top';g.fillText(value,x,y);}
function reveal(g,t,delay,fn){const a=smooth((t-delay)/1.1);g.save();g.globalAlpha*=a;g.translate(0,48*(1-a));fn();g.restore();}
function base(g,t){g.fillStyle=C.ink;g.fillRect(0,0,W,H);const a=g.createRadialGradient(1420+80*Math.sin(t/6),320,60,1100,500,1150);a.addColorStop(0,'#164735');a.addColorStop(.55,'#0b241c');a.addColorStop(1,C.ink);g.fillStyle=a;g.fillRect(0,0,W,H);
 g.save();g.strokeStyle='#89eabc';g.lineWidth=1;g.globalAlpha=.08;for(let i=0;i<15;i++){g.beginPath();g.ellipse(1480,420,180+i*60,100+i*36,-.42+t*.003,0,Math.PI*2);g.stroke();}g.restore();
 for(let i=0;i<34;i++){g.fillStyle=`rgba(190,255,218,${.1+.12*(.5+.5*Math.sin(t+i))})`;g.beginPath();g.arc((i*137.8+73)%W,70+(i*79.3+t*(2+i%3))%940,1.2,0,7);g.fill();}
}
function brand(g,t,label){text(g,'AGENTS TALK',96,60,25,C.mint,700);text(g,label,1430,62,22,C.dim);g.fillStyle='#7dccaa';g.globalAlpha=.23;g.fillRect(96,998,1728,1);g.globalAlpha=1;g.fillStyle=C.mint;g.fillRect(96,998,1728*clamp(t/DURATION),2);}
function footer(g,value){text(g,value,96,1024,21,C.dim);}
function art(g,t,opacity=.55){g.save();g.globalAlpha*=opacity;const z=1.02+.025*Math.sin(t/8);g.translate(W/2,H/2);g.scale(z,z);g.drawImage(assets.art,-W/2,-H/2,W,H);g.restore();const v=g.createLinearGradient(0,0,W,0);v.addColorStop(0,'rgba(3,19,13,.78)');v.addColorStop(.56,'rgba(3,19,13,.35)');v.addColorStop(1,'rgba(3,19,13,.02)');g.fillStyle=v;g.fillRect(0,0,W,H);}
function screen(g,img,x,y,w,h,t,crop){g.save();g.shadowColor='rgba(0,0,0,.6)';g.shadowBlur=65;g.shadowOffsetY=28;g.fillStyle='#ebf0e5';g.beginPath();g.roundRect(x,y,w,h,22);g.fill();g.shadowColor='transparent';g.clip();const z=1+.018*smooth(t/7);g.translate(x+w/2,y+h/2);g.scale(z,z);const c=crop||[0,0,img.width,img.height];g.drawImage(img,...c,-w/2,-h/2,w,h);g.restore();g.save();g.strokeStyle='rgba(194,255,220,.3)';g.lineWidth=2;g.beginPath();g.roundRect(x,y,w,h,22);g.stroke();g.restore();}
function heading(g,t,tag,lines,sub){reveal(g,t,0,()=>text(g,tag,96,195,27,C.mint));lines.forEach((s,i)=>reveal(g,t,.12+i*.17,()=>text(g,s,96,262+i*90,72,C.white,700)));if(sub)reveal(g,t,.55,()=>text(g,sub,96,465,29,C.dim));}
function row(g,t,delay,num,label,body,y,color=C.mint){reveal(g,t,delay,()=>{text(g,num,98,y,22,color);text(g,label,152,y-9,38,C.white,700);text(g,body,152,y+49,27,C.dim);});}
const scenes=[
 {start:0,end:6,draw(g,t){base(g,t);art(g,t,.38);brand(g,t,'LOCAL COLLABORATION');reveal(g,t,.1,()=>text(g,'开了多个 AI 窗口，',96,288,91,C.white,700));reveal(g,t,.55,()=>text(g,'谁在负责交接？',96,408,110,C.mint,700));reveal(g,t,1.7,()=>text(g,'任务重复分配',104,688,36,C.white));reveal(g,t,2.25,()=>text(g,'上下文来回复述',590,688,36,C.white));reveal(g,t,2.8,()=>text(g,'交付缺少验收',1136,688,36,C.white));footer(g,'面向多窗口协作的分工、上下文与验收问题');}},
 {start:6,end:12,draw(g,t){base(g,t+6);brand(g,t+6,'ONE SHARED BOARD');reveal(g,t,0,()=>text(g,'Agents Talk',96,206,100,C.white,700));reveal(g,t,.25,()=>text(g,'一个本地协作面板',100,345,48,C.mint,700));reveal(g,t,.65,()=>text(g,'把共享过程留下来',100,440,34,C.dim));reveal(g,t,.4,()=>screen(g,assets.dashboard,790,178,1034,678,t));reveal(g,t,1,()=>text(g,'Codex   Claude Code',104,620,30,C.white));reveal(g,t,1.25,()=>text(g,'Reasonix   ZCode',104,675,30,C.white));footer(g,'实际空白会话界面，不读取原生客户端私密对话');}},
 {start:12,end:20,draw(g,t){base(g,t+12);brand(g,t+12,'01 / INDEPENDENT ROLES');heading(g,t,'同一客户端，多窗口并发',['角色分开','责任明确']);row(g,t,.7,'01','主导窗口','拆分任务，安排最终整合',566);row(g,t,1.4,'02','实现窗口','处理自己的任务与文件范围',696);row(g,t,2.1,'03','验收窗口','核查交付与验证记录',826);reveal(g,t,.3,()=>screen(g,assets.instances,805,220,1010,702,t,[0,0,940,654]));footer(g,'隔离演示数据，未调用真实模型。每个窗口需单独接入，模型在客户端选择。');}},
 {start:20,end:29,draw(g,t){base(g,t+20);brand(g,t+20,'02 / TRACEABLE HANDOFF');heading(g,t,'任务工作树',['谁执行','谁来验收']);row(g,t,.7,'01','派发可追溯','记录派发者与当前负责人',566);row(g,t,2,'02','交付要核查','指定独立验收人并记录结论',696);row(g,t,3.2,'03','整合有前置','依赖任务与整合计划一起呈现',826);reveal(g,t,.3,()=>screen(g,assets.workflow,760,220,1070,692,t));footer(g,'隔离演示数据，画面中的完成状态仅用于功能说明。任务工作树不创建 Git worktree。');}},
 {start:29,end:37,draw(g,t){base(g,t+29);brand(g,t+29,'03 / HUMAN IN THE LOOP');heading(g,t,'全员对话窗口',['讨论集中看','要求随时加']);row(g,t,.8,'01','共享对话','各实例发布进展与交付摘要',588);row(g,t,2,'02','人工介入','追加要求，查看成员回执',738);reveal(g,t,.3,()=>screen(g,assets.conversation,760,220,1070,692,t));footer(g,'隔离演示数据。人工指令在成员下次读取时生效，无法即时中断外部工具。');}},
 {start:37,end:45,draw(g,t){base(g,t+37);brand(g,t+37,'04 / CONTEXT ON DEMAND');heading(g,t,'上下文按需共享',['默认聚焦','需要再展开']);
 const a=smooth((t-3)/1.35);g.save();g.globalAlpha=.35;g.strokeStyle=C.mint;g.lineWidth=2;g.beginPath();g.moveTo(900,440);g.bezierCurveTo(1200,440,1180,750,1530,750);g.stroke();g.restore();
 reveal(g,t,.7,()=>{text(g,'默认范围',850,250,28,C.mint);text(g,'自己的任务',850,315,53,C.white,700);text(g,'与主导相关的信息',850,390,42,C.white);});
 reveal(g,t,3,()=>{text(g,'开启全局共享后',1120,560,28,C.mint);text(g,'全队任务成果摘要',1120,630,48,C.white,700);text(g,'主导始终保留全队摘要',1120,711,29,C.dim);});
 g.save();g.globalAlpha=a;g.shadowBlur=18;g.shadowColor=C.mint;g.fillStyle=C.mint;g.beginPath();g.arc(900+630*a,440+310*smooth(a),7,0,7);g.fill();g.restore();
 reveal(g,t,1.1,()=>text(g,'增量读取，按需查证',98,640,34,C.mint));reveal(g,t,1.6,()=>text(g,'真实用量按实例记录',98,718,29,C.dim));footer(g,'机制示意。没有量化的 Token 节省承诺，已读取内容无法撤回。');}},
 {start:45,end:54,draw(g,t){base(g,t+45);art(g,t+45,.6);brand(g,t+45,'MIT OPEN SOURCE');reveal(g,t,.1,()=>text(g,'Agents Talk',96,200,114,C.white,700));reveal(g,t,.4,()=>text(g,'让多窗口协作有记录可查',100,358,53,C.mint,700));reveal(g,t,.8,()=>text(g,'Python 3.10+ 与浏览器',102,493,31,C.white));reveal(g,t,1.15,()=>{text(g,'python hub.py doctor',104,558,37,C.mint);text(g,'python start.py',104,616,37,C.mint);});reveal(g,t,1.65,()=>text(g,'github.com/fffssss11/agents-talk',101,785,47,C.white,700));reveal(g,t,2.1,()=>text(g,'下载源码，按 README 安装 skill 并接入各窗口',104,859,30,C.dim));footer(g,'仅用于可信本机。模型和媒体工具由客户端提供，原生回合停止后可能需要重新接入。');}}
];
const buffers=[0,1].map(()=>{const c=document.createElement('canvas');c.width=W;c.height=H;return c;});
function render(t){t=Math.max(0,Math.min(DURATION-1/60,t));let i=scenes.findIndex(s=>t>=s.start&&t<s.end);if(i<0)i=scenes.length-1;const current=scenes[i],local=t-current.start;main.globalAlpha=1;main.fillStyle=C.ink;main.fillRect(0,0,W,H);
 if(i>0&&local<1.05){scenes[i-1].draw(buffers[0].getContext('2d'),t-scenes[i-1].start);current.draw(buffers[1].getContext('2d'),local);const a=smooth(local/1.05);main.drawImage(buffers[0],0,0);const edge=W*(1-a);main.save();main.beginPath();main.rect(edge,0,W-edge,H);main.clip();main.drawImage(buffers[1],0,0);main.restore();if(a>0&&a<1){const glow=main.createLinearGradient(edge-28,0,edge+28,0);glow.addColorStop(0,'rgba(186,255,217,0)');glow.addColorStop(.5,'rgba(186,255,217,.16)');glow.addColorStop(1,'rgba(186,255,217,0)');main.fillStyle=glow;main.fillRect(edge-28,0,56,H);}}else current.draw(main,local);
 if(t<.65){main.fillStyle=`rgba(6,23,18,${1-smooth(t/.65)})`;main.fillRect(0,0,W,H);}
 return t;
}
window.promo={duration:DURATION,render,ready:Promise.all(Object.entries({art:'concept-art.png',dashboard:'dashboard.png',instances:'instances-demo.png',workflow:'workflow-demo.png',conversation:'conversation-demo.png'}).map(([key,file])=>new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>{assets[key]=im;resolve();};im.onerror=reject;im.src='../assets/'+file;}))).then(()=>document.fonts.ready).then(()=>render(48.5))};
let playing=false,raf=0,start=0;document.querySelector('#play').onclick=()=>{playing=!playing;document.querySelector('#play').textContent=playing?'暂停预览':'播放预览';cancelAnimationFrame(raf);if(playing){start=performance.now();const tick=now=>{render((now-start)/1000);if(now-start<DURATION*1000)raf=requestAnimationFrame(tick);else{playing=false;document.querySelector('#play').textContent='重播预览';}};raf=requestAnimationFrame(tick);}};
// Preview is paused by default, including when reduced motion is requested.
