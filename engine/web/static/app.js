let measuredGridResponse={"schema":"r5-measured-grid-response/1","preset":"r5-paired-20261107-nonlinear-he3","sha256":"936af0b27f3c5f1ff422c20dd7c1436f92458407d1dd492a4edca2e5ef45e677","model":"ILCE-7RM5"};
function selectedGridResponse(){
  return measuredGridResponse;
}
function gridResponseName(response){return response?.preset==='r5-paired-20261107-nonlinear-he3'?'R5 Hybrid · 非线性基底＋三色相 C1 专家 · 2026-11-07':'不支持的响应算子';}
function gridResponseControls(){}

'use strict';
const $ = id => document.getElementById(id);
const clone = value => structuredClone(value);
let boot, draft, selected = 1, collection = [], lutText = '', jobId, timer, busy = false;
let chartTargetId, chartUploading=false;
const imageTarget=()=>$('targetKind').value==='chart-image';
const chartJob=()=>diagnosticData?.dataset?.target_kind==='chart-image';
const targetReady=()=>imageTarget()?Boolean(chartTargetId):Boolean(lutText);
const names = ['ST','PT','NT','VV','VV2','FL','FL2','FL3','IN','SH','BW','SE'];
const chineseNames = ['标准','人像','中性','鲜艳','鲜艳二','胶片','胶片二','胶片三','即时','柔和高调','黑白','棕褐'];
let validationJob, rawFile, rawBusy = false, diagnosticData;
let savedDiagnosticData, savedNativePreview, taskEntry, liveTimer, liveSerial=0, liveRunning=false, livePending=false, liveTask, liveMode;
let photoFile, photoBusy=false, photoId, photoTask, photoTimer;
let actualUrl,photoSourceSha;
const pcView=()=>$('resultMode').value!=='native';
const gridKeys=new Map();
let diagnosticSerial=0,compressionTimer,compressionBusy=false;
const beforeGrayKeys=new Map();
const selectedGrid=()=>$('resultMode').value==='compressed'?($('grayRefinementView').value==='before'?beforeGrayKeys.get(jobId)||gridKeys.get(jobId):gridKeys.get(jobId)):undefined;
const algorithmName=()=>$('resultMode').value==='compressed'?('压缩后单网格'+(beforeGrayKeys.has(jobId)?($('grayRefinementView').value==='before'?' · 灰阶微调前':' · 灰阶微调后'):'')):pcView()?'压缩前完整补偿':'原生参数';
const pcJobs=new Set();
const photoGridEffect=()=>$('photoGridEffect').checked;
const photoGridMatches=r=>(r.grid_effect_enabled!==false)===photoGridEffect();
function clearActual(){if(actualUrl)URL.revokeObjectURL(actualUrl);actualUrl=undefined;$('photoActual').removeAttribute('src');$('photoActual').hidden=true;$('photoActualEmpty').hidden=false;$('photoActualClear').hidden=true;$('photoActualName').textContent='此栏为实际软件输出，不由模拟函数生成。';$('photoActualInput').value='';}
function photoReady(){ $('photoRender').disabled=photoBusy||!photoFile||!validationJob||chartJob()||Boolean($('liveEdit')?.checked);$('photoGridEffect').disabled=photoBusy||!pcView(); }
function showPhoto(value){
  if(value.job!==validationJob)return;
  if(Boolean(value.result.pc_compensation_enabled)!==pcView()||!photoGridMatches(value.result))return;
  if((value.result.grid_key||undefined)!==selectedGrid())return;
  if(value.result.grid_key&&value.result.grid_sha256!==diagnosticData?.grid_sha256)return;
  if(value.result.pc_compensation_enabled && value.result.pc_compensation_sha256!==diagnosticData?.pc_sha256)return;
  photoSourceSha=value.result.source_sha256;
  const base='/api/previews/'+value.id+'/';
  $('photoResults').hidden=false;
  $('photoModel').alt=algorithmName()+' RAW 预览';$('photoModelTitle').textContent='拟合结果 · '+algorithmName()+(pcView()?(photoGridEffect()?' · 网格开启':' · 网格关闭'):'');
  for(const [key,file]of[['Lut','lut.png'],['Model','model.png']]){ $('photo'+key).src=base+file;$('photo'+key+'Download').href=base+file; }
  $('photoAudit').href=base+'result.json';
  const r=value.result;
  $('photoProvenance').textContent=`任务 ${value.job} · ${r.gamut} · ${r.width} × ${r.height} ${r.preview_long_edge===3840?'4K 对照图':'历史采样预览'} · ${r.samples} 个采样点 · 同一 RAW SHA256：${r.source_sha256.slice(0,16)}…`;
  $('photoStatus').textContent=('当前 RAW 算法：'+algorithmName()+'；')+(pcView()?(photoGridEffect()?'网格效果开启；':'网格效果关闭；'):'')+'RAW 前端为近似。第三栏可导入 Edit 实际导出图。';
}
async function pollPhoto(){
  try{const value=await(await api('/api/previews/'+photoId)).json();
    if(value.status==='done'||value.status==='error'){
      photoBusy=false;photoReady();
      if(value.status==='done'){showPhoto(value);if(value.job===validationJob&&((value.result.grid_key||undefined)!==selectedGrid()||Boolean(value.result.pc_compensation_enabled)!==pcView()||!photoGridMatches(value.result)))loadDiagnostics(validationJob);}else if(value.job===validationJob)$('photoStatus').textContent='预览失败：'+value.error;
      return;
    }
    if(value.job===validationJob)$('photoStatus').textContent=value.phase;
    photoTimer=setTimeout(pollPhoto,2000);
  }catch(e){photoBusy=false;photoReady();$('photoStatus').textContent='读取预览失败：'+e.message;}
}
const drafts = new Map();
const draftSources=new Map(), collectionSources=new Map();
let draftSource;
const parameterSignature=e=>JSON.stringify([e.cc1_delta,e.block13,e.gamma_native_129,e.grid_5x9x9]);
let compressedSignature;
function exportProject(entries=collection,sources=collectionSources){return {...project(entries),export_sources:Object.fromEntries(entries.filter(e=>sources.has(e.number)).map(e=>[String(e.number),clone(sources.get(e.number))]))};}
function gridSourceStatus(){
  if(draftSource?.kind==='compressed'&&parameterSignature(draft)!==compressedSignature)draftSource=undefined;
  if(draftSource?.kind==='stock'){const p=boot.stock_grids.find(p=>p.id===draftSource.id);if(!p||JSON.stringify(p.grid_5x9x9)!==JSON.stringify(draft.grid_5x9x9))draftSource=undefined;}
  $('stockGrid').value=draftSource?.kind==='stock'?draftSource.id:'';
  $('gridSourceStatus').textContent=draftSource?.kind==='stock'?'已选择原厂网格；保留当前 CC1、block13 与 Gamma。':draftSource?.kind==='compressed'?'已绑定完成的压缩网格与本任务原生参数。':'尚未选择网格：选择原厂网格或完成压缩后才能加入导出集。';
  $('add').disabled=!draftSource;
}

let toastTimer;
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 6500); }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-R5-Token':boot.token}, body:JSON.stringify(body)});
  if (!response.ok) { let value; try { value = await response.json(); } catch { value = {error:response.statusText}; } throw Error(value.error || '请求失败'); }
  return response;
}
function project(entries = collection) { return {...boot.template,entries:clone(entries)}; }
function readNames() { draft.short_name=$('shortName').value;draft.full_name=$('lookName').value; }
function showNames() { $('shortName').value=draft.short_name;$('lookName').value=draft.full_name; }
function remember() { if (draft) { readNames();drafts.set(selected, clone(draft));if(draftSource)draftSources.set(selected,clone(draftSource));else draftSources.delete(selected); } }
function syncRaw() { gridSourceStatus();$('rawEditor').value = JSON.stringify(draft, null, 2); $('editStatus').textContent = '参数已更新；点击“加入导出集”保存本项。'; scheduleDraftDiagnostics(); }
function freshConfiguration(number) { return {...clone(boot.presets[1]),number,short_name:'F'+String(number).padStart(2,'0'),full_name:'自定义滤镜 '+number}; }
function baselineNote() {
  const i=+$('baselineLook').value,p=boot.provenance[i];
  $('sourceNote').textContent=`编辑基线：${chineseNames[i]}（${names[i]}）。配置编号独立；机内原厂创意外观另行选择，其附加处理仍保留。`;
  $('sourceNote').title=JSON.stringify(p);
}
function selectLook(number) {
  remember(); selected = number;
  draft = clone(drafts.get(number) || collection.find(e => e.number === number) || freshConfiguration(number));
  draftSource=clone(drafts.has(number)?draftSources.get(number):collectionSources.get(number));compressedSignature=draftSource?.kind==='compressed'?parameterSignature(draft):undefined;
  showNames();
  document.querySelectorAll('.looks button').forEach(b => { b.classList.toggle('active', +b.dataset.number === number); b.setAttribute('aria-pressed', +b.dataset.number === number ? 'true' : 'false'); });
  baselineNote();renderEditors();
}
function renderEditors() { renderGamma(); renderCC(); renderMatrix(); syncRaw(); }
function cell(value, low, high, change) {
  const td = document.createElement('td'), input = document.createElement('input');
  input.type = 'number'; input.step = '1'; input.min = low; input.max = high; input.value = value;
  input.addEventListener('change', () => { const v = Number(input.value); if (input.value === '' || !Number.isInteger(v) || v < low || v > high) { input.classList.add('invalid'); toast(`请输入 ${low}…${high} 的整数`); return; } input.classList.remove('invalid'); change(v); renderParameterSliders(); syncRaw(); });
  td.append(input); return td;
}
function header(table, values) { table.replaceChildren(); const tr = document.createElement('tr'); for (const text of values) { const th = document.createElement('th'); th.textContent = text; tr.append(th); } table.append(tr); }
function renderCC() {
  const table = $('ccTable'); header(table,['端点','色度混合一','色度混合二','色度混合三','色度混合四','色度增益一','色度增益二','色度增益三','色度增益四']);
  ['基准值','照明一差值','照明二差值'].forEach((label,g)=>{const tr=document.createElement('tr'), title=document.createElement('td'); title.textContent=label;tr.append(title);draft.cc1_delta[g].forEach((v,i)=>{const td=cell(v,g===0?(i<4?-1024:0):-2047,g===0?1023:2047,n=>draft.cc1_delta[g][i]=n);td.firstChild.disabled=$('liveEdit').checked&&g!==0;td.firstChild.onfocus=()=>{$('ccSliderGroup').value=g;$('ccSliderIndex').value=i;renderParameterSliders();};tr.append(td);});table.append(tr);});renderParameterSliders();
}
function renderMatrix() {
  const table=$('matrixTable'), g=+$('matrixEndpoint').value;header(table,['色相','红减绿','红减蓝','绿减红','绿减蓝','蓝减红','蓝减绿']);
  draft.block13[g].forEach((row,s)=>{const tr=document.createElement('tr'), title=document.createElement('td');title.textContent=String(s).padStart(2,'0');tr.append(title);row.forEach((v,i)=>{const td=cell(v,-8192,8191,n=>setBlock13Value(g,s,i,n));td.firstChild.onfocus=()=>{$('matrixSliderSector').value=s;$('matrixSliderIndex').value=i;renderParameterSliders();};tr.append(td);});table.append(tr);});renderParameterSliders();
}
function gammaAxis(){
  const values=(savedDiagnosticData||diagnosticData)?.native_gamma?.parameter_knots?.input_14bit;
  return values?.length===128?values:Array.from({length:128},(_,i)=>i);
}
function gammaResiduals(){
  const raw=(savedDiagnosticData||diagnosticData)?.native_gamma?.parameter_knots?.fitted_output_raw;
  return taskEntry&&raw?.length===128?raw.map((value,i)=>value/2-taskEntry.gamma_native_129[i]):Array(128).fill(0);
}
function gammaLimits(point){
  if(point===128)return [draft.gamma_native_129[127],131071];
  if(!$('gammaShapeLock').checked)return [0,131071];
  const residual=gammaResiduals(),y=draft.gamma_native_129.slice(0,128).map((value,i)=>value+residual[i]),x=gammaAxis();if(point===0)return [0,0];
  let low=y[point-1],high=point<127?y[point+1]:Math.min(131071,draft.gamma_native_129[128])+residual[point];
  if(point<127)low=Math.max(low,(y[point-1]*(x[point+1]-x[point])+y[point+1]*(x[point]-x[point-1]))/(x[point+1]-x[point-1]));
  if(point>1)high=Math.min(high,y[point-1]+(y[point-1]-y[point-2])/(x[point-1]-x[point-2])*(x[point]-x[point-1]));
  if(point<126)high=Math.min(high,y[point+1]-(y[point+2]-y[point+1])/(x[point+2]-x[point+1])*(x[point+1]-x[point]));
  return [Math.max(0,Math.ceil(low-residual[point]-1e-9)),Math.max(0,Math.floor(high-residual[point]+1e-9))];
}
function setGammaValue(value){
  const i=+$('gammaIndex').value,[low,high]=gammaLimits(i);
  if(low>high){$('gammaPointStatus').textContent='相邻原节点不满足单调凹；此节点没有保持邻点不变的可行移动。可关闭形状锁后编辑。';return;}
  draft.gamma_native_129[i]=Math.max(low,Math.min(high,Math.round(value)));renderGamma();syncRaw();
}
function renderGamma() {
  const point=Math.max(0,Math.min(128,+$('gammaIndex').value || 0)),xs=gammaAxis(),xmax=xs.at(-1);
  $('gammaIndex').value=point;$('gammaValue').value=draft.gamma_native_129[point];$('gammaSliderValue').textContent=draft.gamma_native_129[point].toLocaleString();
  const [low,high]=gammaLimits(point);$('gammaSlider').min=Math.min(low,high,draft.gamma_native_129[point]);$('gammaSlider').max=Math.max(low,high,draft.gamma_native_129[point]);$('gammaSlider').disabled=low>high;$('gammaSlider').value=draft.gamma_native_129[point];
  $('gammaPointStatus').textContent=point===128?'第129点仅为导出端点，不参与本页颜色模拟。':`原生节点 ${point} · 输入 ${Number(xs[point].toFixed(3))}${$('gammaShapeLock').checked?' · 保形可调范围 '+low+'–'+high:''}`;
  const canvas=$('gammaChart'), ctx=canvas.getContext('2d'), w=canvas.width,h=canvas.height,pad={l:60,r:16,t:20,b:35}, iw=w-pad.l-pad.r,ih=h-pad.t-pad.b;
  ctx.clearRect(0,0,w,h);ctx.font='12px system-ui';ctx.setLineDash([]);
  for(let i=0;i<=4;i++){const y=pad.t+ih*i/4;ctx.strokeStyle='#e9ede4';ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(w-pad.r,y);ctx.stroke();ctx.fillStyle='#87917f';ctx.fillText(Math.round(131071*(1-i/4)).toLocaleString(),0,y+4);}
  for(let i=0;i<=4;i++){const x=pad.l+iw*i/4;ctx.fillStyle='#87917f';ctx.fillText(String(Math.round(xmax*i/4)),x-7,h-13);}
  const plot=(values,color,width,dash=[])=>{ctx.strokeStyle=color;ctx.lineWidth=width;ctx.setLineDash(dash);ctx.beginPath();values.slice(0,128).forEach((v,i)=>{const x=pad.l+iw*xs[i]/xmax,y=pad.t+ih*(1-v/131071);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();ctx.setLineDash([]);};
  plot(boot.presets[+$('baselineLook').value].gamma_native_129,'#ced6c6',2);
  if(taskEntry)plot(taskEntry.gamma_native_129,'#939eae',1.5,[6,4]);plot(draft.gamma_native_129,'#31583f',2.8);
  ctx.fillStyle='#31583f';draft.gamma_native_129.slice(0,128).forEach((v,i)=>{ctx.beginPath();ctx.arc(pad.l+iw*xs[i]/xmax,pad.t+ih*(1-v/131071),i===point?5:1.8,0,Math.PI*2);ctx.fill();});
  ctx.fillStyle='#87917f';ctx.fillText('实际非均匀输入轴 · 浅灰：原厂基线 / 虚线：已保存 / 深绿：草稿（第129点另行编辑）',pad.l,h-1);
}
function renderParameterSliders(){
  if(!draft||!$('ccSlider'))return;
  const g=+$('ccSliderGroup').value,i=+$('ccSliderIndex').value,v=draft.cc1_delta[g][i];
  $('ccSlider').min=Math.min(g===0?(i<4?-1024:0):-2047,v);$('ccSlider').max=Math.max(g===0?1023:2047,v);$('ccSlider').value=v;$('ccSliderValue').textContent=v;
  const mg=+$('matrixEndpoint').value,sector=+$('matrixSliderSector').value||0,mi=+$('matrixSliderIndex').value,mv=draft.block13[mg][sector][mi];
  $('matrixSlider').value=mv;$('matrixSliderValue').textContent=mv;
  const canvas=$('matrixEditCurve'),ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height,p=35,values=draft.block13[mg].map(row=>row[mi]),bound=Math.max(256,...values.map(Math.abs))*1.15;
  ctx.clearRect(0,0,w,h);ctx.font='12px system-ui';ctx.strokeStyle='#e3e8de';
  for(let j=0;j<=4;j++){const y=p+(h-2*p)*j/4;ctx.beginPath();ctx.moveTo(p,y);ctx.lineTo(w-p,y);ctx.stroke();ctx.fillStyle='#788076';ctx.fillText(String(Math.round(bound*(1-j/2))),0,y+4);}
  ctx.beginPath();ctx.strokeStyle='#31583f';ctx.lineWidth=2;[...values,values[0]].forEach((value,j)=>{const x=p+(w-2*p)*j/16,y=h/2-value/bound*(h-2*p)/2;j?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();
  values.forEach((value,j)=>{const x=p+(w-2*p)*j/16,y=h/2-value/bound*(h-2*p)/2;ctx.fillStyle=j===sector?'#b36f39':'#31583f';ctx.beginPath();ctx.arc(x,y,j===sector?5:2.5,0,Math.PI*2);ctx.fill();if(j%2===0){ctx.fillStyle='#788076';ctx.fillText(String(j),x-4,h-10);}});
  ctx.fillStyle='#788076';ctx.fillText('16 色相周期 · 系数值（按原生节点连接）',p,15);
}

function renderCollection() {
  const node=$('collection');node.replaceChildren();collection.sort((a,b)=>a.number-b.number);
  if(!collection.length){const p=document.createElement('p');p.className='empty';p.textContent='导出空配置可清空机内自定义滤镜';node.append(p);}
  for(const entry of collection){const row=document.createElement('div');row.className='collection-row';const n=document.createElement('span');n.className='number';n.textContent=entry.number;const info=document.createElement('div'),name=document.createElement('strong'),sub=document.createElement('small');name.textContent=entry.full_name;sub.textContent=`${entry.short_name} · 独立配置 ${entry.number} · 5×9×9 网格`;info.append(name,sub);const edit=document.createElement('button');edit.textContent='编辑';edit.onclick=()=>selectLook(entry.number);const remove=document.createElement('button');remove.textContent='×';remove.setAttribute('aria-label','从导出集移除 '+entry.full_name);remove.onclick=()=>{collection=collection.filter(e=>e.number!==entry.number);collectionSources.delete(entry.number);renderCollection();};row.append(n,info,edit,remove);node.append(row);}
  $('exportStatus').textContent=`${collection.length} 项 · v4 / 4.23 · 完整替换${collection.length?'':'，清空全部自定义滤镜'}`;
}
function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function palette(id,colors){const canvas=$(id),ctx=canvas.getContext('2d'),cols=24,rows=4;ctx.clearRect(0,0,canvas.width,canvas.height);for(let i=0;i<cols*rows;i++){const c=colors[Math.floor(i*colors.length/(cols*rows))];ctx.fillStyle=`rgb(${c.map(v=>Math.round(v*255)).join(',')})`;ctx.fillRect(i%cols*canvas.width/cols,Math.floor(i/cols)*canvas.height/rows,canvas.width/cols+1,canvas.height/rows+1);}}
function showResult(result){
  if(liveTask!==jobId){liveSerial++;clearTimeout(liveTimer);savedDiagnosticData=undefined;liveTask=jobId;$('liveEditComparison').hidden=true;}taskEntry=clone(result.config.entries[0]);savedNativePreview=clone(result.preview);
  for(const id of ['before','target','after'])palette(id,result.preview[id]);
  const b=result.heldout.before,a=result.heldout.after;
  $('metrics').replaceChildren();for(const [key,title]of[['mae_8bit','平均绝对误差 / 8位'],['rmse_8bit','均方根误差 / 8位'],['p95_8bit','95%误差分位 / 8位']]){const div=document.createElement('div'),label=document.createElement('span'),value=document.createElement('strong'),sub=document.createElement('small');label.textContent=title;value.textContent=a[key].toFixed(2);sub.textContent=`基线 ${b[key].toFixed(2)}`;div.append(label,value,sub);$('metrics').append(div);}
  $('previewBadge').textContent=result.white_balance?.enabled?'实验白平衡模型 · BIN 不含白平衡':'模型结果 · 实拍待验收';
  const entry=clone(result.config.entries[0]);if(selected!==entry.number){remember();selected=entry.number;}drafts.set(entry.number,entry);draftSources.delete(entry.number);
  draftSource=undefined;draft=entry;showNames();document.querySelectorAll('.looks button').forEach(button=>{button.classList.toggle('active',+button.dataset.number===selected);button.setAttribute('aria-pressed',String(+button.dataset.number===selected));});renderEditors();
  toast('拟合完成；结果已载入编辑器，检查后加入导出集。');
}
function setBusy(value){busy=value;for(const id of ['targetKind','chartVersion','chartTarget','lut','gamut','endpoint','wbTraining','weightRandom','weightPrimaries','weightGray','weightCC24','weightSector16','resetWeights','postfitDeburr','gammaMonotoneConcave','gammaGlobalCorrection','parameterSmoothing','outputContinuity','searchStarts','adaptiveRounds','gammaColorRounds','perceptualWeight','quantizationSweeps','targetPolishRounds','pcCurveMode','pcGridEnabled','gridResponseModel'])$(id).disabled=value;postfitControls();$('pcTraining').disabled=value;$('fit').disabled=value;$('distillGrid').disabled=value||compressionBusy;$('cancel').hidden=!value;if(value){validationJob=undefined;$('rawExport').disabled=true;$('rawTask').textContent='拟合运行中，等待当前任务配方。';photoReady();$('photoResults').hidden=true;$('photoStatus').textContent='拟合运行中，等待当前任务配方。';}}
function histogram(canvas, target, after, color) {
  const ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height,left=54,top=15,bottom=h-30,iw=w-left-12,ih=bottom-top;
  const peak=Math.max(...target,...after,1e-9);
  ctx.clearRect(0,0,w,h);ctx.font='12px system-ui';ctx.lineWidth=1;ctx.setLineDash([]);
  for(let i=0;i<=4;i++){const y=top+ih*i/4;ctx.strokeStyle='#e3e8de';ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(w-12,y);ctx.stroke();ctx.fillStyle='#74816e';ctx.fillText((peak*(1-i/4)*100).toFixed(1)+'%',0,y+4);}
  ctx.fillStyle=color+'30';for(let i=0;i<256;i++){const v=Math.min(target[i],after[i]);ctx.fillRect(left+iw*i/256,bottom-ih*v/peak,iw/256+1,ih*v/peak);}
  for(const [values,dash,stroke]of[[target,[],color],[after,[7,4],'#263b30']]){ctx.strokeStyle=stroke;ctx.lineWidth=1.8;ctx.setLineDash(dash);ctx.beginPath();values.forEach((v,i)=>{const x=left+iw*i/255,y=bottom-ih*v/peak;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();}ctx.setLineDash([]);
  for(const i of [0,64,128,192,255]){ctx.fillStyle='#74816e';ctx.fillText(String(i),left+iw*i/255-7,h-8);}
}
function strip(id, colors){const c=$(id),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);colors.forEach((rgb,i)=>{ctx.fillStyle=`rgb(${rgb.map(v=>Math.round(Math.min(1,Math.max(0,v))*255)).join(',')})`;ctx.fillRect(i*c.width/colors.length,0,c.width/colors.length+1,c.height);});}
function renderNativeGamma(report){
  $('nativeGammaPlot').hidden=!report;
  if(!report)return;
  const canvas=$('nativeGammaCurve'),ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height;
  const parameterMode=$('nativeGammaMode').value==='parameters',knots=report.parameter_knots,editing=Boolean(diagnosticData?.draft&&$('liveEdit').checked);
  const xs=parameterMode?knots.input_14bit:report.runtime_samples.input_14bit;
  const values=key=>parameterMode?knots[key+'_output_14bit']:report.runtime_samples[key+'_output_14bit'];
  const xmax=parameterMode?Math.max(...xs):16383;
  const ymax=parameterMode?Math.max(16383,...values('baseline'),...values('fitted')):report.display_output_max;
  const left=70,top=32,right=w-24,bottom=h-44,iw=right-left,ih=bottom-top;
  ctx.clearRect(0,0,w,h);ctx.font='13px system-ui';ctx.setLineDash([]);ctx.lineWidth=1;
  ctx.fillStyle='#fff';ctx.fillRect(0,0,w,h);
  for(let i=0;i<=4;i++){
    const x=left+iw*i/4,y=bottom-ih*i/4;
    ctx.strokeStyle='#e3e8de';ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(right,y);ctx.stroke();
    ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x,bottom);ctx.stroke();
    ctx.fillStyle='#64715f';ctx.textAlign='right';ctx.fillText(String(Math.round(ymax*i/4)),left-8,y+4);
    ctx.textAlign='center';ctx.fillText(String(Math.round(xmax*i/4)),x,bottom+20);
  }
  for(const [key,color,dash]of [['baseline','#7c8796',[7,4]],['fitted','#16724b',[]]]){
    ctx.strokeStyle=color;ctx.lineWidth=key==='fitted'?2:1.8;ctx.setLineDash(dash);ctx.beginPath();
    values(key).forEach((v,i)=>{const x=left+iw*xs[i]/xmax,y=bottom-ih*v/ymax;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();
    ctx.setLineDash([]);ctx.fillStyle=color;
    const nodes=parameterMode?xs:report.input_14bit;
    const nodeValues=parameterMode?values(key):report[key].output_14bit;
    nodes.forEach((v,i)=>{ctx.beginPath();ctx.arc(left+iw*v/xmax,bottom-ih*nodeValues[i]/ymax,1.7,0,2*Math.PI);ctx.fill();});
  }
  ctx.textAlign='left';
  for(const [i,label,color,dash]of [[0,'原生 '+(report.baseline_name||'基线'),'#7c8796',[7,4]],[1,editing?'当前草稿':'本次拟合','#16724b',[]]]){
    const x=left+i*155;ctx.strokeStyle=color;ctx.setLineDash(dash);ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(x,14);ctx.lineTo(x+27,14);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle=color;ctx.fillText(label,x+34,19);
  }
  ctx.fillStyle='#64715f';ctx.textAlign='right';ctx.fillText('Gamma 内部输入码值',right,h-5);ctx.textAlign='left';ctx.fillText('输出码值',left,top+15);
  const fitted=knots.audit.fitted_shape,baseline=knots.audit.baseline_shape;
  const shape=(editing?'当前草稿128节点实测：单调 ':'128 节点实测：拟合单调 ')+(fitted.monotone?'通过':'未通过')+'、凹性 '+(fitted.concave?'通过':'未通过')+'（斜率上升 '+fitted.convex_transitions+' 处）；原生基线斜率上升 '+baseline.convex_transitions+' 处。';
  const controls='控制点使用实际非均匀输入轴：暗部密集，高光逐渐稀疏；最后节点 x = '+knots.input_14bit.at(-1)+'。';
  const constraints=editing?('原训练'+(report.training_constraints?.enabled?'启用了':'未启用')+'单调凹约束；当前编辑形状锁'+($('gammaShapeLock').checked?'开启':'关闭')+'，实际形状以下方审计为准。'):(report.training_constraints?.enabled?'本任务已启用单调凹硬约束。':'历史任务未启用本次单调凹硬约束。');
  const global=report.global_correction;const globalNote=global ? (editing?' 原训练整体矫正：':' 整体矫正：')+(global.selected_final?'已用于最终结果':global.accepted?'通过整数验收，最终采用其他候选':'未接受额外修改')+'。'+(global.color_recovery?.executed?' 已执行固定 Gamma 的 CC1 / block13 补调。':'') : '';
  const a=report.baseline.audit,b=report.fitted.audit;
  $('nativeGammaStatus').textContent=controls+constraints+shape+globalNote+(parameterMode?' 当前展示拟合参数值，圆点为原生节点，按实际坐标线性连接；凹性按相邻区间斜率检查。':' 当前展示逐整数码查表及固定对比度后的实际 MainGamma；最大单步：原生 '+a.max_step+' / 拟合 '+b.max_step+'，反向步数：'+a.negative_steps+' / '+b.negative_steps+'。整数取整可能产生单码斜率起伏，不能用逐码二阶差分代替参数凹性。')+' 图中内部码值不包含 CC1、PC 补偿或最终网格。';
}
function chart24(id,colors){const c=$(id),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);colors.forEach((rgb,i)=>{ctx.fillStyle=`rgb(${rgb.map(v=>Math.round(Math.max(0,Math.min(1,v))*255)).join(',')})`;ctx.fillRect(i%6*120,Math.floor(i/6)*120,118,118);});}
function renderComparison(){
  if(!diagnosticData)return;
  const groups=diagnosticData.tonal.groups,key=$('comparisonMode').value,g=groups[key],h=g.histogram;
  $('tonalMetrics').replaceChildren();
  const table=document.createElement('table');header(table,['分区','样本数','平均绝对误差','均方根误差','95%误差分位','平均 ΔE00','亮度 L* RMSE','染色 a*b* RMSE']);
  for(const item of Object.values(groups)){const tr=document.createElement('tr');for(const value of [item.label,item.samples,...(item.metrics?[item.metrics.mae,item.metrics.rmse,item.metrics.p95,item.metrics.perceptual?.delta_e00_mean,item.metrics.perceptual?.lightness_rmse,item.metrics.perceptual?.ab_rmse].map(v=>v===undefined?'—':v.toFixed(2)):Array(6).fill('—'))]){const td=document.createElement('td');td.textContent=value;tr.append(td);}table.append(tr);}$('tonalMetrics').append(table);
  ['Red','Green','Blue'].forEach((c,i)=>{if(h){histogram($('hist'+c),h.target[i],h.after[i],['#be4f4b','#4e8958','#4a73b7'][i]);$('hist'+c+'Title').textContent=['红色','绿色','蓝色'][i]+'通道 · 重合 '+h.overlap_percent[i].toFixed(2)+'% · RMSE '+g.metrics.channel_rmse[i].toFixed(2);}else{const canvas=$('hist'+c);canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height);$('hist'+c+'Title').textContent=['红色','绿色','蓝色'][i]+'通道 · 无样本';}});
  $('histMean').textContent=h?'平均重合 '+h.mean_overlap_percent.toFixed(2)+'%':'无样本';
  $('histStatus').textContent=`${g.label}：${g.samples} 个独立测试样本。表格误差为真实 8 位整数 RGB 的码值误差；不扣黑。`;
  const m=groups.all.metrics,values=[m.mae,m.rmse,m.p95];
  document.querySelectorAll('#metrics strong').forEach((el,i)=>el.textContent=values[i].toFixed(2));
  document.querySelectorAll('#metrics small').forEach(el=>el.textContent='双方量化为 8 位后计算');
}

function renderNativeStages(fitting){
  const area=$('nativeStages');area.replaceChildren();
  if(!fitting?.training_pipeline){area.textContent='历史任务未使用新版分阶段原生训练；重新拟合后生效。';return;}
  const table=document.createElement('table');header(table,['训练阶段','灰阶训练 RMSE','验证 RMSE','验证 ΔE00','固定评分']);
  const labels={'baseline':'原厂基线','monotone-seed':'初始单调曲线','native-gray-tone-gamma-only':'① 仅 Gamma · 灰阶明暗','train-precondition':'② 原生颜色初始化','train-precondition-tone':'② 明暗曲线后的颜色初始化','gray-first':'③ 历史灰阶优先','gray-refinement-candidate':'③ 灰阶专项候选（等权选优）','native-chroma-cc1-block13-gamma-frozen':'④ 固定 Gamma · CC1 / block13','gray-priority-joint':'⑤ 历史灰阶优先联合优化','balanced-joint':'⑤ 四组等权联合优化','weighted-joint':'⑤ 按设置权重联合优化'};
  for(const row of fitting.history){const [stage,strategy]=row.label.split(' / ');if(!labels[stage]&&!/^(integrated-native-PC-|multi-start-|adaptive-round-|integer-refinement|PC-integer-refinement)/.test(stage))continue;const tr=document.createElement('tr');const suffix=strategy==='dense-compressed'?' · 大网格压缩':strategy==='direct'?' · 直接小网格':'';for(const value of [(labels[stage]||(stage.startsWith('multi-start-')?'多起点 '+stage.split('-').at(-1):stage.startsWith('adaptive-round-')?'动态权重第 '+stage.split('-').at(-1)+' 轮':stage.includes('integer-refinement')?'量化后微调':'⑥ 原生与 PC 交替 '+stage.split('-').at(-1)))+suffix+(row.label===fitting.selected?' · 已选':''),row.gray_training?.rmse_8bit?.toFixed(3)??'—',row.validation.rmse_8bit.toFixed(3),row.perceptual_validation?.delta_e00_mean?.toFixed(3)??'—',row.selection_score?.toFixed(3)??'—']){const td=document.createElement('td');td.textContent=value;tr.append(td);}table.append(tr);}
  const note=document.createElement('p');note.className='hint';note.textContent=(fitting.pc_compensation_training?'阶段指标按原生参数 + PC 残差整链评估。':'阶段指标按原生参数评估。')+(fitting.group_total_weights?`本任务总权重：随机色 ${fitting.group_total_weights.random} / 正色 ${fitting.group_total_weights.primaries} / 灰阶 ${fitting.group_total_weights.gray} / 24色 ${fitting.group_total_weights.colorchecker24}${fitting.group_total_weights.sector16!=null?' / 矩阵16色相 '+fitting.group_total_weights.sector16:''}。`:'')+'验证集只参与候选选择；独立测试不参与求解或选择。';area.append(table,note);if(fitting.tonal_balance){const tone=document.createElement('p');tone.className='hint';const c=fitting.tonal_balance.counts.random;tone.textContent=`已启用亮度分层平衡：以固定 ST 基线分区，组内阴影／中间调／高光等总权重；随机训练样本原始覆盖 ${c.train.join(' / ')}，验证 ${c.valid.join(' / ')}，独立测试 ${c.test.join(' / ')}。上述为完整数据分组计数，求解保留既有随机子采样；缺失分区不虚构样本。上方输出分区统计仍按 LUT 目标划分。`;area.append(tone);}if(fitting.search_options){const extra=document.createElement('p');extra.className='hint';extra.textContent=`${fitting.search_options.native_sequential_precision ? "Gamma → CC1 → block13 顺序精训 / " : ""}${fitting.search_options.postfit_deburr ? "本任务先拟合后去毛刺 · 24色相锚点保护 / " : ""}本任务平滑 ${fitting.search_options.parameter_smoothing ?? 0} / 输出连续性 ${fitting.search_options.output_continuity ?? 0} / ${fitting.search_options.starts} 个搜索起点 / 动态权重 ${fitting.search_options.adaptive_rounds} 轮 / Gamma与色彩交替 ${fitting.search_options.gamma_color_rounds ?? 0} 轮 / 感知权重 ${fitting.search_options.perceptual_weight} / 量化微调 ${fitting.search_options.quantization_sweeps} 轮。`;area.append(extra);if(fitting.adaptive_history?.length){const log=document.createElement('p');log.className='hint';log.textContent=fitting.adaptive_history.map(r=>`第 ${r.round} 轮权重：`+Object.values(r.weights).map(v=>v.toFixed(2)).join(' / ')).join('；');area.append(log);}}
  renderOutputContinuity(area,fitting.output_continuity);
}
function renderOutputContinuity(area,report){
  if(!report?.enabled)return;
  const title=document.createElement("p");title.className="hint";title.textContent=`输出连续性探针：${report.probes} 个颜色、${report.triplets} 组局部邻点。检查实际整数输出；数值越低表示局部色度变化越平顺。`;
  const table=document.createElement("table");header(table,["连续变化方向","色度二阶差分 P95","最大值"]);
  const names={"dark-exposure":"暗部明暗","full-exposure":"全范围明暗","hue":"局部色相","saturation":"局部饱和度"};
  for(const [name,m] of Object.entries(report.axes)){const tr=document.createElement("tr");for(const value of [(name.startsWith("native-")?"预矩阵 · "+names[name.slice(7)]:"色卡 · "+(names[name]||name)),m.chroma_second_difference_p95.toFixed(3),m.chroma_second_difference_max.toFixed(3)]){const td=document.createElement("td");td.textContent=value;tr.append(td);}table.append(tr);}
  area.append(title,table);
}
function renderPCReport(report){
  const area=$('pcStages');area.replaceChildren();area.hidden=!report;$('pcCurves').hidden=!report?.curves;
  if(!report)return;
  const qaqMode=report.curves?.mode==='qaq-grid';
  const rgbMode=report.curves?.mode==='rgb-independent';
  if(qaqMode)$('pcCurves').hidden=true;
  const table=document.createElement('table');header(table,['阶段','灰阶训练 RMSE','独立测试 RMSE','独立测试 ΔE00']);
  for(const [key,label]of [['native','原生模型'],['tone',rgbMode?'① RGB 独立曲线':'① 灰阶明暗'],['tint',rgbMode?'RGB 曲线输出':'② 灰阶染色'],['compensated',report.curves?(report.fitting?.strategy==='none'?'最终输出（未启用网格）':(qaqMode?gridResponseName(report.response):'③ 彩色网格（保护灰阶）')):'旧版单网格']]){
    if(qaqMode&&['tone','tint'].includes(key))continue;const gray=report.metrics.gray_training[key],test=report.metrics.test[key];if(!gray||!test)continue;
    const tr=document.createElement('tr');for(const value of [label,gray.rmse.toFixed(3),test.rmse.toFixed(3),test.perceptual?.delta_e00_mean?.toFixed(3)??'—']){const td=document.createElement('td');td.textContent=value;tr.append(td);}table.append(tr);
  }area.append(table);
  if(report.fitting?.strategy){const note=document.createElement("p");note.className="hint";note.textContent=report.fitting.strategy==='none'?'仅独立曲线／曲线阶段，未启用三维网格。':report.fitting.strategy==="dense-compressed"?"已选：17×33×33 大网格 → 密集采样压缩 → 5×9×9 / 7位。":"已选：直接拟合 5×9×9 小网格。";area.append(note);}
  if(qaqMode){const note=document.createElement("p");note.className="hint";note.textContent="网格响应："+JSON.stringify(report.response)+"。"+(Array.isArray(report.response)?"BT.601 暂定坐标 → 三线性插值 / 256 → 固定响应 → 加回原生输出。":"按任务保存的实测坐标与响应预测；覆盖范围以任务绑定模型报告为准，未覆盖区域为外推。");area.append(note);return;}
  if(!report.curves)return;
  const v=report.curves;
  function plot(id,series,low,high){
    const canvas=$(id),ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height,p=30;
    ctx.clearRect(0,0,w,h);ctx.strokeStyle='#d7dce2';ctx.lineWidth=1;
    for(let i=0;i<=4;i++){const y=p+(h-2*p)*i/4;ctx.beginPath();ctx.moveTo(p,y);ctx.lineTo(w-p,y);ctx.stroke();ctx.fillStyle='#667085';ctx.font='12px sans-serif';ctx.fillText(((high-(high-low)*i/4)*255).toFixed(0),1,y+4);}
    if(low<0){const y=p+high/(high-low)*(h-2*p);ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(p,y);ctx.lineTo(w-p,y);ctx.stroke();ctx.setLineDash([]);}
    for(const [values,color]of series){ctx.beginPath();ctx.strokeStyle=color;ctx.lineWidth=2;values.forEach((y,i)=>{const x=p+v.axis[i]*(w-2*p),yy=p+(high-y)/(high-low)*(h-2*p);if(i)ctx.lineTo(x,yy);else ctx.moveTo(x,yy);});ctx.stroke();}
    ctx.fillStyle='#667085';ctx.fillText('0',p,h-5);ctx.fillText('255',w-p-22,h-5);
  }
  $('pcToneTitle').textContent=rgbMode?'RGB 独立曲线 · 各通道输入 → 输出':'灰阶亮度曲线';$('pcTintTitle').textContent=rgbMode?'RGB 独立曲线 · 相对恒等映射偏移':'灰阶染色曲线 · 红 / 绿 / 蓝通道偏移';
  if(rgbMode){const colors=['#be4f4b','#4e8958','#4a73b7'];plot('pcToneCurve',[0,1,2].map(c=>[v.rgb.map(row=>row[c]),colors[c]]),0,1);const offset=v.rgb.map((row,i)=>row.map(x=>x-v.axis[i]));const range=Math.max(8/255,...offset.flat().map(Math.abs))*1.15;plot('pcTintCurve',[0,1,2].map(c=>[offset.map(row=>row[c]),colors[c]]),-range,range);return;}
  plot('pcToneCurve',[[v.tone,'#5e6977']],0,1);
  const bound=Math.max(8/255,...v.tint.flat().map(Math.abs))*1.15;
  plot('pcTintCurve',[0,1,2].map((c)=>[v.tint.map(row=>row[c]),['#be4f4b','#4e8958','#4a73b7'][c]]),-bound,bound);
}

async function loadDiagnostics(identifier){
  liveSerial++;clearTimeout(liveTimer);
  $('resultMode').disabled=true;
  const request=++diagnosticSerial;const changingJob=validationJob!==identifier;
  let compression;
  try{compression=await(await api('/api/jobs/'+identifier+'/grid-training')).json();}
  catch(e){if(request===diagnosticSerial){$('resultMode').disabled=false;$('histStatus').textContent='压缩状态读取失败：'+e.message;}return;}
  if(request!==diagnosticSerial||identifier!==jobId)return;
  if(compression.key)gridKeys.set(identifier,compression.key);else gridKeys.delete(identifier);
  if(compression.report?.before_gray_refinement_key)beforeGrayKeys.set(identifier,compression.report.before_gray_refinement_key);else beforeGrayKeys.delete(identifier);
  $('grayRefinementViewFields').hidden=!beforeGrayKeys.has(identifier);
  $('grayRefinementView').disabled=$('resultMode').value!=='compressed';
  if(changingJob)$('grayRefinementView').value='after';
  $('resultMode').querySelector('option[value=compressed]').disabled=!compression.key;

  if(['queued','running'].includes(compression.status)){compressionBusy=true;pollCompression(identifier);}

  $('distillGrid').disabled=busy||compressionBusy;$('distillStatus').textContent='';$('distillMetrics').replaceChildren();$('distillGray').hidden=true;$('distillDownload').hidden=true;$('gridFirmwareDownload').hidden=true;$('addCompressed').hidden=true;
  if(changingJob){photoSourceSha=undefined;clearActual();$('resultMode').value=gridKeys.has(identifier)?'compressed':pcJobs.has(identifier)?'pc':'native';}
  if($('resultMode').value==='compressed'&&!gridKeys.has(identifier))$('resultMode').value=pcJobs.has(identifier)?'pc':'native';
  $('resultMode').querySelector('option[value=pc]').disabled=!pcJobs.has(identifier);$('pcDownload').hidden=!pcJobs.has(identifier);$('pcDownload').href='/api/jobs/'+identifier+'/pc-download';$('trainingResult').hidden=false;
  $('grayRefinementView').disabled=$('resultMode').value!=='compressed';
  if(compression.report){try{renderCompression(compression.report,compression.key,identifier);}catch(e){$('distillStatus').textContent='压缩报告显示失败：'+e.message;}}
  if(selectedGrid()&&selectedGrid()!==compression.key){
    try{const before=await(await api('/api/jobs/'+identifier+'/grid-training?key='+selectedGrid())).json();
      if(request===diagnosticSerial&&before.report)strip('distillStudentGray',before.report.samples.gray_grid);
    }catch(e){$('histStatus').textContent=e.message;}
  }
  validationJob=undefined;$('rawExport').disabled=true;$('rawTask').textContent='正在读取当前任务配方…';
  photoReady();$('photoResults').hidden=true;$('photoStatus').textContent='正在载入任务配方…';
  $('histStatus').textContent='正在计算测试集直方图与必拟合色卡…';
  try{const data=await(await api('/api/jobs/'+identifier+'/diagnostics?pc='+(pcView()?'1':'0')+'&grid='+(selectedGrid()||''))).json();if(identifier!==jobId||request!==diagnosticSerial)return;
    savedDiagnosticData=clone(data);diagnosticData=data;$('datasetStatus').textContent=data.dataset?.dataset_id?.startsWith('v4.5-')?'v4.5 · 5300K · 99,372 色块 · 中心5点均值（'+(data.dataset?.edit_validated?'Edit实采验证：模拟输入全部一致，最终PT输出1块微差':'PT模拟派生上下文，按任务保存的验证状态')+'）':data.dataset?.dataset_id==='v4-sony100mp-unity-sim-center5-20261027'?'v4 · unity-WB · 99,372 色块 · Edit PT 已验证 · 中心5点均值':'历史任务：按保存的色卡和基线显示';if(chartJob())$('datasetStatus').textContent+=' · 软件处理色卡目标（'+data.dataset.bits_per_channel+' 位 '+data.dataset.file_format.toUpperCase()+'）';renderComparison();renderNativeGamma(data.native_gamma);renderNativeStages(data.training_fitting);if(data.training_fitting?.convergence?.length){const rows=data.training_fitting.convergence;$('convergenceNote')?.remove();const note=document.createElement('p');note.id='convergenceNote';note.className='hint';note.textContent='求解诊断：'+rows.map(r=>r.stage+'：'+(r.native_strict_stopping?({projected_gradient:'投影梯度达到阈值',relative_objective_change:'相对目标变化达到阈值',solver_success:'求解器停止',evaluation_budget:'达到评估上限',iteration_budget:'达到迭代上限',line_search_failure:'线搜索停止，保留已验收最佳值',solver_failure:'求解器未收敛'}[r.stopping_reason]||r.stopping_reason):(r.budget_exhausted?'达到评估上限':r.converged?'已满足收敛条件':'未收敛'))+'（'+r.evaluations+'次，'+(r.native_strict_stopping?'8位尺度投影梯度 ':'最优性 ')+(r.native_strict_stopping?r.projected_gradient_inf_8bit:r.optimality).toExponential(2)+'）').join('；');$('trainingPolicy').after(note);}renderPCReport(data.grid_key?null:data.pc_report);$('trainingPolicy').textContent=data.fitting_policy+(data.white_balance?.enabled?` 白平衡联合训练（实验）：冷暖 ${data.white_balance.parameters.temperature_shift} K，绿／洋红 ${data.white_balance.parameters.tint}；LUT 目标固定，前端动态响应近似。BIN 不含白平衡。`:'');$('trainingBadge').textContent=pcJobs.has(identifier)?'含 PC 补偿':'仅原生参数';
    if(data.pc_enabled){palette('after',data.test_preview);$('previewBadge').textContent=algorithmName()+' · 非机内';}else{const native=await(await api('/api/jobs/'+identifier)).json();palette('after',native.result.preview.after);$('previewBadge').textContent='原生参数模型 · 实拍待验收';}
    const n=data.native_tonal.groups.all.metrics,c=data.tonal.groups.all.metrics;
    $('pcStatus').textContent=data.pc_enabled?`${algorithmName()} · 独立测试 RMSE：原生 ${n.rmse.toFixed(2)} → 当前 ${c.rmse.toFixed(2)}；灰阶色卡已显示补偿后结果。导出需选择原厂网格或完成压缩。`:'当前显示原生结果；新任务可在导入目标后开启 PC 补偿整体训练。';
    if(data.colorchecker24){
      for(const [key,title]of[['before','Before'],['target','Target'],['after','After']])chart24('cc24'+title,data.colorchecker24[key]);
      $('cc24Status').textContent='24 色全部参与优化 · 训练 RMSE / 8位：'+data.colorchecker24.metrics.after.rmse_8bit.toFixed(2)+'；顺序：'+data.colorchecker24.names.join('、');
    }else{
      for(const id of ['cc24Before','cc24Target','cc24After']){const c=$(id);c.getContext('2d').clearRect(0,0,c.width,c.height);}
      $('cc24Status').textContent='此历史任务未包含标准 24 色，请重新拟合。';
    }
    if(data.sector16){
      const sector=data.sector16;
      for(const [key,title]of[['before','Before'],['target','Target'],['after','After']]){
        const canvas=$('sector16'+title),ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);
        sector[key].forEach((rgb,i)=>{const row=i<48?i%3:3,col=i<48?Math.floor(i/3):i-48;ctx.fillStyle=`rgb(${rgb.map(v=>Math.round(v*255)).join(',')})`;ctx.fillRect(col*48,row*30,48,30);});
      }
      $('sector16Status').textContent=`64 个实采训练代表色 · RMSE / 8位 ${sector.metrics.after.rmse_8bit.toFixed(2)}（基线 ${sector.metrics.before.rmse_8bit.toFixed(2)}）。前三行为每节点三种明暗，末行为过渡色。基准最大坐标偏差 ${sector.audit.maximum_sector_error}/1024 圈。`;
      const table=document.createElement('table');header(table,['节点','目标坐标','基准实测坐标','当前实测坐标','RMSE / 8位']);
      for(let i=0;i<16;i++){const row=table.insertRow();for(const value of [i+1,sector.audit.knots[i],sector.audit.records.slice(i*3,i*3+3).map(r=>r.measured_sector).join(' / '),sector.current_sectors.slice(i*3,i*3+3).join(' / '),sector.nodes[i].metrics.rmse_8bit.toFixed(2)])row.insertCell().textContent=String(value);}
      $('sector16Details').replaceChildren(table);
    }else{
      for(const id of ['sector16Before','sector16Target','sector16After']){const c=$(id);c.getContext('2d').clearRect(0,0,c.width,c.height);}
      $('sector16Details').replaceChildren();$('sector16Status').textContent='历史任务未启用矩阵16色相训练分组，请重新拟合。';
    }
    if(data.anchors){
      for(const [key,title]of[['before','Input'],['target','Target'],['after','After']]){strip('primary'+title,data.anchors[key].slice(0,4));strip('gray'+title,data.anchors[key].slice(4,260));}
      const design=data.anchors.design;
      for(const cohort of ['primary','gray']){
        $(cohort+'DesignLabel').hidden=!design;$(cohort+'Design').hidden=!design;
        if(design)strip(cohort+'Design',cohort==='primary'?design.slice(0,4):design.slice(4,260));
      }
      const m=data.anchors.metrics;
      $('anchorStatus').textContent=`${data.fitting_policy||'历史任务；请重新拟合以应用当前四组等权设置。'} 全部 ${data.anchors.input.length} 个色块参与优化${data.white_balance?.enabled?'，白平衡前端使用实验近似':data.dataset?.dataset_id?.startsWith('v4.5-')?'，前端为5300K模拟派生上下文':'，前端为已验证的 unity-WB 模拟数据'}。正色训练 RMSE / 8位：${m.primaries.after.rmse_8bit.toFixed(2)}（基线 ${m.primaries.before.rmse_8bit.toFixed(2)}）；灰阶训练 RMSE / 8位：${m.gray.after.rmse_8bit.toFixed(2)}（基线 ${m.gray.before.rmse_8bit.toFixed(2)}）。`;
    }else{
      for(const id of ['primaryDesignLabel','primaryDesign','grayDesignLabel','grayDesign'])$(id).hidden=true;
      for(const id of ['primaryInput','primaryTarget','primaryAfter','grayInput','grayTarget','grayAfter']){const c=$(id);c.getContext('2d').clearRect(0,0,c.width,c.height);}
      $('anchorStatus').textContent='旧任务未使用正色与完整灰阶训练。请使用原 LUT 重新拟合；旧结果不会自动变成新版结果。';
      $('histStatus').textContent=`旧任务独立测试集 ${data.histogram.samples} 个样本；该任务未纳入新增色卡。`;
    }
    validationJob=identifier;renderGamma();scheduleDraftDiagnostics();const wbActive=data.white_balance&&Object.values(data.white_balance.parameters).some(v=>v!==0);$('rawTask').textContent=wbActive?'此任务含实验白平衡，验证 ARW 暂不能完整复现；请使用浏览器预览。':'配方任务：'+identifier+'；写入 RAW 的'+(data.dataset?.look==='PT'?'人像（PT）':'标准（ST）')+'外观。';$('rawExport').disabled=wbActive||!rawFile||rawBusy;
    photoReady();$('photoStatus').textContent=chartJob()?'本任务为色卡目标：支持色块验证及参数 ARW 导出，不提供任意 RAW 目标照片渲染。':'当前任务：'+identifier+'；选择 RAW 后生成两张图。';
    const saved=await(await api('/api/jobs/'+identifier)).json();
    if(identifier===validationJob&&request===diagnosticSerial&&!chartJob()){
      const previews=saved.photo_previews|| (saved.photo_preview?[saved.photo_preview]:[]);
      const sourceSha=photoSourceSha||previews.at(-1)?.result.source_sha256;
      const currentPreviews=previews.filter(p=>p.result.source_sha256===sourceSha&&p.result.preview_long_edge===3840);
      if(!currentPreviews.length&&previews.some(p=>p.result.source_sha256===sourceSha))$('photoStatus').textContent='历史预览为低分辨率，请重新导入 RAW 生成 4K 对照图';
      const matching=currentPreviews.filter(p=>Boolean(p.result.pc_compensation_enabled)===pcView()&&photoGridMatches(p.result)&&(p.result.grid_key||undefined)===selectedGrid()&&(!pcView()||p.result.pc_compensation_sha256===data.pc_sha256)&&(!selectedGrid()||p.result.grid_sha256===data.grid_sha256));
      if(matching.length)showPhoto(matching.at(-1));
      else if(currentPreviews.length&&!photoBusy){
        try{const r=await(await api('/api/preview-reuse',{job:identifier,preview:currentPreviews.at(-1).id,pc:pcView(),grid:selectedGrid(),grid_effect:photoGridEffect()})).json();photoBusy=true;photoReady();photoId=r.id;pollPhoto();}
        catch(e){if(photoFile)$('photoRender').click();else $('photoStatus').textContent=e.message;}
      }
    }
  }catch(e){if(identifier!==jobId)return;$('histStatus').textContent='诊断生成失败：'+e.message;}
  finally{if(request===diagnosticSerial)$('resultMode').disabled=false;}
}

function renderCompression(r,key,identifier){
        const table=document.createElement('table'),head=table.createTHead().insertRow();
        for(const text of ['样本','原组合→LUT RMSE','单网格→LUT RMSE','压缩损失 RMSE']){const th=document.createElement('th');th.textContent=text;head.append(th);}
        const labels={gray_training:'灰阶（训练）',primaries_training:'正色（训练）',colorchecker24_training:'24色（训练）',validation:'验证集',test:'独立测试',unseen_synthetic:'独立合成探针'};
        for(const [name,m]of Object.entries(r.metrics)){if(!m||typeof m!=='object'||!m.grid_vs_combined?.groups?.all?.metrics)continue;const row=table.insertRow();for(const text of [labels[name]||name,m.combined_vs_lut?.groups?.all?.metrics?.rmse?.toFixed(3)??'—',m.grid_vs_lut?.groups?.all?.metrics?.rmse?.toFixed(3)??'—',m.grid_vs_combined.groups.all.metrics.rmse.toFixed(3)])row.insertCell().textContent=text;}
        $('distillMetrics').replaceChildren(table);
        const stack=r.fitting?.stack_experiment;
        if(stack){
          const note=document.createElement('p');note.className='hint';
          note.textContent=`NC叠加训练：同向约束30＋RGB/ΔE00损失对齐＋CC1/block13与网格交替＋任务感知整数优化＋目标导数匹配。已执行 ${stack.rounds.length} 轮；验证集选中 ${stack.selected}。Gamma冻结；最终指标来自实际整数网格。`;
          const rounds=document.createElement('table');
          for(const [i,values]of [['阶段','TRAIN颜色损失','同向惩罚','导数惩罚','验证颜色损失'],['起点',stack.seed.train.data,stack.seed.train.direction,stack.seed.train.derivatives,stack.seed.validation],...stack.rounds.map(v=>['第'+v.round+'轮',v.train.data,v.train.direction,v.train.derivatives,v.validation])].entries()){
            const row=rounds.insertRow();for(const value of values){const cell=document.createElement(i?'td':'th');cell.textContent=typeof value==='number'?value.toFixed(6):value;row.append(cell);}
          }
          const comparison=document.createElement('div');comparison.textContent='正在加载基准与叠加结果对照…';
          $('distillMetrics').append(note,rounds,comparison);
          fetch('/api/jobs/'+identifier+'/stack-comparison').then(response=>{if(!response.ok)throw Error('对照报告尚未就绪');return response.json();}).then(result=>{
            const t=document.createElement('table');
            const names=[['rgb_rmse','RGB RMSE'],['delta_e00_mean','平均ΔE00'],['lightness_rmse','L* RMSE'],['ab_rmse','a/b RMSE'],['chroma_rmse','彩度RMSE'],['hue_mae_deg','色相MAE°']];
            const head=t.createTHead().insertRow();for(const label of ['分组','指标','本款叠加前基准','本款正式结果']){const c=document.createElement('th');c.textContent=label;head.append(c);}
            for(const group of ['validation','test','gray_train'])for(const [metric,label]of names){const row=t.insertRow();for(const value of [group,label,result[group].parent[metric],result[group].stack[metric]])row.insertCell().textContent=typeof value==='number'?value.toFixed(6):(value??'—');}
            const caption=document.createElement('p');caption.className='hint';caption.textContent='上表为最终整数网格的浮点输出误差；下方原有报告保留8-bit显示指标。测试集仅在最终选定后评估。'+(result.companion_source?.native_parameters_identical_to_base===false?' NC-HueDir30为独立训练，实际原生参数不同；三支仅作结果比较。':'');comparison.replaceChildren(caption,t);
          }).catch(error=>{comparison.textContent='叠加对照报告：'+error.message;});
        }
        renderOutputContinuity($('distillMetrics'),r.fitting?.output_continuity?.final_grid);
        const deburr=r.fitting?.postfit_deburr;
        if(deburr?.enabled){
          const note=document.createElement('p');note.className='hint';
          const reasons={no_extra_train_backsteps:'未发现需要修补的额外反跳',all_integer_candidates_rejected:'修补未通过色差或锚点保护检查',continuous_projection_has_no_changed_integer_candidate:'整数量化后没有可用的修补',missing_24_hue_anchor_evidence:'缺少完整24色相锚点',no_local_repair_preserving_target_turns_and_anchors:'没有兼顾真实转折与锚点的局部修补'};
          const before=deburr.before?.shape,after=deburr.after?.shape;
          note.textContent='拟合后去毛刺：'+(deburr.accepted?'已接受，修改 '+deburr.changed_coefficients+' 个网格系数。':'保留拟合结果，'+(reasons[deburr.reason]||'未找到通过验收的局部修补')+'。')+(before?' 额外反跳 '+before.extra_events+' → '+(after?.extra_events??before.extra_events)+'，较大反跳 '+before.severe_events+' → '+(after?.severe_events??before.severe_events)+'。':'')+' 修补使用 Fritsch–Carlson 保形插值，保护24色相锚点与完整明暗轨道。';
          $('distillMetrics').append(note);
        }
        const hueDirection=r.fitting?.hue_direction?.final_grid;
        if(hueDirection){
          const note=document.createElement('p');note.className='hint';
          note.textContent=`色相-亮度偏移同向约束：强度 ${hueDirection.strength}，24 条 TRAIN 轨道 ${hueDirection.reliable_edges} 个可靠相邻步进；反向 ${hueDirection.opposite_edges} 个，同向率 ${(hueDirection.agreement_rate*100).toFixed(2)}%，最大反向 ${hueDirection.maximum_reverse_degrees.toFixed(3)}°，平均环形步进误差 ${hueDirection.mean_circular_step_error_degrees.toFixed(3)}°。目标自身转折和低置信区不强制单调。`;
          $('distillMetrics').append(note);
        }
        const grayPolish=r.fitting?.post_gray_refinement;
        if(grayPolish?.enabled){
          const note=document.createElement('p');note.className='hint';
          note.textContent='已进行压缩后灰阶微调：'+grayPolish.accepted_moves+' 次整数更新。以下列出微调前后RMSE；预览和BIN均采用最终网格。';
          const comparison=document.createElement('table');comparison.innerHTML='<tr><th>分组</th><th>微调前RMSE</th><th>微调后RMSE</th></tr>';
          for(const [name,m]of Object.entries(r.metrics)){if(!m.before_gray_refinement_vs_lut)continue;const row=comparison.insertRow();for(const text of [labels[name]||name,m.before_gray_refinement_vs_lut.groups.all.metrics.rmse.toFixed(3),m.grid_vs_lut.groups.all.metrics.rmse.toFixed(3)])row.insertCell().textContent=text;}
          $('distillMetrics').append(note,comparison);
        }
        strip('distillTeacherGray',r.samples.gray_combined);strip('distillStudentGray',r.samples.gray_grid);$('distillGray').hidden=false;
        $('distillStatus').textContent=`已压缩为 405×3 个7位系数（1215 字节），触及幅度边界 ${(r.fitting.limit_fraction*100).toFixed(2)}%。所有 RMSE 均为实际 8 位码值。本次网格模型：${gridResponseName(r.identity.response)}；尚非 R5 实机验收。${r.white_balance?.enabled?' 白平衡仍在网格前单独运算，未压入网格；BIN 不含白平衡。':''}`;
        $('distillDownload').href='/api/jobs/'+identifier+'/grid-distillation-download?key='+key;$('distillDownload').hidden=false;$('gridFirmwareDownload').href='/api/jobs/'+identifier+'/grid-firmware-download?key='+key;$('gridFirmwareDownload').hidden=false;$('addCompressed').hidden=false;

}

function trainingProgressText(p){
  if(!p)return '';
  let text=` · ${p.stage} · 求解轮 ${p.round}/${p.total_rounds}`;
  if(p.gradient_workers)text+=` · CPU ${p.gradient_workers}线程`;
  if(p.gpu_backend)text+=` · ${p.gpu_backend}`;
  if(p.iteration!=null && p.stage!=='压缩网格求解')text+=` · 迭代 ${p.iteration}（评估 ${p.evaluations}/${p.max_evaluations} 上限）`;
  if(p.candidate)text+=` · 候选 ${p.candidate}`;
  if(p.sweep!=null)text+=` · 微调 ${p.sweep}/${p.total_sweeps} 轮`;
  if(p.point!=null)text+=` · ${p.family||'网格'} 点位 ${p.point}/${p.total_points}`;
  return text;
}

async function pollCompression(identifier){
  clearTimeout(compressionTimer);
  try{
    const state=await(await api('/api/jobs/'+identifier+'/grid-training')).json();
    if(identifier!==jobId){compressionBusy=false;return;}
    $('compressionTrainingStatus').textContent=(state.phase||'准备压缩训练')+trainingProgressText(state.training_progress);
    if(state.status==='done'||state.status==='error'){
      compressionBusy=false;$('distillGrid').disabled=busy;
      if(state.status==='error')throw Error(state.error);
      gridKeys.set(identifier,state.key);$('resultMode').querySelector('option[value=compressed]').disabled=false;
      $('resultMode').value='compressed';await loadDiagnostics(identifier);return;
    }
    compressionTimer=setTimeout(()=>pollCompression(identifier),1500);
  }catch(e){compressionBusy=false;$('distillGrid').disabled=busy;$('compressionTrainingStatus').textContent='压缩训练：'+e.message;}
}
async function poll(){
  try{const job=await(await api('/api/jobs/'+jobId)).json();$('jobStatus').textContent=job.phase+trainingProgressText(job.training_progress)+` · ${Math.round(((job.finished||Date.now()/1000)-job.started)/60)} 分钟`;$('log').textContent=job.log||'正在校验输入资料…';
    if(job.status==='done'||job.status==='error'){setBusy(false);$('jobDownload').hidden=false;$('jobDownload').href='/api/jobs/'+jobId+'/download';$('jobDownload').download='r5-fit.zip';if(job.status==='done'){if(job.result.pc_compensation?.enabled)pcJobs.add(job.id);if(job.result.grid_key)gridKeys.set(job.id,job.result.grid_key);showResult(job.result);}else{$('jobStatus').textContent=job.error;toast(job.error);}loadDiagnostics(jobId);return;}
    timer=setTimeout(poll,2000);
  }catch(e){setBusy(false);$('jobStatus').textContent='连接中断：'+e.message+'。重载页面可重新连接运行中任务。';}
}
async function loadLut(file){if(!file)return;if(!file.name.toLowerCase().endsWith('.cube')||file.size>64*1024*1024){toast('请选择 64 MiB 内的 .cube 文件');return;}lutText=await file.text();$('lutLabel').textContent=file.name;$('jobStatus').textContent=`已导入 ${(file.size/1024).toFixed(1)} KiB；请选择正确的输入色域。`;}
function postfitControls(){const enabled=$('postfitDeburr').checked;for(const id of ['parameterSmoothing','outputContinuity']){if(enabled)$(id).value=0;$(id).disabled=busy||enabled;}if(enabled)$('parameterSmoothingValue').textContent='0';}
function fitOptions(compression){const endpoint=$('endpoint').value===''?null:Number($('endpoint').value);if(endpoint!==null&&(!Number.isInteger(endpoint)||endpoint<0||endpoint>131071))throw Error('伽马最后一点必须为 0–131071 的整数，或留空');const group_weights={random:+$('weightRandom').value,primaries:+$('weightPrimaries').value,gray:+$('weightGray').value,colorchecker24:+$('weightCC24').value,sector16:+$('weightSector16').value};if(Object.values(group_weights).some(v=>!Number.isFinite(v)||v<0.05||v>64))throw Error('训练权重需在 0.05–64 之间');const postfit=$('postfitDeburr').checked;const search_options={native_strict_stopping:$('nativeStrictStopping').checked,gamma_global_correction:$('gammaGlobalCorrection').checked,gamma_color_recovery:$('gammaGlobalCorrection').checked,gamma_monotone_concave:$('gammaMonotoneConcave').checked,postfit_deburr:postfit,output_continuity:+$('outputContinuity').value,parameter_smoothing:+$('parameterSmoothing').value,hue_direction_strength:+$('hueDirectionStrength').value,starts:+$('searchStarts').value,adaptive_rounds:+$('adaptiveRounds').value,gamma_color_rounds:+$('gammaColorRounds').value,perceptual_weight:+$('perceptualWeight').value,quantization_sweeps:+$('quantizationSweeps').value,target_polish_rounds:+$('targetPolishRounds').value};const body={speed_priority:$('speedPriority').checked,target_kind:$('targetKind').value,dataset_id:$('chartVersion').value,target_id:chartTargetId,white_balance:$('wbTraining').checked,compression_training:compression||postfit,post_gray_refinement:false,pc_options:{curve_mode:$('pcCurveMode').value,grid_enabled:$('pcCurveMode').value==='qaq-grid'?true:$('pcGridEnabled').checked,response:selectedGridResponse()},search_options,group_weights,pc_compensation:$('pcTraining').checked,lut:lutText,gamut:$('gamut').value,evaluations:+$('evaluations').value,number:selected,short_name:draft.short_name,full_name:draft.full_name,gamma_endpoint128:endpoint};return body;}
async function initTrainedFilters(){
  const select=$('trainedFilter'),status=$('trainedFilterStatus');
  // Keep the batch result selector usable while a saved result is loading.
  select.hidden=false;
  select.disabled=false;
  select.replaceChildren(new Option('选择已完成的滤镜…',''));
  if(!boot.latest_batch){status.textContent='暂无已保存的批量训练。';return;}
  try{
    const batch=await(await api('/api/batches/'+boot.latest_batch)).json();
    const completed=batch.jobs.filter(job=>job.status==='done');
    for(const job of completed)select.append(new Option(job.name,job.id));
    select.disabled=false;
    select.value=new URLSearchParams(location.search).get('job')||'';
    status.textContent=`最近一批训练 · ${completed.length} / ${batch.jobs.length} 个滤镜已完成；选择后加载对应色块、指标与参数。`;
    select.onchange=()=>{
      if(!select.value)return;
      if(busy){select.value=jobId||'';toast('当前任务运行中，请完成后查看其他结果');return;}
      const url=new URL(location.href);url.searchParams.set('job',select.value);location.assign(url.href);
    };
  }catch(e){status.textContent='训练列表加载失败：'+e.message;}
}

function setBlock13Value(group,sector,index,value){
  if($('liveEdit').checked){
    const delta=value-draft.block13[0][sector][index];
    if(draft.block13.some(rows=>rows[sector][index]+delta < -8192||rows[sector][index]+delta > 8191)){toast('同步三端点后系数会越界，请减小改动');return;}
    for(const rows of draft.block13)rows[sector][index]+=delta;
  }else draft.block13[group][sector][index]=value;
}
function liveEditorControls(){
  const enabled=$('liveEdit').checked;
  if(enabled){$('ccSliderGroup').value='0';$('matrixEndpoint').value='0';}
  $('ccSliderGroup').disabled=enabled;$('matrixEndpoint').disabled=enabled;
  renderCC();renderMatrix();
}
function scheduleDraftDiagnostics(mode){
  clearTimeout(liveTimer);liveSerial++;
  if(!$('liveEdit')?.checked)return;
  if(!jobId||validationJob!==jobId||!savedDiagnosticData||!taskEntry){$('liveEditStatus').textContent='请先选择并载入一个已完成的训练任务。';return;}
  if(draft.number!==taskEntry.number){$('liveEditStatus').textContent='当前编辑配置不属于所选任务；请恢复本任务参数后再模拟。';return;}
  liveMode=mode||$('liveEditMode').value;$('liveEditStatus').textContent='草稿已改动，等待计算…';
  liveTimer=setTimeout(runDraftDiagnostics,250);
}
async function runDraftDiagnostics(){
  if(liveRunning){livePending=true;return;}
  if(!$('liveEdit').checked||!jobId||validationJob!==jobId||!savedDiagnosticData||!taskEntry||draft.number!==taskEntry.number)return;
  const request=liveSerial,identifier=jobId,mode=liveMode||$('liveEditMode').value,entrySignature=parameterSignature(draft),viewSignature=JSON.stringify([$('resultMode').value,selectedGrid()]);
  liveRunning=true;livePending=false;$('liveEditStatus').textContent='正在计算'+(mode==='full'?'完整测试集':'快速预览')+'…';
  try{
    const data=await(await api('/api/jobs/'+identifier+'/draft-diagnostics',{entry:clone(draft),pc:pcView(),grid:selectedGrid(),mode})).json();
    if(request!==liveSerial||identifier!==jobId||!$('liveEdit').checked||entrySignature!==parameterSignature(draft)||viewSignature!==JSON.stringify([$('resultMode').value,selectedGrid()]))return;
    renderLiveDiagnostics(data);
    const count=data.samples?.evaluated??data.sample_count??data.tonal?.groups?.all?.samples;
    const elapsed=data.elapsed_ms!==undefined?' · '+(data.elapsed_ms/1000).toFixed(2)+'秒':'';
    $('liveEditStatus').textContent=`草稿实时模拟 · ${mode==='full'?'完整测试集':'快速预览'}${count?' · '+count.toLocaleString()+' 样本':''}${elapsed} · 训练结果和文件未改变。`;
  }catch(error){if(request===liveSerial&&identifier===jobId&&$('liveEdit').checked)$('liveEditStatus').textContent='草稿模拟失败：'+error.message;}
  finally{liveRunning=false;if(livePending&&$('liveEdit').checked){livePending=false;clearTimeout(liveTimer);liveTimer=setTimeout(runDraftDiagnostics,100);}}
}
function hueMetrics(target,after){
  const hsl=rgb=>{const max=Math.max(...rgb),min=Math.min(...rgb),d=max-min,l=(max+min)/2;if(d<1e-12)return [0,0,l];const s=d/(1-Math.abs(2*l-1));let h=max===rgb[0]?((rgb[1]-rgb[2])/d)%6:max===rgb[1]?(rgb[2]-rgb[0])/d+2:(rgb[0]-rgb[1])/d+4;return [(h*60+360)%360,s,l];};
  let hue=0,count=0,targetCount=0,neutralCount=0,saturation=0,lightness=0;
  target.forEach((rgb,i)=>{const a=hsl(rgb.map(v=>Math.round(Math.max(0,Math.min(1,v))*255)/255)),b=hsl(after[i].map(v=>Math.round(Math.max(0,Math.min(1,v))*255)/255));saturation+=Math.abs(a[1]-b[1])*100;lightness+=Math.abs(a[2]-b[2])*100;if(a[1]>=.1){targetCount++;if(b[1]<.1)neutralCount++;}if(a[1]>=.1&&b[1]>=.1){hue+=Math.min(Math.abs(a[0]-b[0]),360-Math.abs(a[0]-b[0]));count++;}});
  return {hue:count?hue/count:null,count,targetCount,neutralCount,saturation:saturation/target.length,lightness:lightness/target.length};
}
function renderLiveDiagnostics(data){
  diagnosticData={...savedDiagnosticData,...data};renderComparison();if(data.native_gamma)renderNativeGamma(data.native_gamma);
  const preview=data.preview||(Array.isArray(data.test_preview)?{after:data.test_preview}:data.test_preview)||{};
  for(const id of ['before','target','after'])if(preview[id]?.length)palette(id,preview[id]);
  if(preview.saved?.length)palette('liveOriginal',preview.saved);else if(preview.before?.length)palette('liveOriginal',preview.before);
  $('liveOriginal').previousElementSibling.textContent=preview.saved?'保存的训练结果':'原厂基线';
  if(preview.target?.length)palette('liveTarget',preview.target);if(preview.after?.length)palette('liveAfter',preview.after);
  $('liveEditComparison').hidden=false;$('previewBadge').textContent='交互草稿 · '+algorithmName();$('pcStatus').textContent='当前色块与误差来自手动编辑草稿；保存的训练参数、补偿和网格未改变。';
  const metrics=data.tonal?.groups?.all?.metrics||{},perceptual=metrics.perceptual||{};
  const saved=data.saved_tonal?.groups?.all?.metrics||{},rows=[['RGB RMSE / 8位',metrics.rmse,saved.rmse],['平均 ΔE00',perceptual.delta_e00_mean,saved.perceptual?.delta_e00_mean],['亮度 L* RMSE',perceptual.lightness_rmse,saved.perceptual?.lightness_rmse],['彩度 C* RMSE',perceptual.chroma_rmse,saved.perceptual?.chroma_rmse],['Lab 色相 MAE / °',perceptual.hue_mae_deg,saved.perceptual?.hue_mae_deg]];
  let hue;
  if(preview.target?.length&&preview.target.length===preview.after?.length){hue=hueMetrics(preview.target,preview.after);rows.push(['HSL 色相 MAE / °',hue.hue],['饱和度 MAE / 百分点',hue.saturation],['HSL 亮度 MAE / 百分点',hue.lightness]);}
  $('liveEditMetrics').replaceChildren();for(const [label,value,original]of rows){const div=document.createElement('div'),title=document.createElement('span'),number=document.createElement('strong');title.textContent=label;number.textContent=Number.isFinite(value)?value.toFixed(2):'—';div.append(title,number);if(Number.isFinite(original)){const note=document.createElement('small');note.textContent='保存结果 '+original.toFixed(2)+' · 差值 '+(value-original>=0?'+':'')+(value-original).toFixed(2);div.append(note);}$('liveEditMetrics').append(div);}
  const ignored=data.entry_audit?.ignored_parameters||[];
  $('liveEditAudit').textContent=(data.simulation_note||'模拟当前训练共同参数：CC1基值、同步的block13三端点、Gamma前128点。')+(ignored.length?' 仅导出、不参与模拟：'+ignored.join('、')+'。':'')+(perceptual.hue_samples!==undefined?' Lab色相：双方C*≥5有效 '+perceptual.hue_samples+'/'+perceptual.hue_target_samples+'，草稿近灰 '+perceptual.hue_prediction_neutral_samples+'，覆盖 '+perceptual.hue_coverage_percent.toFixed(1)+'%。':'')+(hue?' HSL色相：目标S≥10%共 '+hue.targetCount+' 样本，其中 '+hue.neutralCount+' 个草稿降至近灰，角误差在双方S≥10%的 '+hue.count+' 样本统计；HSL与RGB使用同一8位量化。':'');
  if(data.anchors){for(const [key,title]of [['before','Input'],['target','Target'],['after','After']]){strip('primary'+title,data.anchors[key].slice(0,4));strip('gray'+title,data.anchors[key].slice(4,260));}const m=data.anchors.metrics;$('anchorStatus').textContent=`交互草稿 · 正色 RMSE ${m.primaries.after.rmse_8bit.toFixed(2)}；灰阶 RMSE ${m.gray.after.rmse_8bit.toFixed(2)}；目标及训练结果未改写。`;}
  if(data.colorchecker24){for(const [key,title]of [['before','Before'],['target','Target'],['after','After']])chart24('cc24'+title,data.colorchecker24[key]);$('cc24Status').textContent='交互草稿 · 24色 RMSE / 8位：'+data.colorchecker24.metrics.after.rmse_8bit.toFixed(2);}
  if(data.sector16){const sector=data.sector16;for(const [key,title]of [['before','Before'],['target','Target'],['after','After']]){const canvas=$('sector16'+title),ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);sector[key].forEach((rgb,i)=>{const row=i<48?i%3:3,col=i<48?Math.floor(i/3):i-48;ctx.fillStyle=`rgb(${rgb.map(v=>Math.round(v*255)).join(',')})`;ctx.fillRect(col*48,row*30,48,30);});}$('sector16Status').textContent='交互草稿 · 16色相代表色 RMSE / 8位：'+sector.metrics.after.rmse_8bit.toFixed(2);const table=document.createElement('table');header(table,['原生节点','目标坐标','基准坐标','草稿坐标','RMSE / 8位']);for(let i=0;i<16;i++){const row=table.insertRow();for(const value of [i+1,sector.audit.knots[i],sector.audit.records.slice(i*3,i*3+3).map(record=>record.measured_sector).join(' / '),sector.current_sectors.slice(i*3,i*3+3).join(' / '),sector.nodes[i].metrics.rmse_8bit.toFixed(2)])row.insertCell().textContent=String(value);}$('sector16Details').replaceChildren(table);}
}
function initInteractiveEditing(){
  for(let sector=0;sector<16;sector++){const option=document.createElement('option');option.value=sector;option.textContent=String(sector).padStart(2,'0');$('matrixSliderSector').append(option);}
  $('liveEdit').onchange=()=>{liveSerial++;clearTimeout(liveTimer);liveEditorControls();photoReady();if($('liveEdit').checked){$('photoResults').hidden=true;$('photoStatus').textContent='实时草稿更新色卡和指标；RAW预览仍绑定保存配方，关闭实时模拟后可生成。';}if($('liveEdit').checked)scheduleDraftDiagnostics();else{$('liveEditStatus').textContent='实时模拟已关闭；显示保存的训练结果。';$('liveEditComparison').hidden=true;if(savedNativePreview)for(const key of ['before','target','after'])palette(key,savedNativePreview[key]);if(jobId)loadDiagnostics(jobId);}};
  $('liveEditMode').onchange=()=>scheduleDraftDiagnostics();$('liveEditRefresh').onclick=()=>{if(!$('liveEdit').checked){$('liveEdit').checked=true;liveEditorControls();photoReady();$('photoResults').hidden=true;}scheduleDraftDiagnostics('full');};
  $('liveEditReset').onclick=()=>{if(!taskEntry){toast('请先载入已完成任务');return;}draftSource=undefined;selected=taskEntry.number;draft=clone(taskEntry);drafts.set(selected,clone(draft));showNames();document.querySelectorAll('.looks button').forEach(button=>button.classList.toggle('active',+button.dataset.number===selected));renderEditors();};
  $('gammaSlider').oninput=()=>setGammaValue(+$('gammaSlider').value);$('gammaShapeLock').onchange=renderGamma;
  $('gammaBlend').oninput=()=>{
    if(!taskEntry||draft.number!==taskEntry.number){toast('请先载入本任务参数');return;}
    const mix=+$('gammaBlend').value/100,residual=gammaResiduals(),rawBaseline=savedDiagnosticData?.native_gamma?.parameter_knots?.baseline_output_raw,original=rawBaseline?rawBaseline.map((value,i)=>value/2-residual[i]):boot.presets[+$('baselineLook').value].gamma_native_129,trained=taskEntry.gamma_native_129,x=gammaAxis();
    const values=trained.map((value,i)=>i===128?value:Math.round(original[i]*(1-mix)+value*mix));
    if($('gammaShapeLock').checked){
      values[0]=0;for(let i=1;i<128;i++)values[i]=Math.min(values[128],Math.max(values[i-1],values[i]));
      for(let pass=0;pass<4096;pass++){let changed=false;for(let i=1;i<127;i++){const minimum=Math.ceil(((values[i-1]+residual[i-1])*(x[i+1]-x[i])+(values[i+1]+residual[i+1])*(x[i]-x[i-1]))/(x[i+1]-x[i-1])-residual[i]-1e-9);if(values[i]<minimum){values[i]=minimum;changed=true;}}if(!changed)break;}
      if(values.slice(1,127).some((value,j)=>(value+residual[j+1]-values[j]-residual[j])*(x[j+2]-x[j+1])+1e-8<(values[j+2]+residual[j+2]-value-residual[j+1])*(x[j+1]-x[j]))){$('gammaPointStatus').textContent='该整数混合未通过凹性检查，保留当前草稿。';return;}
    }
    draft.gamma_native_129=values;$('gammaBlendValue').textContent=Math.round(mix*100)+'%';renderGamma();syncRaw();
  };
  const canvas=$('gammaChart');let dragging=false;
  const drag=event=>{const rect=canvas.getBoundingClientRect(),x=(event.clientX-rect.left)/rect.width*canvas.width,y=(event.clientY-rect.top)/rect.height*canvas.height,xs=gammaAxis(),physical=(x-60)/(canvas.width-76)*xs.at(-1);if(event.type==='pointerdown'){let nearest=0;for(let i=1;i<128;i++)if(Math.abs(xs[i]-physical)<Math.abs(xs[nearest]-physical))nearest=i;$('gammaIndex').value=nearest;renderGamma();}else setGammaValue((1-(y-20)/(canvas.height-55))*131071);};
  canvas.onpointerdown=event=>{dragging=true;canvas.setPointerCapture(event.pointerId);drag(event);event.preventDefault();};canvas.onpointermove=event=>{if(dragging)drag(event);};canvas.onpointerup=event=>{dragging=false;canvas.releasePointerCapture(event.pointerId);scheduleDraftDiagnostics();};canvas.onpointercancel=()=>{dragging=false;};
  for(const id of ['ccSliderGroup','ccSliderIndex','matrixSliderSector','matrixSliderIndex'])$(id).onchange=renderParameterSliders;
  $('ccSlider').oninput=()=>{draft.cc1_delta[+$('ccSliderGroup').value][+$('ccSliderIndex').value]=+$('ccSlider').value;renderCC();syncRaw();};
  $('matrixSlider').oninput=()=>{setBlock13Value(+$('matrixEndpoint').value,+$('matrixSliderSector').value,+$('matrixSliderIndex').value,+$('matrixSlider').value);renderMatrix();syncRaw();};
}

async function init(){
  try{boot=await(await api('/api/bootstrap')).json();
    measuredGridResponse=boot.grid_response;
    $('computeBackend').textContent=boot.compute_backend?.available?'Apple Metal GPU：浮点拟合、Gamma／色彩交替、整数颜色渲染、网格求解／压缩和批量色差。保留一次有上限的 CPU 浮点校正及阶段验收。':'CPU 8线程：当前服务未启用 Metal 训练；已运行任务保持原计算方式。';
    names.forEach((name,i)=>{const b=document.createElement('button');b.textContent=String(i+1);b.title='自定义配置 '+(i+1);b.dataset.number=i+1;b.onclick=()=>selectLook(i+1);$('looks').append(b);});
    for(const preset of boot.stock_grids){const o=document.createElement('option');o.value=preset.id;o.textContent=preset.label;o.title=JSON.stringify(preset.provenance);$('stockGrid').append(o);}
    names.forEach((name,i)=>{const o=document.createElement('option');o.value=i;o.textContent=chineseNames[i]+'（'+name+'）';$('baselineLook').append(o);});
    $('baselineLook').value='1';selectLook(1);renderCollection();
    initChartVersions();await applyFormalProfile();
    initFolderTraining();
    $('postfitDeburr').onchange=postfitControls;postfitControls();$('gammaMonotoneConcave').onchange=()=>{if(!$('gammaMonotoneConcave').checked)$('gammaGlobalCorrection').checked=false;};$('gammaGlobalCorrection').onchange=()=>{if($('gammaGlobalCorrection').checked)$('gammaMonotoneConcave').checked=true;};
    $('stockGrid').onchange=()=>{const preset=boot.stock_grids.find(p=>p.id===$('stockGrid').value);draftSource=preset?{kind:'stock',id:preset.id}:undefined;if(preset)draft.grid_5x9x9=clone(preset.grid_5x9x9);syncRaw();};
    $('baselineLook').onchange=()=>{baselineNote();renderGamma();};
    $('gridResponseModel').onchange=gridResponseControls;gridResponseControls();
    for(const id of ['shortName','lookName'])$(id).oninput=()=>{readNames();syncRaw();};
    $('reset').onclick=()=>{remember();const names={short_name:draft.short_name,full_name:draft.full_name};draftSource=undefined;draft={...clone(boot.presets[+$('baselineLook').value]),...names,number:selected};showNames();drafts.set(selected,clone(draft));renderEditors();};
    $('matrixEndpoint').onchange=renderMatrix;
    $('comparisonMode').onchange=renderComparison;
    $('nativeGammaMode').onchange=()=>renderNativeGamma(diagnosticData?.native_gamma);
    $('grayRefinementView').onchange=()=>{if(validationJob){$('photoResults').hidden=true;loadDiagnostics(validationJob);}};
    $('resultMode').onchange=()=>{if(validationJob){$('photoResults').hidden=true;loadDiagnostics(validationJob);}};
    $('photoGridEffect').onchange=()=>{ $('photoResults').hidden=true;if(validationJob)loadDiagnostics(validationJob); };
    $('photoInput').onchange=e=>{const file=e.target.files[0];if(!file)return;if(!/\.arw$/i.test(file.name)||file.size>512*1024*1024){toast('请选择 512 MiB 内的 R5 RAW');return;}photoFile=file;clearActual();$('photoResults').hidden=true;$('photoName').textContent=file.name+' · '+(file.size/1024/1024).toFixed(1)+' MiB';photoReady();};
    $('photoRender').onclick=async()=>{
      if(photoBusy||!photoFile||!validationJob||chartJob())return;
      photoBusy=true;photoReady();photoTask=validationJob;$('photoResults').hidden=true;$('photoStatus').textContent='正在上传 RAW，随后进行本地解码和渲染…';
      try{const response=await fetch('/api/preview?job='+photoTask+'&pc='+(pcView()?'1':'0')+'&grid='+(selectedGrid()||'')+'&grid_effect='+(photoGridEffect()?'1':'0'),{method:'POST',headers:{'Content-Type':'application/octet-stream','X-R5-Token':boot.token},body:photoFile});const value=await response.json();if(!response.ok)throw Error(value.error);photoId=value.id;clearTimeout(photoTimer);pollPhoto();}
      catch(e){photoBusy=false;photoReady();$('photoStatus').textContent='预览失败：'+e.message;}
    };
    $('photoZoom').onchange=()=>{for(const id of ['photoLut','photoModel','photoActual'])$(id).style.width=(+$('photoZoom').value*100)+'%';};
    $('photoActualInput').onchange=e=>{const file=e.target.files[0];if(!file)return;if(!['image/jpeg','image/png'].includes(file.type)||file.size>65*1024*1024){toast('请选择 65 MiB 内的 JPG / PNG');return;}clearActual();actualUrl=URL.createObjectURL(file);$('photoActual').onload=()=>{$('photoActual').hidden=false;$('photoActualEmpty').hidden=true;$('photoActualClear').hidden=false;$('photoActualName').textContent=file.name+' · '+$('photoActual').naturalWidth+' × '+$('photoActual').naturalHeight+'；请确认是同一 RAW、同一配方，裁切和方向一致。';};$('photoActual').onerror=()=>{clearActual();toast('软件导出图无法解码');};$('photoActual').src=actualUrl;};
    $('photoActualClear').onclick=clearActual;
    const panes=document.querySelectorAll('.photo-scroll');let syncing=false;panes.forEach(pane=>pane.onscroll=()=>{if(syncing)return;syncing=true;for(const other of panes){if(other===pane)continue;other.scrollLeft=pane.scrollLeft;other.scrollTop=pane.scrollTop;}requestAnimationFrame(()=>syncing=false);});
    initInteractiveEditing();
    $('gammaIndex').onchange=renderGamma;
    $('gammaLast').onclick=()=>{$('gammaIndex').value=128;renderGamma();$('gammaValue').focus();};
    $('gammaValue').onchange=()=>{const v=+$('gammaValue').value;if($('gammaValue').value===''||!Number.isInteger(v)||v<0||v>131071){toast('Gamma 必须为 0–131071 的整数');return;}setGammaValue(v);};

    $('gammaReset').onclick=()=>{draft.gamma_native_129=clone(boot.presets[+$('baselineLook').value].gamma_native_129);renderGamma();syncRaw();};
    document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>{document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b===button));document.querySelectorAll('.tab-panel').forEach(panel=>panel.hidden=panel.id!==button.dataset.tab);});
    $('applyRaw').onclick=async()=>{try{const value=JSON.parse($('rawEditor').value);if(value.number!==selected)throw Error('序号必须与当前配置一致');await api('/api/validate',project([value]));draft=value;showNames();renderEditors();toast('JSON 已应用');}catch(e){toast(e.message);}};
    $('add').onclick=async()=>{try{remember();const response=await(await api('/api/validate',exportProject([draft],new Map(draftSource?[[selected,draftSource]]:[])))).json();collection=collection.filter(e=>e.number!==selected);collection.push(clone(draft));collectionSources.set(selected,clone(draftSource));renderCollection();$('editStatus').textContent=`已加入导出集 · 文件检查通过 · 单项 ${response.bytes} 字节`;}catch(e){$('editStatus').textContent=e.message;toast(e.message);}};
    $('addCompressed').onclick=async()=>{try{const key=gridKeys.get(jobId);if(!jobId||!key)throw Error('请先完成压缩训练');const value=await(await api('/api/jobs/'+jobId+'/grid-firmware-config?key='+key)).json();const entry=value.entries[0];collection=collection.filter(e=>e.number!==entry.number);collection.push(clone(entry));collectionSources.set(entry.number,clone(value.export_sources[String(entry.number)]));draftSources.set(entry.number,clone(value.export_sources[String(entry.number)]));drafts.set(entry.number,clone(entry));renderCollection();draft=undefined;selectLook(entry.number);toast('本任务原生参数与压缩网格已一起加入导出集');}catch(e){toast(e.message);}};
    $('export').onclick=async()=>{try{const response=await api('/api/export',exportProject());download(await response.blob(),'r5-native-config.zip');toast('已导出 BIN、JSON 与校验回执');}catch(e){toast(e.message);}};
    $('saveProject').onclick=()=>download(new Blob([JSON.stringify(exportProject(),null,2)],{type:'application/json'}),'native_config.json');
    $('importProject').onchange=async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>131072)throw Error('配置 JSON 超过 128 KiB');const value=JSON.parse(await file.text());if(!value.export_sources)throw Error('旧配置缺少网格来源，请重新选择原厂网格或重新压缩');await api('/api/validate',value);collection=clone(value.entries);collectionSources.clear();for(const entry of collection)collectionSources.set(entry.number,clone(value.export_sources[String(entry.number)]));drafts.clear();draftSources.clear();draft=undefined;renderCollection();selectLook(collection[0]?.number||1);toast('配置已载入，导出集已替换');}catch(error){toast(error.message);}finally{e.target.value='';}};
    $('targetKind').onchange=()=>{
      $('chartTargetFields').hidden=!imageTarget();
      $('dropzone').hidden=imageTarget();
      $('gamut').closest('label').hidden=imageTarget();
    };
    $('targetKind').onchange();
    $('chartTarget').onchange=async e=>{
      const file=e.target.files[0];chartTargetId=undefined;
      if(!file)return;
      if(!/\.(tif|tiff|jpg|jpeg)$/i.test(file.name)||file.size>1024*1024*1024){$('chartTargetStatus').textContent='请选择 1 GiB 内的 TIFF 或 JPG';e.target.value='';return;}
      chartUploading=true;$('chartVersion').disabled=true;$('targetKind').disabled=true;$('chartTarget').disabled=true;$('fit').disabled=true;$('distillGrid').disabled=true;
      $('chartTargetStatus').textContent='上传并检查色卡布局、位深及色域…';
      try{
        const response=await fetch('/api/chart-target?dataset_id='+encodeURIComponent($('chartVersion').value),{method:'POST',headers:{'Content-Type':'application/octet-stream','X-R5-Token':boot.token},body:file});
        const value=await response.json();if(!response.ok)throw Error(value.error);
        chartTargetId=value.id;const name=file.name.replace(/\.[^.]+$/,'');$('shortName').value=name;$('lookName').value=name;readNames();syncRaw();$('chartTargetStatus').textContent=file.name+' · '+value.audit.bits_per_channel+' 位 · '+value.audit.samples+' 个目标色块已就绪';
      }catch(error){$('chartTargetStatus').textContent='导入失败：'+error.message;}
      finally{chartUploading=false;$('chartVersion').disabled=busy;$('targetKind').disabled=busy;$('chartTarget').disabled=busy;$('fit').disabled=busy;$('distillGrid').disabled=busy||compressionBusy;}
    };
    $('lut').onchange=e=>loadLut(e.target.files[0]);
    $('dropzone').ondragover=e=>{e.preventDefault();$('dropzone').classList.add('drag');};$('dropzone').ondragleave=()=>$('dropzone').classList.remove('drag');$('dropzone').ondrop=e=>{e.preventDefault();$('dropzone').classList.remove('drag');loadLut(e.dataTransfer.files[0]);};
    $('distillGrid').onclick=async()=>{
      if(busy||compressionBusy||chartUploading)return;
      if(targetReady()){$('fit').onclick(true);return;}
      try{
        if(!jobId)throw Error('请导入LUT，或选择已完成的PC补偿任务');
        await api('/api/grid-training',{job:jobId,response:selectedGridResponse(),post_gray_refinement:false});
        compressionBusy=true;$('distillGrid').disabled=true;pollCompression(jobId);
      }catch(e){toast(e.message);}
    };
    $('pcCurveMode').onchange=()=>{if($('pcCurveMode').value==='qaq-grid')$('pcGridEnabled').checked=true;};
    $('resetWeights').onclick=()=>{for(const id of ['weightRandom','weightPrimaries','weightGray','weightCC24','weightSector16'])$(id).value='1';};
    $('parameterSmoothing').oninput=()=>{$('parameterSmoothingValue').textContent=$('parameterSmoothing').value;};
    $('fit').onclick=async(compression=false)=>{compression=compression===true;try{if(chartUploading)throw Error('目标图仍在上传');if(!targetReady())throw Error(imageTarget()?'请先导入处理后的色卡目标图':'请先导入 .cube LUT');remember();const body=fitOptions(compression);const response=await(await api('/api/fit',body)).json();jobId=response.id;setBusy(true);$('jobDownload').hidden=true;$('jobStatus').textContent='任务已提交';clearTimeout(timer);poll();}catch(e){toast(e.message);}};
    $('cancel').onclick=async()=>{try{await api('/api/cancel',{id:jobId});$('jobStatus').textContent='正在取消…';}catch(e){toast(e.message);}};
    $('rawInput').onchange=e=>{const f=e.target.files[0];if(!f)return;if(!/\.arw$/i.test(f.name)||f.size>512*1024*1024){toast('请选择 512 MiB 内的 R5 ARW');return;}rawFile=f;$('rawName').textContent=f.name+' · '+(f.size/1024/1024).toFixed(1)+' MiB';$('rawExport').disabled=!validationJob||rawBusy||Boolean(diagnosticData?.white_balance&&Object.values(diagnosticData.white_balance.parameters).some(v=>v!==0));};
    $('rawExport').onclick=async()=>{if(!rawFile||!validationJob||rawBusy)return;const identifier=validationJob;rawBusy=true;$('rawExport').disabled=true;$('rawStatus').textContent='正在本地上传、校验并生成 ARW 副本，请稍候…';try{const response=await fetch('/api/raw-export?job='+identifier,{method:'POST',headers:{'Content-Type':'application/octet-stream','X-R5-Token':boot.token},body:rawFile});if(!response.ok){const error=await response.json();throw Error(error.error);}download(await response.blob(),rawFile.name.replace(/\.arw$/i,'')+'-Edit验证.zip');$('rawStatus').textContent='验证包已下载。打开包内 fitted-PT.ARW（新PT任务）或 fitted-ST.ARW（历史ST任务），在 Edit 显式选择对应外观。内嵌预览未重绘；请以实际渲染为准。';}catch(e){$('rawStatus').textContent='生成失败：'+e.message;toast(e.message);}finally{rawBusy=false;$('rawExport').disabled=!rawFile||!validationJob||Boolean(diagnosticData?.white_balance&&Object.values(diagnosticData.white_balance.parameters).some(v=>v!==0));}};
    for(const job of boot.history){if(job.pc_available)pcJobs.add(job.id);const option=document.createElement('option');option.value=job.id;option.textContent=new Date(job.started*1000).toLocaleString()+' · '+(job.target_kind==='chart-image'?'色卡目标 · ':'')+job.phase;$('history').append(option);}
    $('history').onchange=()=>{if(!$('history').value)return;if(busy){toast('当前任务运行中，请完成后查看历史');return;}jobId=$('history').value;$('trainedFilter').value=jobId;clearTimeout(timer);poll();};
    $('history').addEventListener('focus',async()=>{try{const value=await(await api('/api/bootstrap')).json();for(const job of value.history){if([...$('history').options].some(o=>o.value===job.id))continue;const option=document.createElement('option');option.value=job.id;option.textContent=new Date(job.started*1000).toLocaleString()+' · '+(job.target_kind==='chart-image'?'色卡目标 · ':'')+job.phase;$('history').append(option);}}catch{}});
    document.querySelector('.brand').onclick=e=>{e.preventDefault();document.querySelector('header').scrollIntoView({behavior:'smooth'});};
    await initTrainedFilters();
    const requestedJob=new URLSearchParams(location.search).get('job');
    // A saved job must expose the overall result block immediately; diagnostics
    // will fill its metrics and charts asynchronously.
    if(requestedJob)$('trainingResult').hidden=false;
    if(boot.jobs.length){jobId=boot.jobs[0];setBusy(true);poll();}
    else {
      const completed=boot.history.find(j=>j.status==='done');
      const restore=requestedJob&&boot.history.some(j=>j.id===requestedJob)?requestedJob:completed?.id;
      if(restore){jobId=restore;$('history').value=restore;await poll();}
    }
  }catch(e){$('jobStatus').textContent=e.message;toast('初始化失败：'+e.message);}
}
init();

function folderTargets(files){
  const selected=[...files].filter(f=>/\.(jpe?g|tiff?)$/i.test(f.name)).sort((a,b)=>a.name.localeCompare(b.name,'en',{numeric:true}) || (a.webkitRelativePath||a.name).localeCompare(b.webkitRelativePath||b.name));
  if(!selected.length||selected.length>12)throw Error('需要 1–12 张 JPG／TIFF，当前 '+selected.length+' 张；请分文件夹处理。');
  const seen=new Set();
  return selected.map((file,i)=>{
    const name=file.name.replace(/\.[^.]+$/,'');
    if(!name.trim()||new TextEncoder().encode(name).length>23)throw Error(file.name+'：简称超过 23 个 UTF-8 字节或为空，请先重命名。');
    if(seen.has(name.toLowerCase()))throw Error('名称重复：'+name+'；请先重命名。');
    if(file.size>1024*1024*1024)throw Error(file.name+' 超过 1 GiB');
    seen.add(name.toLowerCase());return {file,name,number:i+1};
  });
}
function initFolderTraining(){
  let targets=[],active=false;
  const storage='r5-folder-batch';
  async function pollBatch(id){
    try{
      const state=await(await api('/api/batches/'+id)).json();
      $('batchStatus').textContent=state.jobs.map(j=>j.name+'：'+j.phase+trainingProgressText(j.training_progress)).join('\n')+(state.error?'\n'+state.error:'');
      $('batchStatus').style.whiteSpace='pre-line';
      let links=$('batchJobLinks');if(!links){links=document.createElement('div');links.id='batchJobLinks';$('batchStatus').after(links);}links.replaceChildren();for(const j of state.jobs){const a=document.createElement('a');a.href='/?job='+j.id;a.textContent=j.name+' · '+j.status;a.style.marginRight='18px';links.append(a);}
      if(state.status==='done'){
        $('batchStatus').textContent='全部 '+state.jobs.length+' 项已训练、压缩并合并（'+state.bytes+' 字节）。实际颜色仍需验证。';
        for(const [element,file]of [['batchBin','R5NATIVE.BIN'],['batchConfig','native_config.json'],['batchAudit','export_audit.json']])$(element).href='/api/batches/'+id+'/'+file;
        $('batchDownloads').hidden=false;active=false;$('chartVersion').disabled=busy;
        if(state.jobs.length===1&&!busy&&jobId!==state.jobs[0].id){jobId=state.jobs[0].id;clearTimeout(timer);await poll();}
      }else if(state.status==='error'){active=false;$('chartVersion').disabled=busy;}
      else{setTimeout(()=>pollBatch(id),2000);return;}
      $('targetFolder').disabled=false;$('batchStart').disabled=!targets.length;
    }catch(e){$('batchStatus').textContent='连接中断：'+e.message+'；刷新可重连后台批量任务。';$('targetFolder').disabled=false;}
  }
  $('targetFolder').onchange=e=>{
    targets=[];$('batchStart').disabled=true;$('batchDownloads').hidden=true;
    try{targets=folderTargets(e.target.files);$('folderFiles').textContent=targets.map(t=>t.number+' · '+t.name+' / '+t.name+' ← '+(t.file.webkitRelativePath||t.file.name)).join('\n');$('batchStart').disabled=active;}
    catch(error){$('folderFiles').textContent=error.message;}
  };
  $('batchStart').onclick=async()=>{
    if(active||!targets.length)return;
    active=true;$('chartVersion').disabled=true;$('batchStart').disabled=true;$('targetFolder').disabled=true;$('batchDownloads').hidden=true;
    try{
      const options=fitOptions(true),files=[];
      for(const t of targets){
        $('batchStatus').textContent='上传并检查 '+t.number+'/'+targets.length+'：'+t.file.name;
        const response=await fetch('/api/chart-target?dataset_id='+encodeURIComponent($('chartVersion').value),{method:'POST',headers:{'Content-Type':'application/octet-stream','X-R5-Token':boot.token},body:t.file});
        const value=await response.json();if(!response.ok)throw Error(t.file.name+'：'+value.error);
        files.push({filename:t.file.name,target_id:value.id});
      }
      const state=await(await api('/api/batches',{files,options,concurrency:2})).json();
      localStorage.setItem(storage,state.id);pollBatch(state.id);
    }catch(error){active=false;$('chartVersion').disabled=busy;$('batchStatus').textContent='批量未启动：'+error.message;$('batchStart').disabled=false;$('targetFolder').disabled=false;}
  };
  const id=boot.latest_batch;if(id){localStorage.setItem(storage,id);active=true;$('targetFolder').disabled=true;pollBatch(id);}else{localStorage.removeItem(storage);}
}

function initChartVersions(){
  const select=$('chartVersion');
  for(const version of boot.chart_versions){const option=document.createElement('option');option.value=version.id;option.textContent=version.label;select.append(option);}
  select.value=boot.default_chart.schema;
  const update=()=>{
    const query='?dataset_id='+encodeURIComponent(select.value);
    $('chartRafDownload').href='/api/chart-original'+query;
    for(const [id,format]of [['chartArwDownload','arw'],['chartDngDownload','dng']]){
      $(id).hidden=!select.value.startsWith('v4.5-');$(id).href='/api/chart-file'+query+'&format='+format;
    }
    $('chartVersionStatus').textContent=select.value.startsWith('v4.5-')?'v4.5：以 DSC00569 的5300K白平衡为准，RAW已补偿以保持原颜色。ARW／DNG保留相同码值和WB；RAF按IED转换不加增益。保留拍摄白平衡，新目标必须从v4.5重新导出。':'v4历史色卡：unity-WB；仅用于旧版目标和旧任务。';
  };
  select.onchange=()=>{
    chartTargetId=undefined;$('chartTarget').value='';$('chartTargetStatus').textContent='色卡版本已切换，请上传该版本的导出图';
    $('targetFolder').value='';$('targetFolder').dispatchEvent(new Event('change'));update();
  };
  update();
}

async function applyFormalProfile(){
  const response=await fetch('/api/formal-profile');
  if(!response.ok)throw Error('正式配方加载失败');
  const profile=await response.json(), options=profile.options, s=options.search_options;
  const values={evaluations:options.evaluations,searchStarts:s.starts,adaptiveRounds:s.adaptive_rounds,
    gammaColorRounds:s.gamma_color_rounds,quantizationSweeps:s.quantization_sweeps,
    perceptualWeight:s.perceptual_weight,parameterSmoothing:s.parameter_smoothing,
    outputContinuity:s.output_continuity,hueDirectionStrength:s.hue_direction_strength,
    targetPolishRounds:s.target_polish_rounds,endpoint:131071,
    chartVersion:options.dataset_id,pcCurveMode:options.pc_options.curve_mode};
  for(const [id,value]of Object.entries(values)){if($(id)){ $(id).value=value;$(id).disabled=true;}}
  for(const id of ['weightRandom','weightPrimaries','weightGray','weightCC24','weightSector16']){$(id).value=1;$(id).disabled=true;}
  const checked={pcTraining:true,pcGridEnabled:true,wbTraining:false,speedPriority:false,
    nativeStrictStopping:true,gammaGlobalCorrection:true,gammaMonotoneConcave:true,postfitDeburr:true};
  for(const [id,value]of Object.entries(checked)){if($(id)){ $(id).checked=value;$(id).disabled=true;}}
  const notice=document.createElement('p');notice.className='hint';
  notice.textContent='当前固定为 Mac 4189 正式配方：原生12起点 → 五轮目标网格 → 三轮五项叠加。同向30、导数0.02；叠加阶段Gamma冻结；validation选优、test仅报告。浮点训练使用Apple Metal，原生整数颜色使用Metal并与CPU核验。';
  document.querySelector('.intro').append(notice);
  // Result loading and batch polling may change disabled flags. The fixed
  // profile remains visibly locked after those updates as well.
  const locked=[...Object.keys(values),...Object.keys(checked),'weightRandom','weightPrimaries',
    'weightGray','weightCC24','weightSector16','resetWeights'];
  const observer=new MutationObserver(()=>{for(const id of locked){if($(id)&&!$(id).disabled)$(id).disabled=true;}});
  for(const id of locked){if($(id)){ $(id).disabled=true;observer.observe($(id),{attributes:true,attributeFilter:['disabled']});}}
}
