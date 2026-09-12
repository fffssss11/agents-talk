const path=require('path'),fs=require('fs');
const {spawnSync}=require('child_process');
// npm ci + npx playwright install chromium is the public default.
const {chromium}=require(process.env.AGENTS_TALK_NODE_MODULES ? path.join(process.env.AGENTS_TALK_NODE_MODULES,'playwright') : 'playwright');
const root=path.resolve(__dirname,'..');
fs.mkdirSync(path.join(root,'.runtime'),{recursive:true});
function findPython(){
  const choices=process.env.AGENTS_TALK_PYTHON ? [process.env.AGENTS_TALK_PYTHON] : ['python3','python'];
  for(const candidate of choices){
    const r=spawnSync(candidate,['-c','import sys; assert sys.version_info >= (3,10); print(sys.executable)'],{encoding:'utf8',windowsHide:true});
    if(r.status===0&&r.stdout.trim())return r.stdout.trim();
  }
  throw Error('Python 3.10+ not found. Set AGENTS_TALK_PYTHON to its executable.');
}
const executablePath=process.env.AGENTS_TALK_BROWSER||process.env.AGENTS_TALK_CHROME;
module.exports={chromium,python:findPython(),launchOptions:{headless:true,...(executablePath?{executablePath}:{})}};
