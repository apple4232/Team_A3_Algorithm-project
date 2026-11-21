const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const elements = Object.fromEntries(['split', 'n', 'pattern', 'start', 'seed', 'seed-note', 'task-count', 'split-note', 'run', 'mode', 'time-heading', 'results', 'task-info', 'rule', 'aggregate', 'aggregate-b', 'aggregate-pair', 'aggregate-source', 'algorithm-a', 'algorithm-b', 'algorithm-explanation', 'algorithm-explanation-content', 'all-algorithm-explanations'].map(id => [id, {
  value: '', options: [], textContent: '', children: [],
  replaceChildren(...options) { this.options = options; this.value = options[0]?.value || ''; }
}]));
const document = {getElementById: id => elements[id], createElement: () => ({})};
const source = fs.readFileSync('demo/app.js', 'utf8').replace(/init\(\);\s*$/, '');
vm.runInNewContext(source + `
tasks = [
 {id:'100:3:clustered:0', seed:100, split:'dev', pattern:'clustered', required:[1,2,3]},
 {id:'101:3:clustered:0', seed:101, split:'eval', pattern:'clustered', required:[1,2,3]},
 {id:'103:3:directional:0', seed:103, split:'eval', pattern:'directional', required:[1,2,3]}
];
$('split').value='eval'; $('n').value='3'; $('pattern').value='clustered'; $('start').value='0';
updateSeeds();
assert.deepEqual(Array.from($('seed').options, o=>o.value), ['', '101']);
$('seed').value='101'; updateSeeds(); assert.equal($('seed').value, '101');
$('pattern').value='directional'; updateSeeds();
assert.deepEqual(Array.from($('seed').options, o=>o.value), ['', '103']);
assert.equal($('seed').value, ''); assert.equal(filtered().length, 1);
loadDetail = () => {};
updateTaskOptions(); assert.equal(selectedTaskId, '103:3:directional:0');
assert.match($('task-count').textContent, /첫 번째 작업 표시/);
$('n').value='50'; updateSeeds(); assert.equal(filtered().length, 0);
assert.match($('seed-note').textContent, /없습니다/);
const detail = {task:{id:'sample'}, features:{n:13,dispersion:1,start_mean:1,conveyor_mean:1}, results:[], rules:{count:{feature:'n',threshold:13.5,left:'dp',right:'nn+2opt'}}};
renderTable(detail);
assert.ok($('rule').textContent.includes('13곳 이하면 DP, 14곳 이상이면 NN + 2-opt'));
assert.match($('rule').textContent, /규칙의 선택: DP/);
detail.features.n=14; renderTable(detail);
assert.ok($('rule').textContent.includes('규칙의 선택: NN + 2-opt'));
detail.results=[{algorithm:'nn',status:'timeout',budget_exceeded:true,distance:100,returned_algorithm:'nn',path:[[0,0]]},{algorithm:'dp',status:'completed',distance:90}];
renderTable(detail); assert.ok($('results').innerHTML.includes('-10.0 m (참고 · NN 시간 초과)'));
detail.results[0].path=null; renderTable(detail); assert.doesNotMatch($('results').innerHTML, /참고 · NN 시간 초과/);
const liveRows = (distance, status='completed') => algorithms.map(algorithm=>({algorithm, status, distance, seconds:distance/100, budget_exceeded:false}));
const aggregateRows = summarizeLive([{id:'a'},{id:'b'},{id:'c'}], {a:liveRows(10),b:liveRows(30),c:liveRows(100,'timeout')});
assert.equal(aggregateRows[0].attempts, 3);
assert.equal(aggregateRows[0].completed, 2);
assert.equal(aggregateRows[0].median_distance, 20);
assert.equal(aggregateRows[0].statuses.timeout, 1);
$('algorithm-a').value='nn'; $('algorithm-b').value='dp'; renderAlgorithmExplanation();
assert.equal(($('all-algorithm-explanations').innerHTML.match(/<summary>/g) || []).length, algorithms.length);
assert.ok($('all-algorithm-explanations').innerHTML.includes('Segment DP'));
tasks.push({id:'101:3:paired-far:0'}, {id:'101:3:paired-near:0'}, {id:'101:3:paired-far:1'});
scenario='F'; assert.equal(pairedTasks([tasks[3]])[0].id, '101:3:paired-near:0');
scenario='H'; assert.equal(pairedTasks([tasks[3]])[0].id, '101:3:paired-far:1');
`, {document, assert});

let requestedUrl;
vm.runInNewContext(source + `
  $('split').value='eval'; $('n').value='10'; $('pattern').value='paired-far'; $('start').value='0'; $('seed').value='111';
  api = async url => { capture(url); return []; };
  aggregate();
`, {document, assert, URLSearchParams, capture: url => { requestedUrl = url; }});
const query = new URLSearchParams(requestedUrl.split('?')[1]);
assert.equal(query.get('seed'), '');
assert.equal(query.get('n'), '10');
