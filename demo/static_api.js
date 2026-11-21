'use strict';
const staticShards = new Map();
async function staticReadJSON(path) {
 const response = await fetch(path);
 if (!response.ok) throw new Error('저장된 실험 데이터를 불러오지 못했습니다.');
 return response.json();
}
async function staticShard(task, mode) {
 const key=`${task.split}-${mode}-${task.seed}`;
 if (!staticShards.has(key)) staticShards.set(key, staticReadJSON(`/data/${key}.json`));
 return staticShards.get(key);
}
async function staticSummary(split, mode) {
 const key=`${split}-${mode}-summary`;
 if (!staticShards.has(key)) staticShards.set(key, staticReadJSON(`/data/${key}.json`));
 return staticShards.get(key);
}
async function staticApi(url) {
 const parsed = new URL(url, location.href), params = parsed.searchParams;
 if (parsed.pathname==='/api/tasks') return staticReadJSON('/data/tasks.json');
 const mode=params.get('mode') || 'request';
 if (parsed.pathname==='/api/detail') {
   const task=tasks.find(t=>t.id===params.get('id'));
   if (!task) throw new Error('작업을 찾을 수 없습니다.');
   return (await staticShard(task, mode))[task.id];
 }
 if (parsed.pathname==='/api/aggregate') {
   let list=tasks.filter(task=>['split','pattern','seed','n','start'].every(key=>{
     const value=params.get(key); if(!value)return true;
     return String(key==='n'?task.required.length:key==='start'?task.id.split(':')[3]:task[key])===value;
   }));
   if(params.get('pair')) list=pairedTasks(list);
   const summaries=await Promise.all([...new Set(list.map(task=>task.split))].map(split=>staticSummary(split,mode)));
   const results={};
   for(const task of list) {
     const rows=summaries.find(summary=>summary[task.id])?.[task.id];
     if(!rows) throw new Error('작업의 저장 결과가 없습니다.');
     results[task.id]=rows;
   }
   return summarizeLive(list,results);
 }
 throw new Error('지원하지 않는 요청입니다.');
}
