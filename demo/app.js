'use strict';
const $ = id => document.getElementById(id);
const algorithms = ['given','nn','exhaustive','dp','ca-plus','ca-minus','nn+2opt','ca-plus+2opt','ca-minus+2opt','nn+2opt+reinsert','nn+2opt+reinsert-twice','nn+2opt+reinsert+segment-dp'];
const labels = {'given':'입력 순서','nn':'NN','exhaustive':'완전 탐색','dp':'DP','ca-plus':'CA-plus','ca-minus':'CA-minus','nn+2opt':'NN + 2-opt','ca-plus+2opt':'CA-plus + 2-opt','ca-minus+2opt':'CA-minus + 2-opt'};
Object.assign(labels, {
 'nn+2opt+reinsert':'NN + 2-opt + Reinsertion',
 'nn+2opt+reinsert-twice':'NN + 2-opt + Reinsertion 2회',
 'nn+2opt+reinsert+segment-dp':'제안 알고리즘 · NN + 2-opt + Reinsertion + Segment DP'
});
const patterns = {'clustered':'가까운 통로에 모아 배치','random-stow-like':'창고 전체에 흩어 배치','directional':'창고 뒤쪽에 배치','paired-far':'도착점에서 먼 쪽에 배치','paired-near':'도착점에 가까운 쪽에 배치'};
const statuses = {'completed':'완료','timeout':'시간 초과','resource_limit':'계산 규모 제한','error':'오류','invalid_input':'입력 오류','infeasible':'경로 없음'};
const terms = {'completed':'완료','local_optimum':'한 번 바꾸는 방법으로 더 짧은 경로를 찾지 못함','evaluation_limit':'평가 횟수 제한','deadline':'시간 제한','dp_size':'DP 위치 수 제한','exhaustive_size':'완전 탐색 위치 수 제한','dp_memory_estimate':'DP 메모리 추정 제한','allocation_failed':'메모리 할당 실패'};
Object.assign(terms, {'single_pass':'한 번 순회 완료','segment_resource_limit':'구간 DP 자원 제한'});
const scenarios = {
 I:['제안 알고리즘','같은 초기 경로에서 Reinsertion을 두 번 적용한 방법과 Reinsertion 후 Segment DP를 적용한 제안 알고리즘을 비교합니다.',20,'random-stow-like','nn+2opt+reinsert-twice','nn+2opt+reinsert+segment-dp'],
 A:['최적 경로 비교','작은 작업에서 완전 탐색과 DP의 결과를 비교합니다.',3,'clustered','exhaustive','dp'],
 B:['위치 수와 계산 시간','위치 수에 따라 DP의 시간과 완료 상태를 확인합니다.',15,'random-stow-like','dp','nn+2opt'],
 C:['물건이 많은 작업','큰 작업에서 빠른 방법들의 경로와 비용을 비교합니다.',50,'random-stow-like','nn','nn+2opt'],
 D:['가까이 모인 물건','인접한 통로에 모인 물건에서 경로 개선 효과를 살펴봅니다.',10,'clustered','nn','nn+2opt'],
 E:['물건 사이 거리','물건 사이의 실제 평균 통로 거리와 경로 개선을 살펴봅니다.',10,'random-stow-like','nn','nn+2opt'],
 F:['도착점과의 거리','같은 위치 구조를 좌우로 반사한 작업을 비교합니다. 출발점까지 거리도 함께 변합니다.',10,'paired-far','nn','nn'],
 G:['창고 뒤쪽 물건','창고 뒤쪽에 배치된 물건에서 컨베이어 고려 방법을 비교합니다.',10,'directional','nn','ca-minus'],
 H:['출발점 변경','같은 물건 집합에서 출발점만 바꿔 비교합니다.',10,'clustered','nn','nn']
};
let tasks = [], scenario = 'A', selectedTaskId = '', current = null, other = null, live = null, playing = false, frame = null, lastTime = 0, mapPaths = [], refreshToken = 0, aggregateToken = 0, cancelRecalculation = false;
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = (v, digits=2) => v == null || !Number.isFinite(v) ? '—' : Number(v).toFixed(digits);
const time = v => v == null ? '—' : `${fmt(v*1000,3)} ms`;
async function api(url, options) { if (typeof staticApi !== 'undefined') return staticApi(url); const r = await fetch(url, options); let data; try { data = await r.json(); } catch { throw new Error('서버 응답을 읽지 못했습니다.'); } if (!r.ok) throw new Error(data.error || '요청을 처리하지 못했습니다.'); return data; }
function error(message) { $('error').hidden = !message; $('error').textContent = message || ''; }
function option(value, label) { const o = document.createElement('option'); o.value = value; o.textContent = label; return o; }
function setOptions(select, entries, selected) { select.replaceChildren(...entries.map(([v,l]) => option(String(v),l))); if ([...select.options].some(o => o.value === String(selected))) select.value = String(selected); }
function taskLabel(t) { return `시드 ${t.seed} · ${t.required.length}곳 · ${patterns[t.pattern] || t.pattern} · ${['앞쪽','중앙','가장자리'][Number(t.id.split(':')[3])] || t.id}`; }
function getFilters() { return Object.fromEntries(['split','n','pattern','start','seed'].map(k => [k,$(k).value])); }
function filtered(ignoreSeed=false) { const f=getFilters(); return tasks.filter(t => (!f.split || t.split===f.split) && (!f.n || t.required.length===Number(f.n)) && (!f.pattern || t.pattern===f.pattern) && (!f.start || t.id.split(':')[3]===f.start) && (ignoreSeed || !f.seed || String(t.seed)===f.seed)); }
function pairedTasks(list) {
 return list.map(task=>{ const parts=task.id.split(':'); if(scenario==='F') { if(parts[2]==='paired-near') parts[2]='paired-far'; else if(parts[2]==='paired-far') parts[2]='paired-near'; else return null; } else if(scenario==='H') parts[3]=parts[3]==='0'?'1':'0'; else return null; return tasks.find(t=>t.id===parts.join(':')); }).filter(Boolean);
}
function updateSeeds() {
 const selected=$('seed').value;
 const seeds=[...new Set(filtered(true).map(t=>t.seed))].sort((a,b)=>a-b);
 setOptions($('seed'),[['','전체 시드'],...seeds.map(s=>[s,`시드 ${s}`])],selected);
 $('seed-note').textContent=seeds.length ? `현재 조건에서 ${seeds.length}개 선택 가능` : '현재 조건에 맞는 시드가 없습니다';
}
function updateTaskOptions() {
 const list=filtered(); selectedTaskId=list[0]?.id || '';
 $('task-count').textContent = list.length ? `${list.length.toLocaleString()}개 작업 일치 · 첫 번째 작업 표시: ${taskLabel(list[0])}` : '조건에 맞는 작업이 없습니다';
 $('split-note').textContent = $('split').value === 'dev' ? '개발 데이터: 규칙 생성에 사용됨' : '평가 데이터: 규칙 고정 후 사용됨';
 $('run').disabled = !list.length;
 if (!list.length) { refreshToken++; current=other=null; stop(); $('map-a').textContent=$('map-b').textContent='조건에 맞는 작업이 없습니다.'; for(const id of ['results','task-info','rule','route-info-a','route-info-b','badge-a','badge-b']) $(id).replaceChildren(); return; }
 loadDetail();
}
async function aggregate() {
 const token=++aggregateToken;
 $('aggregate-source').textContent=live?'이번 재계산 결과 · 전체 요청 시간':'저장된 실험 기록';
 const qs = new URLSearchParams({...getFilters(),seed:'',mode:$('mode').value});
 try {
   const list=filtered(true), pairs=pairedTasks(list);
   const rows=live ? summarizeLive(list, live) : await api('/api/aggregate?'+qs);
   const paired=scenario==='F'||scenario==='H';
   const otherRows=paired ? (live ? summarizeLive(pairs, live) : await api('/api/aggregate?'+new URLSearchParams({...getFilters(),seed:'',mode:$('mode').value,pair:scenario}))) : [];
   if(token!==aggregateToken)return;
   const table = rows => rows.map(r=>`<tr><td>${escapeHtml(labels[r.algorithm])}</td><td class="num">${r.attempts}</td><td class="num">${r.completed} / ${r.attempts}</td><td>${escapeHtml(Object.entries(r.statuses).filter(([s])=>s!=='completed').map(([s,n])=>`${statuses[s]||s} ${n}`).join(' · ') || '—')}</td><td class="num">${r.median_distance==null?'—':fmt(r.median_distance,1)+' m'}</td><td class="num">${time(r.median_seconds)}</td></tr>`).join('');
   $('aggregate').innerHTML=table(rows); $('aggregate-b').innerHTML=table(otherRows); $('aggregate-pair').hidden=!paired;
 } catch(e) { if(token===aggregateToken)error(e.message); }
}
function setScenario(key) {
 scenario=key; const s=scenarios[key];
 if(key==='I') $('mode').value='request';
 for(const button of $('scenarios').children) { const active=button.dataset.key===key; button.classList.toggle('active',active); button.setAttribute('aria-pressed',String(active)); }
 $('scenario-description').textContent=s[1]; $('n').value=String(s[2]); $('pattern').value=s[3]; $('start').value='0'; $('algorithm-a').value=s[4]; $('algorithm-b').value=s[5];
 live=null; updateSeeds(); updateTaskOptions(); aggregate();
}
async function loadDetail() {
 const id=selectedTaskId; if(!id)return;
 const token=++refreshToken; if(!live) { $('restore').hidden=true; $('recalc-progress').hidden=true; $('live-note').textContent=''; } stop();
 try {
   const mode=$('mode').value; const data=await api(`/api/detail?id=${encodeURIComponent(id)}&mode=${mode}`);
   let paired=null; const pairId=scenario==='F'?data.pair_f:scenario==='H'?data.pair_h:null;
   if(pairId) { try { paired=await api(`/api/detail?id=${encodeURIComponent(pairId)}&mode=${mode}`); } catch { paired=null; } }
   if(token!==refreshToken)return; current=data; other=paired; error('');
   $('comparison-note').hidden=!(scenario==='F'||scenario==='H');
   $('comparison-note').textContent=paired ? (scenario==='F'?'A는 원래 작업, B는 동일 seed·위치 수·출발점의 좌우 반사 작업입니다. 출발점과 물건 사이 거리도 달라집니다.':'A와 B는 같은 물건 집합이며 출발점이 다릅니다.') : '짝이 되는 작업이 없습니다. 해당 시나리오의 배치 또는 출발점을 선택하세요.';
   render(); aggregate();
 } catch(e) { if(token===refreshToken)error(e.message); }
}
function rowFor(detail, name) { return detail?.results.find(r=>r.algorithm===name); }
function xy(p) { return [50+Number(p[0])*10,430-Number(p[1])*10]; }
const svgNS='http://www.w3.org/2000/svg';
function el(name, attrs={}) { const e=document.createElementNS(svgNS,name); Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,v)); return e; }
function renderMap(target, detail, result, color, dashed, overlay) {
 const container=$(target); container.replaceChildren();
 if(!detail) { container.textContent='비교할 작업이 없습니다.'; return; }
 const svg=el('svg',{viewBox:'0 0 480 480','aria-hidden':'true'}); container.append(svg);
 for(const y of [0,20,40]) { const [x1,y1]=xy([0,y]), [x2,y2]=xy([36,y]); svg.append(el('line',{x1,y1,x2,y2,stroke:'#d4dfd9','stroke-width':7,'stroke-linecap':'round'})); }
 for(let x=0;x<=36;x+=4) { const [x1,y1]=xy([x,0]),[x2,y2]=xy([x,40]); svg.append(el('line',{x1,y1,x2,y2,stroke:'#d4dfd9','stroke-width':7,'stroke-linecap':'round'})); }
 for(let x=0;x<=36;x+=4) for(let y=2;y<40;y+=2) if(y!==20) { const [cx,cy]=xy([x,y]); svg.append(el('circle',{cx,cy,r:2,fill:'#b5c5bd'})); }
 let progressPath=null, marker=null;
 if(overlay?.path?.length) svg.append(el('polyline',{points:overlay.path.map(p=>xy(p).join(',')).join(' '),fill:'none',stroke:color==='#2874c1'?'#df8249':'#2874c1','stroke-width':2,'stroke-opacity':'.65','stroke-dasharray':'5 4','stroke-linecap':'round','stroke-linejoin':'round'}));
 if(result?.path?.length) {
   const points=result.path.map(p=>xy(p).join(',')).join(' ');
   svg.append(el('polyline',{points,fill:'none',stroke:color,'stroke-width':6,'stroke-opacity':'.13','stroke-linecap':'round','stroke-linejoin':'round'}));
   progressPath=el('polyline',{points,fill:'none',stroke:color,'stroke-width':3.5,'stroke-linecap':'round','stroke-linejoin':'round',...(dashed?{'stroke-dasharray':'7 4'}:{})}); svg.append(progressPath);
 }
 const order=result?.order || []; const orderMap=new Map(order.map((p,i)=>[p.join(','),i+1]));
 for(const p of detail.task.required) { const [cx,cy]=xy(p); svg.append(el('circle',{cx,cy,r:7,fill:'#fff',stroke:color,'stroke-width':2})); const text=el('text',{x:cx,y:cy+3,'text-anchor':'middle','font-size':8,'font-weight':'700',fill:color}); text.textContent=orderMap.get(p.join(',')) || '•'; svg.append(text); }
 for(const [name,p,fill] of [['S',detail.task.start,'#2b7f67'],['C',[36,0],'#354e68']]) { const [cx,cy]=xy(p); svg.append(el('circle',{cx,cy,r:12,fill,stroke:'#fff','stroke-width':2})); const text=el('text',{x:cx,y:cy+4,'text-anchor':'middle','font-size':11,'font-weight':'700',fill:'#fff'}); text.textContent=name; svg.append(text); }
 if(progressPath) { marker=el('circle',{r:6,fill:color,stroke:'#fff','stroke-width':2}); svg.append(marker); mapPaths.push({path:progressPath,marker,dashed}); }
 else { const text=el('text',{x:240,y:465,'text-anchor':'middle','font-size':12,fill:'#a26d4e'}); text.textContent=result?.path_error?'경로 검증 실패':result?.message || '표시할 경로가 없습니다'; svg.append(text); }
}
function renderSide(which, detail, result, overlay) {
 const badge=$('badge-'+which); badge.textContent = result ? (statuses[result.status]||result.status)+(result.fallback_used?' · 대체 경로':'') : '기록 없음'; badge.classList.toggle('bad',!!result && result.status!=='completed');
 const returned=result?.distance != null ? labels[result.returned_algorithm]||result.returned_algorithm||'—' : '—';
 $('route-info-'+which).innerHTML=`<div class="metric"><small>이동 거리</small><strong>${fmt(result?.distance,1)} <span>m</span></strong></div><div class="metric"><small>${live?'재계산 · 전체 요청':$('mode').value==='request'?'전체 요청':'후보 탐색'}</small><strong>${result?.seconds == null?'—':fmt(result.seconds*1000,3)} <span>ms</span></strong></div><div class="route-detail">실제로 사용된 알고리즘: ${escapeHtml(returned)}<br>${result?.optimal && result.status==='completed'?'최적해 확인':escapeHtml(terms[result?.termination]||result?.message||'최단 경로인지 확인되지 않음')}</div>`;
 renderMap('map-'+which,detail,result,which==='a'?'#2874c1':'#df8249',which==='b',overlay);
}
function drawProgress() {
 const ratio=Number($('progress').value)/1000; $('progress-label').value=`${Math.round(ratio*100)}%`;
 for(const {path,marker,dashed} of mapPaths) { const len=path.getTotalLength(); if(dashed && ratio===1) path.setAttribute('stroke-dasharray','7 4'); else path.setAttribute('stroke-dasharray',`${len*ratio} ${len}`); const p=path.getPointAtLength(len*ratio); marker.setAttribute('cx',p.x); marker.setAttribute('cy',p.y); }
}
function stop() {playing=false; if(frame)cancelAnimationFrame(frame); frame=null; $('play').textContent='▶'; $('play').setAttribute('aria-label','경로 재생');}
function tick(now) { if(!playing)return; if(lastTime) $('progress').value=Math.min(1000,Number($('progress').value)+(now-lastTime)*Number($('speed').value)/12); lastTime=now; drawProgress(); if(Number($('progress').value)>=1000)stop(); else frame=requestAnimationFrame(tick); }
function renderTable(detail, suffix='') {
 const nn=rowFor(detail,'nn'); const optimum=detail.results.filter(r=>r.status==='completed'&&!r.budget_exceeded&&r.optimal&&r.distance!=null).map(r=>r.distance); const best=optimum.length?Math.min(...optimum):null;
 $('time-heading'+suffix).textContent=live || $('mode').value==='request'?'전체 요청 시간':'후보 탐색 시간';
 $('results'+suffix).innerHTML=detail.results.map(r=>{const comparable=r.status==='completed'&&!r.budget_exceeded&&r.distance!=null; const nnValid=nn?.returned_algorithm==='nn'&&nn.path&&!nn.path_error&&nn.distance!=null&&['completed','timeout'].includes(nn.status); const nnDiff=comparable&&nnValid?r.distance-nn.distance:null; const nnReference=nnValid&&(nn.status==='timeout'||nn.budget_exceeded); const gap=comparable&&best!=null?r.distance-best:null; return `<tr><td>${escapeHtml(labels[r.algorithm])}</td><td>${escapeHtml(statuses[r.status]||r.status)}${r.termination?' · '+escapeHtml(terms[r.termination]||r.termination):''}${r.budget_exceeded?' · 예산 초과':''}</td><td>${r.distance==null?'—':escapeHtml(labels[r.returned_algorithm]||r.returned_algorithm||'—')}${r.fallback_used?' (선택한 방법 대신 사용)':''}</td><td class="num">${r.distance==null?'—':fmt(r.distance,1)+' m'}</td><td class="num">${time(r.seconds)}</td><td class="num">${nnDiff==null?'—':fmt(nnDiff,1)+' m'+(nnReference?' (참고 · NN 시간 초과)':'')}</td><td class="num">${gap==null?'—':fmt(gap,1)+' m'}</td><td>${r.optimal&&r.status==='completed'?'최적해 확인':'—'}</td></tr>`;}).join('');
 const f=detail.features; $('task-info'+suffix).textContent=`${detail.task.id} · ${f.n}개 위치 · 분산 ${fmt(f.dispersion,1)} m · 출발점 평균 ${fmt(f.start_mean,1)} m · 도착점 평균 ${fmt(f.conveyor_mean,1)} m`;
 const rule=detail.rules.count; const chosen=rule.algorithm || (f[rule.feature] <= rule.threshold?rule.left:rule.right); const description=rule.algorithm ? `항상 ${labels[rule.algorithm]}` : rule.feature === 'n' ? `물건 위치가 ${Math.floor(rule.threshold)}곳 이하면 ${labels[rule.left]}, ${Math.floor(rule.threshold)+1}곳 이상이면 ${labels[rule.right]}` : `${rule.feature} ≤ ${rule.threshold}이면 ${labels[rule.left]}, 그 외에는 ${labels[rule.right]}`; $('rule'+suffix).textContent=`개발 데이터로 만든 선택 규칙: ${description}. 이 작업에 대한 규칙의 선택: ${labels[chosen]}. 지도에는 위에서 직접 선택한 알고리즘이 표시됩니다.`;
}
function renderAlgorithmExplanation() {
 const descriptions = {
  'given':'주문에 입력된 순서 그대로 물건을 방문합니다. 경로가 가장 짧은지는 따로 확인하지 않습니다.',
  'nn':'현재 위치에서 아직 방문하지 않은 물건 중 가장 가까운 곳으로 갑니다. 이를 반복하지만 전체 경로가 가장 짧다고 보장하지는 않습니다.',
  'exhaustive':'가능한 방문 순서를 하나씩 비교해 가장 짧은 경로를 찾습니다. 물건이 많으면 계산량이 커져 제한으로 중단될 수 있습니다.',
  'dp':'이미 비교한 물건 조합의 결과를 재사용해 가장 짧은 방문 순서를 찾습니다. 물건이 많으면 계산 규모나 시간 제한으로 중단될 수 있습니다.',
  'ca-plus':'다음 물건을 고를 때 현재 위치에서의 거리에 도착점까지의 거리 × CA 계수를 더합니다. 점수가 가장 낮은 물건을 선택합니다.',
  'ca-minus':'다음 물건을 고를 때 현재 위치에서의 거리에서 도착점까지의 거리 × CA 계수를 뺍니다. 점수가 가장 낮은 물건을 선택합니다.',
  'nn+2opt':'가장 가까운 물건부터 만든 경로의 일부 방문 순서를 뒤집어 짧아지는 경우 개선합니다.',
  'ca-plus+2opt':'CA-plus로 만든 경로의 일부 방문 순서를 뒤집어 짧아지는 경우 개선합니다.',
  'ca-minus+2opt':'CA-minus로 만든 경로의 일부 방문 순서를 뒤집어 짧아지는 경우 개선합니다.',
  'nn+2opt+reinsert':'Reinsertion(재삽입)은 NN + 2-opt로 만든 경로에서 선반 하나씩 방문 순서를 바꿉니다. 예를 들어 8번째 선반을 3번째로 옮겨 봅니다. 다른 모든 삽입 지점을 비교하고, 전체 거리가 가장 짧아지는 순서를 채택합니다. 초기 순서의 각 선반을 한 번씩 검사합니다.',
  'nn+2opt+reinsert-twice':'NN + 2-opt 경로에 Reinsertion(재삽입)을 두 번 적용합니다. 선반 하나를 다른 모든 방문 순서 자리에 넣어 보고, 전체 거리가 줄어드는 경우에만 옮깁니다. 첫 번째 순회에서 바뀐 경로를 두 번째 순회에서 다시 개선합니다.',
  'nn+2opt+reinsert+segment-dp':'언제 사용하나요? 물건이 많아 모든 방문 순서를 비교하기 어렵고, 계산 시간을 조금 더 들여 이동 거리를 줄이고 싶을 때 고려할 수 있습니다. 합성 창고에서 방문 위치 15·20·50곳인 1,350개 작업을 비교한 결과, Reinsertion을 두 번 적용한 방법보다 평균 이동 거리가 0.406m 짧았습니다. 대신 전체 계산 시간의 중앙값은 2.92ms에서 3.44ms로 늘었습니다. 이 데모에서는 사용자가 직접 선택합니다.\n어떻게 작동하나요? 먼저 NN으로 가까운 물건부터 방문하는 경로를 만들고, 2-opt로 순서를 다듬습니다. 이어서 Reinsertion으로 물건을 하나씩 다른 순서에 넣어 보며 더 짧은 경로를 찾습니다. 마지막으로 Segment DP가 연속된 최대 6곳을 묶어, 묶음 앞뒤는 그대로 두고 그 안에서 가장 짧은 방문 순서를 찾습니다. 묶음을 3곳씩 옮겨 가며 마지막 부분까지 살펴봅니다. 계산이 완료된 변경은 전체 거리가 줄어들 때만 적용합니다.\n왜 이렇게 만들었나요? 물건이 많아지면 전체 경로를 정확한 DP로 계산하는 부담이 커집니다. 기존 실험에서는 20곳과 50곳 작업이 당시 설정한 DP 크기 제한에 걸렸습니다. 이는 DP 자체의 절대적인 한계가 아니라 실험 설정에 따른 결과입니다. NN + 2-opt는 빠르게 경로를 만들지만 더 짧은 순서가 남아 있을 수 있습니다. 그래서 먼저 Reinsertion으로 물건을 하나씩 옮겨 보고, 이어서 Segment DP로 작은 묶음의 순서를 함께 바꿉니다. 하나씩 옮길 때 놓칠 수 있는 개선을 찾으면서 전체 순서를 정확히 계산하는 부담은 줄이려는 방식입니다.\n결과를 어떻게 해석하나요? 위 결과는 하나의 합성 창고와 실행 환경에서 얻었습니다. 전체 최단 경로를 찾거나 다른 창고에서도 같은 효과가 나타난다는 보장은 없습니다.'
 };
 const selected = [...new Set(['algorithm-a','algorithm-b'].map(id=>$(id).value))].filter(name=>descriptions[name]);
 $('algorithm-explanation').hidden = selected.length === 0;
 const paragraphs = name => descriptions[name].split('\n').map(part=>`<p>${escapeHtml(part)}</p>`).join('');
 $('algorithm-explanation-content').innerHTML = selected.map(name=>`<h3>${escapeHtml(labels[name])}</h3>${paragraphs(name)}`).join('');
 if (!$('all-algorithm-explanations').children.length) $('all-algorithm-explanations').innerHTML = algorithms.map(name=>`<details><summary>${escapeHtml(labels[name])}</summary>${paragraphs(name)}</details>`).join('');
}
function render() {
 renderAlgorithmExplanation();
 for(const which of ['a','b']) { const name=$('algorithm-'+which).value; $('algorithm-name-'+which).textContent=`선택한 알고리즘: ${labels[name]} (${name})`; }
 if(!current)return; mapPaths=[];
 const pairedScenario=scenario==='F'||scenario==='H';
 const rightDetail=pairedScenario ? other : current;
 const a=live ? live[current.task.id]?.find(r=>r.algorithm===$('algorithm-a').value) : rowFor(current,$('algorithm-a').value); const b=live ? live[rightDetail?.task.id]?.find(r=>r.algorithm===$('algorithm-b').value) : rowFor(rightDetail,$('algorithm-b').value);
 const canOverlay=!!rightDetail && rightDetail.task.id===current.task.id;
 $('overlay').disabled=!canOverlay; if(!canOverlay)$('overlay').checked=false;
 $('run').disabled=pairedScenario && !other;
 renderSide('a',current,a,$('overlay').checked?b:null); renderSide('b',rightDetail,b,$('overlay').checked?a:null); $('progress').value=1000; drawProgress(); renderTable(live ? {...current, results:live[current.task.id]} : current);
 $('detail-pair').hidden=!pairedScenario||!other; if(pairedScenario&&other) renderTable(live ? {...other, results:live[other.task.id]} : other, '-b');
 $('source-tag').textContent=live?'이번 재계산 결과':'저장된 실험 기록';
}
function summarizeLive(list, results) {
 const median = values => { values.sort((a,b)=>a-b); const i=Math.floor(values.length/2); return values.length ? (values.length%2 ? values[i] : (values[i-1]+values[i])/2) : null; };
 return algorithms.map(algorithm=>{
   const rows=list.map(task=>results[task.id].find(row=>row.algorithm===algorithm));
   const valid=rows.filter(row=>row.status==='completed'&&!row.budget_exceeded&&row.distance!=null);
   const counts={}; for(const row of rows) counts[row.status]=(counts[row.status]||0)+1;
   return {algorithm, attempts:rows.length, completed:valid.length, statuses:counts,
     median_distance:median(valid.map(row=>row.distance)), median_seconds:median(valid.map(row=>row.seconds).filter(value=>value!=null))};
 });
}
async function runLive() {
 if(!current)return;
 const budget=Number($('budget').value), coefficient=Number($('coefficient').value);
 if(!Number.isFinite(budget)||budget<.01||budget>2||!Number.isFinite(coefficient)||coefficient<0||coefficient>2) { error('시간은 0.01~2초, CA 계수는 0~2로 입력하세요.'); return; }
 const list=filtered(true), all=[...new Map([...list,...pairedTasks(list)].map(task=>[task.id,task])).values()];
 const total=all.length*algorithms.length, results={}; let done=0;
 const controls=[...document.querySelectorAll('#scenarios button, .filter-grid select, #mode, #algorithm-a, #algorithm-b, #budget, #coefficient, #run, #restore')];
 cancelRecalculation=false; controls.forEach(control=>control.disabled=true); $('cancel-recalc').hidden=false; $('recalc-progress').hidden=false; $('recalc-progress').max=total; $('recalc-progress').value=0; error('');
 try {
   for(const task of all) {
     results[task.id]=[];
     for(const algorithm of algorithms) {
       if(cancelRecalculation) throw new Error('계산이 취소되었습니다.');
       const data=await api('/api/recalculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:task.id,algorithms:[algorithm],budget,coefficient})});
       if(cancelRecalculation) throw new Error('계산이 취소되었습니다.');
       results[task.id].push(data.results[0]);
       $('recalc-progress').value=++done; $('live-note').textContent=`재계산 중: ${done.toLocaleString()} / ${total.toLocaleString()}건 (${Math.floor(done/total*100)}%)`;
     }
   }
   live=results; $('mode').value='request'; await loadDetail(); $('restore').hidden=false; $('live-note').textContent=`재계산 완료: ${done.toLocaleString()}건 · 전체 요청 시간 · 제한 ${budget}초 / CA 계수 ${coefficient}. 저장 기록은 변경되지 않았습니다.`; stop(); render(); aggregate();
 } catch(e) { if(!cancelRecalculation) error(e.message); $('live-note').textContent=cancelRecalculation?'재계산을 취소했습니다. 이전 결과를 유지합니다.':'재계산에 실패했습니다. 이전 결과를 유지합니다.'; }
 finally { $('cancel-recalc').hidden=true; controls.forEach(control=>control.disabled=false); $('run').disabled=(scenario==='F'||scenario==='H')&&!other; }
}
async function init() {
 try {
   if (typeof staticApi !== 'undefined') { $('live-section').hidden=true; $('static-notice').hidden=false; }
   for(const [key,s] of Object.entries(scenarios)) { const b=document.createElement('button'); b.className='scenario'; b.dataset.key=key; b.innerHTML=`<b>${key}</b><span>${s[0]}</span>`; b.addEventListener('click',()=>setScenario(key)); $('scenarios').append(b); }
   for(const id of ['algorithm-a','algorithm-b']) { setOptions($(id),algorithms.map(a=>[a,labels[a]]),'nn'); $(id).addEventListener('change',()=>{render();}); }
   tasks=await api('/api/tasks');
   setOptions($('n'),[[ '', '전체'],...[...new Set(tasks.map(t=>t.required.length))].sort((a,b)=>a-b).map(n=>[n,`${n}개`])],'3');
   setOptions($('pattern'),[['','전체'],...Object.entries(patterns)],'clustered');
   setOptions($('start'),[['','전체'],['0','앞쪽'],['1','중앙'],['2','가장자리']],'0');
   for(const id of ['split','n','pattern','start','seed']) $(id).addEventListener('change',()=>{if(id!=='seed') {live=null;updateSeeds();} updateTaskOptions();aggregate();});
   $('mode').addEventListener('change',()=>{live=null;loadDetail();});
   $('run').addEventListener('click',runLive); $('cancel-recalc').addEventListener('click',()=>{cancelRecalculation=true;$('live-note').textContent='현재 계산이 끝나면 취소합니다…';}); $('restore').addEventListener('click',()=>{live=null;$('restore').hidden=true;$('recalc-progress').hidden=true;$('live-note').textContent='';loadDetail();});
   $('play').addEventListener('click',()=>{if(playing){stop();return;} if(Number($('progress').value)>=1000)$('progress').value=0; playing=true;lastTime=0;$('play').textContent='Ⅱ';$('play').setAttribute('aria-label','경로 일시정지');frame=requestAnimationFrame(tick);});
   $('overlay').addEventListener('change',render);
   $('reset').addEventListener('click',()=>{stop();$('progress').value=0;drawProgress();}); $('progress').addEventListener('input',()=>{stop();drawProgress();});
   setScenario('A');
 } catch(e) {error(`데이터를 불러오지 못했습니다: ${e.message}`);}
}
init();
