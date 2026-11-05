'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="app-token"]').content;
let state = {settings: null, jobs: [], active_job: null};
let selected = null;
let draft = null;
let keyProvider = 'openai';
let pendingKeys = {};
let sending = false;
let renderSignature = '';
let attachments = [];
let cadAttachments = [];
let drawingAttachments = [];
let uploading = false;
let moduleId = 'solidworks';
const activePhases = new Set(['queued','planning','executing','checking','stopping']);

async function api(path, data) {
  const response = await fetch(path, data === undefined ? {cache:'no-store'} : {
    method:'POST', headers:{'Content-Type':'application/json','X-App-Token':token}, body:JSON.stringify(data)
  });
  const result = await response.json();
  if (!response.ok || result.error) throw new Error(result.error || '请求未完成，请稍后重试。');
  return result;
}
function notice(text) { $('notice').textContent=text; $('notice').hidden=!text; }
function settingsNotice(text) { $('settings-notice').textContent=text; $('settings-notice').hidden=!text; }
function node(tag, className, text) { const element=document.createElement(tag); if(className) element.className=className; if(text!==undefined) element.textContent=text; return element; }
function configured() { if(state.magpie?.config?.enabled)return state.magpie.key_present&&state.magpie.gateway_ready;return state.settings && ['planner','executor'].every(role=>state.settings.providers[state.settings.roles[role].provider].key_present); }
function currentJob() { return state.jobs.find(job=>job.id===selected); }

function magpieNotice(text){$('magpie-notice').textContent=text;$('magpie-notice').hidden=!text;}
function showMagpie(value,fill=false){
  state.magpie=value;const c=value.config;
  if(fill){$('magpie-key').value='';$('magpie-enabled').checked=c.enabled;$('magpie-auto').checked=c.auto_checkin;$('magpie-vision').checked=c.vision;['simple','standard','complex'].forEach(t=>$('magpie-'+t).value=c.models[t]);$('magpie-effort').value=c.effort;$('magpie-output').value=c.max_output_tokens;}
  $('magpie-key-state').textContent=value.key_present?'令牌已安全保存在本机；留空保持。':'尚未保存魔搭令牌。';
  $('magpie-balance').textContent=value.balance_state==='verified'?'实际可用余额：'+value.balance+' 魔粒（'+value.checked_at+'）':'额度尚未核实：'+(value.balance_message||'保存令牌后点击刷新。');
  $('magpie-checkin-state').textContent=value.checkin?.message||'尚未配置支持签到的账号。';
  $('magpie-gateway').textContent=value.gateway_ready?'Magpie 网关已启动，当前任务池只转发到魔搭。':'Magpie 网关尚未启动。';
  const list=$('magpie-models');list.replaceChildren();(value.models||[]).forEach(id=>{const item=node('option');item.value=id;list.append(item);});
}
async function magpieAction(action){
  const ids=['magpie-save','magpie-start','magpie-refresh','magpie-checkin','magpie-test'];ids.forEach(id=>$(id).disabled=true);magpieNotice('正在处理，请稍候。');
  try{
    let data={action};
    if(action==='save')data={action,key:$('magpie-key').value,config:{enabled:$('magpie-enabled').checked,auto_checkin:$('magpie-auto').checked,free_only:true,vision:$('magpie-vision').checked,models:Object.fromEntries(['simple','standard','complex'].map(t=>[t,$('magpie-'+t).value.trim()])),effort:$('magpie-effort').value,max_output_tokens:Number($('magpie-output').value)}};
    const value=await api('/api/magpie',data);$('magpie-key').value='';showMagpie(value);magpieNotice(action==='save'?'设置已保存在本机。':action==='test'?(value.model_tests||[]).map(x=>x.model+'：'+(x.tools_verified?'工具调用通过':x.message||'未通过工具调用')).join('；'):'状态已更新。');await refresh();
  }catch(error){magpieNotice(error.message);}finally{ids.forEach(id=>$(id).disabled=false);}
}
$('magpie-open').addEventListener('click',async()=>{try{showMagpie(await api('/api/magpie'),true);magpieNotice('');$('magpie-dialog').showModal();}catch(error){notice(error.message);}});
$('magpie-close').addEventListener('click',()=>{$('magpie-key').value='';$('magpie-dialog').close();});
$('magpie-dialog').addEventListener('close',()=>{$('magpie-key').value='';});
['save','start','refresh','checkin','test','manage'].forEach(action=>$('magpie-'+action).addEventListener('click',()=>magpieAction(action)));

function render() {
  if (!state.settings) return;
  const modules=$('modules'); modules.replaceChildren();
  (state.modules||[{id:'solidworks',title:'SolidWorks 助手'}]).forEach(item=>{
    const button=node('button','module'+(moduleId===item.id?' active':''),item.title);
    button.disabled=!!state.active_job;
    button.addEventListener('click',()=>{moduleId=item.id;$('new-task').click();});modules.append(button);
  });
  $('upload-button').disabled=uploading||sending||!!state.active_job||attachments.length>=4;
  $('cad-upload-button').disabled=uploading||sending||!!state.active_job||cadAttachments.length>=12;
  $('drawing-upload-button').disabled=uploading||sending||!!state.active_job||drawingAttachments.length>=1;
  $('reference-mode').disabled=!!state.active_job;
  const localVector=currentJob()?.routing?.mode==='local_vector'||drawingAttachments.some(a=>a.kind==='vector');
  ['planner','executor'].forEach(role=>{const p=state.settings.roles[role];$(role+'-badge').textContent=localVector?(role==='planner'?'精确图纸解析 · 0 Token':'原生API建模 · 0 Token'):state.magpie?.config?.enabled?(currentJob()?.routing?.[role]||'按任务难度分配（免费）'):p.model+(p.reasoning_effort?' · '+p.reasoning_effort.toUpperCase():'');});
  $('setup-notice').hidden=configured();
  $('service-status').textContent=state.active_job ? '本机任务执行中' : state.environment?.solidworks_registered ? '已检测到 SolidWorks 2024' : '请先安装并激活 SolidWorks 2024';
  $('new-task').disabled=!!state.active_job;
  $('quit-app').disabled=!!state.active_job;
  const history=$('history'); history.replaceChildren();
  if (!state.jobs.length) history.append(node('div','history-empty','还没有任务'));
  state.jobs.forEach(job=>{
    const button=node('button','history-item'+(job.id===selected?' selected':''));
    button.append(node('span','',job.requests[0]));
    button.append(node('small','',job.label));
    button.addEventListener('click',()=>{selected=job.id;renderSignature='';render();});
    history.append(button);
  });
  const job=currentJob();
  $('welcome').hidden=!!job; $('conversation').hidden=!job;
  $('stop-task').hidden=!state.active_job;
  $('send-task').disabled=sending||uploading||!!state.active_job;
  $('message').disabled=!!state.active_job;
  $('message').placeholder=job?.phase==='clarify' ? '补充尺寸或要求，我会继续处理这个任务。' : '例如：建一个边长10毫米的立方体，保存并导出STEP。';
  $('composer-hint').textContent=state.active_job ? '正在执行；停止后会保留已经完成的操作' : 'Enter 发送，Shift + Enter 换行';
  if (!job) { $('conversation').replaceChildren(); return; }
  const signature=JSON.stringify([job.id,job.phase,job.requests,job.summary,job.plan,job.events.length,job.artifacts,job.usage]);
  if(signature===renderSignature) return;
  renderSignature=signature;
  const container=$('conversation'); container.replaceChildren();
  job.requests.forEach(text=>container.append(node('div','user-message',text)));
  if(job.references?.length){const refs=node('div','reference-gallery');job.references.forEach(ref=>{const img=node('img');img.src=ref.url;img.alt=ref.name;refs.append(img);});container.append(refs);}
  if(job.cad_inputs?.length)container.append(node('p','small-note','已提供零件：'+job.cad_inputs.map(file=>file.name).join('、')+'。CAD文件留在本机，模型接收名称与检查结果。'));
  if(job.drawing_inputs?.length)container.append(node('p','small-note','二维图纸：'+job.drawing_inputs.map(file=>file.name).join('、')+'。DXF/DWG使用本机精确轮廓建模；PDF按参考图片处理。'));
  container.append(node('div','assistant-label','科研自动化'));
  const status=node('div','task-status '+job.phase+(activePhases.has(job.phase)?' active':''));
  status.append(node('span','phase-dot'),node('span','',job.label)); container.append(status);
  const stages=node('div','stages');
  const stageIndex={queued:0,planning:0,executing:2,checking:3,completed:4,review_required:3,clarify:0,failed:0,cancelled:0,blocked:0,stopping:2}[job.phase]??0;
  ['理解需求','制定方案','执行操作','核对结果'].forEach((text,index)=>stages.append(node('span','stage'+(stageIndex>index?' passed':stageIndex===index?' current':''),text)));
  container.append(stages);
  if(job.plan) {
    const card=node('div','plan-card'); card.append(node('div','plan-summary',job.plan.summary));
    if(job.plan.steps.length) { const list=node('ol','plan-steps'); job.plan.steps.forEach(text=>list.append(node('li','',text))); card.append(list); }
    if(job.plan.assumptions?.length)card.append(node('p','small-note','估计内容：'+job.plan.assumptions.join('；')));
    container.append(card);
  }
  if(job.routing?.tier)container.append(node('p','small-note','免费任务池 · '+({simple:'基础',standard:'常规',complex:'复杂'}[job.routing.tier])+'：'+job.routing.reason+' 实际规划 '+job.routing.planner+'；复核 '+job.routing.reviewer));
  if(job.summary) container.append(node('div','task-summary'+((['failed','blocked','clarify'].includes(job.phase)||(job.phase==='review_required'&&job.review_status?.state!=='passed'))?' error':''),job.summary));
  if(job.review_status?.state) {
    const text={reviewing:job.review_status.repair_count?'预览已修正，正在再次复核':'正在复核预览',repairing:'复核发现预览问题，正在自动修正',passed:job.review_status.repair_count?'预览自动修正后再次复核通过':'预览复核通过',unresolved:'自动复核尚未通过，请查看问题记录'}[job.review_status.state];
    container.append(node('p','preview-review-status',text||''));
  }
  if(activePhases.has(job.phase)) {
    const recent=[...job.events].reverse().find(event=>['tool_start','tool_done','cad_wait','model_request'].includes(event.kind));
    if(recent) container.append(node('div','task-summary',recent.text));
  }
  if(job.artifacts.length) {
    const artifacts=node('section','artifacts'); const header=node('div','artifact-head'); header.append(node('span','','任务输出'));
    const open=node('button','','打开输出目录'); open.addEventListener('click',()=>api('/api/open-folder',{job_id:job.id}).catch(error=>notice(error.message))); header.append(open); artifacts.append(header);
    if(job.plan?.design&&!activePhases.has(job.phase)&&job.review_status?.mode!=='preview_only') {
      const review=node('button','','重新复核预览');review.id='review-previews';review.disabled=!!state.active_job;
      review.addEventListener('click',async()=>{review.disabled=true;try{const next=await api('/api/review-previews',{job_id:job.id});selected=next.id;renderSignature='';await refresh();}catch(error){notice(error.message);review.disabled=false;}});header.append(review);
    }
    const order=['isometric','front','top','right'];
    const previews=job.artifacts.filter(file=>file.preview).sort((a,b)=>a.view_id&&b.view_id?order.indexOf(a.view_id)-order.indexOf(b.view_id):Number(!a.name.startsWith('scene_'))-Number(!b.name.startsWith('scene_'))||Number(!a.name.includes('isometric'))-Number(!b.name.includes('isometric'))).slice(0,4);
    if(previews.length) { const grid=node('div','preview-grid'); previews.forEach(file=>{const figure=node('figure');figure.style.margin='0';const link=node('a');link.href=file.url;link.target='_blank';link.rel='noopener';const image=node('img');image.src=file.url;image.alt=file.view_label||file.name;image.loading='lazy';link.append(image);figure.append(link,node('figcaption','small-note',file.view_label||file.name));grid.append(figure);});artifacts.append(grid); }
    const files=node('div','files');job.artifacts.filter(file=>!file.preview&&!file.archived_preview&&!file.name.endsWith('.bmp')).sort((a,b)=>Number(!a.current_delivery)-Number(!b.current_delivery)).forEach(file=>{const link=node('a','file-link',(file.current_delivery?'当前交付包：':'')+file.name);link.href=file.url;link.download='';files.append(link);});artifacts.append(files);container.append(artifacts);
  }
  if(job.events.length) {
    const details=node('details','timeline'); details.append(node('summary','','查看执行记录'));
    const list=node('ol');job.events.filter(event=>event.kind!=='plan').forEach(event=>list.append(node('li','',event.text+(event.tool?' · '+event.tool:''))));details.append(list);container.append(details);
  }
  const used=(job.usage.input_tokens||0)+(job.usage.output_tokens||0);
  if(used) container.append(node('div','usage','本任务模型用量：'+used.toLocaleString()+' tokens'));
  if(activePhases.has(job.phase)) $('workspace').scrollTop=$('workspace').scrollHeight;
}

async function refresh() {
  try { state=await api('/api/state'); render(); }
  catch(error) { $('service-status').textContent='本机服务未连接'; notice(error.message==='Failed to fetch'?'本机服务连接中断，请双击桌面入口重新打开。':error.message); }
}

function rememberProvider() {
  if(!draft) return;
  pendingKeys[keyProvider]=$('api-key').value;
  draft.providers[keyProvider].base_url=$('base-url').value.trim();
  draft.providers[keyProvider].api_style=$('api-style').value;
}
function showProvider() {
  const profile=draft.providers[keyProvider];
  $('api-key').value=pendingKeys[keyProvider]||'';
  $('api-key').placeholder=profile.key_present?'已保存；留空保持原密钥':'粘贴你已有的完整 API Key';
  $('key-state').textContent=profile.key_present?'已安全保存在本机':'尚未保存密钥';
  $('remove-key').hidden=!profile.key_present;
  $('base-url').value=profile.base_url;
  $('base-url').readOnly=keyProvider!=='custom';
  $('api-style').value=profile.api_style;
}
function openSettings() {
  draft=structuredClone(state.settings); pendingKeys={}; keyProvider='openai';
  $('key-provider').value=keyProvider; showProvider();
  ['planner','executor'].forEach(role=>{
    const select=$(role+'-provider');select.replaceChildren();
    Object.entries(draft.providers).forEach(([id,profile])=>{const option=node('option','',profile.title);option.value=id;select.append(option);});
    select.value=draft.roles[role].provider; $(role+'-model').value=draft.roles[role].model;
    $(role+'-effort').value=draft.roles[role].reasoning_effort||'auto';
    updateEffortOptions(role);
  });
  $('max-turns').value=draft.max_turns;settingsNotice('');$('connection-results').replaceChildren();$('settings-dialog').showModal();
  $('planner-vision').checked=!!draft.roles.planner.vision;
}
function updateEffortOptions(role) {
  const deepseek=$(role+'-provider').value==='deepseek';
  [...$(role+'-effort').options].forEach(option=>{option.disabled=deepseek&&['medium','xhigh'].includes(option.value);});
}
['planner','executor'].forEach(role=>$(role+'-provider').addEventListener('change',()=>updateEffortOptions(role)));
async function saveSettings() {
  rememberProvider();
  ['planner','executor'].forEach(role=>{draft.roles[role]={provider:$(role+'-provider').value,model:$(role+'-model').value.trim()};});
  ['planner','executor'].forEach(role=>{const effort=$(role+'-effort').value;if(effort!=='auto')draft.roles[role].reasoning_effort=effort;});
  draft.roles.planner.vision=$('planner-vision').checked;
  draft.max_turns=Number($('max-turns').value);
  const keys=Object.fromEntries(Object.entries(pendingKeys).filter(([,value])=>value.trim()));
  $('settings-save').disabled=true;
  try {
    const result=await api('/api/settings',{settings:draft,keys});state.settings=result.settings;draft=structuredClone(result.settings);pendingKeys={};$('api-key').value='';showProvider();settingsNotice('已保存到本机。可以测试两个模型，或关闭设置开始输入需求。');render();return true;
  } catch(error) {settingsNotice(error.message);return false;}
  finally {$('settings-save').disabled=false;}
}

$('key-provider').addEventListener('change',()=>{rememberProvider();keyProvider=$('key-provider').value;showProvider();});
$('settings-save').addEventListener('click',saveSettings);
$('settings-close').addEventListener('click',()=>{$('api-key').value='';pendingKeys={};$('settings-dialog').close();});
$('settings-dialog').addEventListener('close',()=>{$('api-key').value='';pendingKeys={};});
['settings-open','models-edit','setup-open'].forEach(id=>$(id).addEventListener('click',()=>{if(state.settings)openSettings();}));
['planner','executor'].forEach(role=>$(role+'-provider').addEventListener('change',()=>{
  const provider=$(role+'-provider').value; const defaults={openai:role==='planner'?'gpt-6.1-sol':'gpt-5.4-mini',deepseek:role==='planner'?'deepseek-v4-pro':'deepseek-flash'};
  if(defaults[provider])$(role+'-model').value=defaults[provider];
  if(role==='planner')$('planner-vision').checked=provider==='openai';
}));
$('test-models').addEventListener('click',async()=>{
  if(!await saveSettings()) return;
  $('test-models').disabled=true;$('connection-results').replaceChildren();settingsNotice('正在分别测试两个模型，请稍候。');
  try {const result=await api('/api/test',{});settingsNotice(result.ok?'两个模型均连接成功，可以开始输入需求。':'部分模型未连接，请按下面的提示核对设置。');result.results.forEach(item=>$('connection-results').append(node('div','connection-result'+(item.ok?'':' bad'),item.title+(item.model?' · '+item.model:'')+'\n'+item.message)));}
  catch(error){settingsNotice(error.message);} finally{$('test-models').disabled=false;}
});
$('remove-key').addEventListener('click',async()=>{
  try {const result=await api('/api/keys/remove',{provider:keyProvider});state.settings=result.settings;draft=structuredClone(result.settings);pendingKeys[keyProvider]='';showProvider();render();settingsNotice('本应用保存的该供应商密钥已移除。');}catch(error){settingsNotice(error.message);}
});
document.querySelectorAll('[data-example]').forEach(button=>button.addEventListener('click',()=>{$('message').value=button.dataset.example;if(button.dataset.referenceMode)$('reference-mode').value=button.dataset.referenceMode;$('message').focus();}));
$('new-task').addEventListener('click',()=>{selected=null;attachments=[];cadAttachments=[];drawingAttachments=[];renderAttachments();renderSignature='';$('message').value='';notice('');render();$('message').focus();});
$('new-task-mobile').addEventListener('click',()=>{$('new-task').click();});
$('message').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();$('chat-form').requestSubmit();}});
$('chat-form').addEventListener('submit',async event=>{
  event.preventDefault();if(sending||state.active_job)return;
  const vector=drawingAttachments.some(a=>a.kind==='vector')||(!drawingAttachments.length&&state.jobs.find(j=>j.id===selected)?.drawing_inputs?.some(a=>a.kind==='vector'));
  if(!configured()&&!vector){openSettings();settingsNotice('先保存两个角色所用供应商的密钥，就可以开始执行。');return;}
  const message=$('message').value.trim()||(drawingAttachments.length?'请根据二维图纸新建零件，先询问缺少的尺寸。':attachments.length?'请根据参考图片新建零件。':cadAttachments.length?'请使用选择的零件规划装配，先确认缺少的配合关系。':'');if(!message)return;
  sending=true;notice('');render();
  try {const job=await api('/api/jobs',{message,previous_job_id:selected,module_id:moduleId,reference_ids:attachments.map(a=>a.id),cad_ids:cadAttachments.map(a=>a.id),drawing_ids:drawingAttachments.map(a=>a.id),reference_mode:$('reference-mode').value});selected=job.id;attachments=[];cadAttachments=[];drawingAttachments=[];renderAttachments();$('message').value='';state.jobs=[job,...state.jobs.filter(item=>item.id!==job.id)];state.active_job=job.id;renderSignature='';render();}
  catch(error){notice(error.message);}finally{sending=false;await refresh();}
});
$('stop-task').addEventListener('click',async()=>{if(!state.active_job)return;try{await api('/api/stop',{job_id:state.active_job});await refresh();}catch(error){notice(error.message);}});
$('quit-app').addEventListener('click',async()=>{try{await api('/api/shutdown',{});clearInterval(timer);$('service-status').textContent='应用已退出';notice('应用已退出，可以关闭此页。下次双击桌面入口即可重新打开。');}catch(error){notice(error.message);}});
const timer=setInterval(refresh,1200);
refresh();

function renderAttachments(){
  const box=$('attachments');box.replaceChildren();
  attachments.forEach(ref=>{const card=node('div','attachment');const img=node('img');img.src=ref.url;img.alt=ref.name;const remove=node('button','','移除');remove.type='button';remove.addEventListener('click',()=>{attachments=attachments.filter(a=>a.id!==ref.id);renderAttachments();render();});card.append(img,node('span','',ref.name),remove);box.append(card);});
  cadAttachments.forEach(ref=>{const card=node('div','attachment');const remove=node('button','','移除');remove.type='button';remove.addEventListener('click',()=>{cadAttachments=cadAttachments.filter(a=>a.id!==ref.id);renderAttachments();render();});card.append(node('span','','零件 · '+ref.name),remove);box.append(card);});
  drawingAttachments.forEach(ref=>{const card=node('div','attachment');const remove=node('button','','移除');remove.type='button';remove.addEventListener('click',()=>{drawingAttachments=drawingAttachments.filter(a=>a.id!==ref.id);renderAttachments();render();});card.append(node('span','','二维图纸 · '+ref.name),remove);box.append(card);});
}
$('drawing-upload-button').addEventListener('click',()=>$('drawing-files').click());
$('drawing-files').addEventListener('change',async()=>{
  const files=[...$('drawing-files').files];$('drawing-files').value='';if(!files.length)return;
  if(files.length!==1||drawingAttachments.length){notice('每个任务请选择一份二维图纸。');return;}
  uploading=true;render();notice('正在保存本机图纸；DXF/DWG不消耗模型Token，PDF会转换为参考图片。');
  try{const file=files[0];if(file.size>20*1024*1024)throw new Error('每张图纸最多20MB。');
    const response=await fetch('/api/drawing-uploads',{method:'POST',headers:{'X-App-Token':token,'Content-Type':'application/octet-stream','X-File-Name':encodeURIComponent(file.name)},body:file});
    const result=await response.json();if(!response.ok)throw new Error(result.error||'图纸上传失败。');drawingAttachments.push(result);renderAttachments();
    notice(result.kind==='vector'?'图纸已加入。可输入“按三视图及孔标注建模”，或补充厚度、孔深。缺少视图对应、深度或盲孔底形时会先询问；当前支持阶梯外形及俯视图中的Z向孔。':'PDF已转成参考图片；需要支持图片的模型。请补充关键尺寸，扫描图不会被当作精确CAD坐标。');
  }catch(error){notice(error.message);}finally{uploading=false;render();}
});
$('upload-button').addEventListener('click',()=>$('image-files').click());
$('image-files').addEventListener('change',async()=>{
  const files=[...$('image-files').files];$('image-files').value='';
  if(files.length+attachments.length>4){notice('每个任务最多4张参考图片。');return;}
  uploading=true;render();notice('正在读取参考图片；发送需求后才会提交给模型。');
  try{for(const file of files){
    if(file.size>8*1024*1024)throw new Error('每张图片最多8MB。');
    const response=await fetch('/api/uploads',{method:'POST',headers:{'X-App-Token':token,'Content-Type':file.type||'application/octet-stream','X-File-Name':encodeURIComponent(file.name)},body:file});
    const result=await response.json();if(!response.ok)throw new Error(result.error||'图片上传失败。');attachments.push(result);renderAttachments();
  }notice($('reference-mode').value==='approximate'?'图片已加入。请描述要做的外观，比例与尺度估计会在方案中列出。':'图片已加入。请补充整体尺寸和厚度；缺少的信息会在规划时询问。');}
  catch(error){notice(error.message);}finally{uploading=false;render();}
});

$('cad-upload-button').addEventListener('click',()=>$('cad-files').click());
$('cad-files').addEventListener('change',async()=>{
  const files=[...$('cad-files').files];$('cad-files').value='';
  if(files.length+cadAttachments.length>12){notice('每个任务最多12个零件文件。');return;}
  uploading=true;render();notice('正在保存本机零件副本。CAD文件不会直接发送给模型。');
  try{for(const file of files){
    if(file.size>50*1024*1024)throw new Error('每个零件文件最多50MB。');
    const response=await fetch('/api/cad-uploads',{method:'POST',headers:{'X-App-Token':token,'Content-Type':'application/octet-stream','X-File-Name':encodeURIComponent(file.name)},body:file});
    const result=await response.json();if(!response.ok)throw new Error(result.error||'零件文件保存失败。');cadAttachments.push(result);renderAttachments();
  }notice('零件已加入。请说明装配关系、对齐方式和间隙；缺少的关键参数会先询问。');}
  catch(error){notice(error.message);}finally{uploading=false;render();}
});
