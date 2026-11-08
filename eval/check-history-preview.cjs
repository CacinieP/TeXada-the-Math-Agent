const fs = require('fs'), path = require('path'), http = require('http'), assert = require('assert/strict');
const {execFileSync} = require('child_process');
// Optional browser audit: see docs/issue70-history-preview.md.
const {chromium} = require(process.env.TEXADA_PLAYWRIGHT_MODULE || 'playwright-core');
const root=path.resolve(__dirname, '..'), src=path.join(root,'tauri-shell/src');
const python=process.env.TEXADA_PYTHON || path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const fixtures=JSON.parse(execFileSync(python,['-c',`from texada.core.matrices import MatrixSpec, generate_matrix
import json
cases = []
for kind in ('general', 'tridiagonal', 'identity', 'zero', 'diagonal', 'upper_triangular', 'lower_triangular'):
    for n in (1, 2, 3, 10, 20):
        for display in ('expanded', 'compact'):
            spec = MatrixSpec(kind=kind, rows=n, columns=n, display=display)
            cases.append(dict(id=f'{kind}-{n}-{display}', spec=spec.model_dump(), latex=generate_matrix(spec)))
    for bracket in ('pmatrix', 'bmatrix', 'matrix', 'vmatrix'):
        for start in (0, 1):
            spec = MatrixSpec(kind=kind, rows='n', columns='n', bracket=bracket, index_start=start)
            cases.append(dict(id=f'{kind}-n-{bracket}-{start}', spec=spec.model_dump(), latex=generate_matrix(spec)))
for rows, columns in ((2, 3), (3, 2), ('m', 'n')):
    for kind in ('general', 'zero'):
        spec = MatrixSpec(kind=kind, rows=rows, columns=columns, bracket='bmatrix')
        cases.append(dict(id=f'{kind}-rect-{rows}-{columns}', spec=spec.model_dump(), latex=generate_matrix(spec)))
print(json.dumps(cases))`],{cwd:root,env:{...process.env,PYTHONPATH:path.join(root,'src')}}));
const katex=require(path.join(src,'vendor/katex/katex.min.js'));
const before={}; for(const f of ['main.js','index.html','style.css'])before[f]=execFileSync('git',['show',`${process.env.TEXADA_UI_BASELINE || '0cccb7fa5a3b9efe385803b995cc61a0387bfe6f'}:tauri-shell/src/${f}`],{cwd:root});
const mime={'.html':'text/html','.js':'application/javascript','.css':'text/css','.woff2':'font/woff2','.woff':'font/woff','.ttf':'font/ttf','.svg':'image/svg+xml'};
const server=http.createServer((req,res)=>{
 const url=new URL(req.url,'http://localhost');const parts=url.pathname.split('/').filter(Boolean); const mode=parts.shift();
 let rel=parts.join('/')||'index.html';let filename=path.resolve(src,rel);
 if(!filename.startsWith(src+path.sep)){res.writeHead(403);res.end();return;}
 try{const data=mode==='before'&&before[rel]?before[rel]:fs.readFileSync(filename);res.writeHead(200,{'Content-Type':mime[path.extname(filename)]||'application/octet-stream','Cache-Control':'no-store'});res.end(data);}catch{res.writeHead(404);res.end();}
});
const output=process.env.TEXADA_UI_AUDIT_OUTPUT || path.join(require('os').tmpdir(),'texada-history-browser-audit');fs.mkdirSync(output,{recursive:true});
const records=[];
const historyItem=(f,type='matrix')=>({id:1,input_type:type,input_text:'矩阵预设 '+JSON.stringify(f.spec),latex:f.latex,valid:true,render_mode:'latex',created_at:'2026-11-08T00:00:00Z'});
const normal=fixtures.find(x=>x.id==='tridiagonal-2-expanded');let histories=[historyItem(normal)];
const requests=[], errors=[];
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const address=`http://127.0.0.1:${server.address().port}`;
 const browser=await chromium.launch({executablePath:process.env.TEXADA_BROWSER_EXECUTABLE || undefined,headless:true});
 try{
  const context=await browser.newContext({viewport:{width:620,height:760}});
  await context.addInitScript(()=>{window._auditCopies=[];Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>window._auditCopies.push(text)}});});
  const page=await context.newPage();page.on('pageerror',e=>errors.push(String(e)));
  await page.route('**/api/**',async route=>{
   const req=route.request(),u=new URL(req.url()),p=u.pathname;requests.push({path:p,method:req.method()});let data={};
   if(p==='/api/runtime')data={max_ocr_bytes:5242880,allowed_image_mime_types:['image/png'],api_request_timeout_seconds:240};
   else if(p==='/api/settings/ui')data={ui_language:'zh',ui_zoom:1};
   else if(p==='/api/status')data={ready:true,status:'ready',backend:'llama_server',model:'MiniCPM-V-4.7-1B',vision:'MiniCPM-V-4.7-1B'};
   else if(p==='/api/history')data=histories;
   else if(p==='/api/shorthands')data=[{key:'matrix-audit',value:normal.latex},{key:'wrapped-matrix',value:'$$'+normal.latex+'$$'},{key:'cases-audit',value:String.raw`f(x)=\begin{cases}x&x>0\\0&x\leq0\end{cases}`}];
   else if(p==='/api/matrix'){
    const spec=req.postDataJSON().spec;
    const f=fixtures.find(x=>x.spec.kind===spec.kind&&x.spec.rows===spec.rows&&x.spec.columns===spec.columns&&x.spec.bracket===spec.bracket&&x.spec.display===(typeof spec.rows==='string'?'compact':spec.display)&&x.spec.index_start===spec.index_start);
    if(!f){await route.fulfill({status:422,contentType:'application/json',body:JSON.stringify({detail:'No audit fixture for '+JSON.stringify(spec)})});return;}
    data={run_id:'audit-matrix-'+f.id,latex:f.latex,katex_html:katex.renderToString(f.latex,{displayMode:true}),copy_text:'$$'+f.latex+'$$',valid:true,committed:true,source:'agent',intent:'matrix',revision:1,tokens_used:0,stop_reason:'deterministic_candidate',agent_trace:[{step:1,matrix_constraints:[{verdict:'MATCH',revision:1}]}]};
   }
   await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  const tab=async name=>{await page.locator('#tab-button-'+name).click();};
  const loaded=async()=>{await page.waitForFunction(()=>document.querySelector('#history-list').getAttribute('aria-busy')==='false');};
  await page.goto(address+'/before/');await tab('history');await loaded();
  await page.locator('[data-history-view-result="0"]').click();
  const baseline=await page.evaluate(()=>({activeTab:document.querySelector('.tab-content.active')?.id,mathNodes:document.querySelectorAll('#matrix-result [data-matrix-preview] .katex').length,sourceText:document.querySelector('#matrix-result [data-matrix-preview]')?.textContent,renderState:document.querySelector('#matrix-result [data-matrix-preview]')?.dataset.renderState}));
  assert.equal(baseline.activeTab,'tab-shorthand');assert.equal(baseline.mathNodes,0);
  records.push({name:'baseline reproduction',pass:true,details:baseline});await page.screenshot({path:path.join(output,'before-history.png')});
  console.log('BASELINE',JSON.stringify(baseline));
  await page.goto(address+'/after/');await page.locator('#nl-input').fill('保留自然语言草稿');
  await tab('shorthand');await page.locator('#matrix-form').evaluate(e=>e.closest('details').open=true);
  await page.selectOption('#matrix-kind','tridiagonal');await page.fill('#matrix-rows','2');await page.locator('#btn-generate-matrix').click();
  await page.waitForFunction(()=>document.querySelector('#matrix-result')?._texadaResult?.committed===true);
  assert.equal(await page.locator('[data-matrix-preview] .katex').count(),1);
  const cards=await page.locator('[data-shorthand-render]').evaluateAll(xs=>xs.map(x=>({state:x.dataset.renderState,count:x.querySelectorAll('.katex').length})));
  assert.ok(cards.length===3&&cards.every(x=>x.state==='rendered'&&x.count===1));records.push({name:'preset cards and generation render without fallback',pass:true,cards});
  await page.fill('#matrix-rows','7');
  const draft=await page.evaluate(()=>({fields:[...document.querySelector('#matrix-form').elements].filter(x=>x.name).map(x=>[x.name,x.value]),nl:document.querySelector('#nl-input').value,result:document.querySelector('#matrix-result')._texadaResult,status:document.querySelector('#matrix-status').textContent}));
  await tab('history');await loaded();const postCount=()=>requests.filter(x=>x.method==='POST').length;const beforeView=postCount();
  await page.locator('[data-history-view-result="0"]').click();
  assert.equal(await page.locator('.tab-content.active').getAttribute('id'),'tab-history');
  assert.equal(await page.locator('[data-history-preview-math] .katex').count(),1);
  const afterDraft=await page.evaluate(()=>({fields:[...document.querySelector('#matrix-form').elements].filter(x=>x.name).map(x=>[x.name,x.value]),nl:document.querySelector('#nl-input').value,result:document.querySelector('#matrix-result')._texadaResult,status:document.querySelector('#matrix-status').textContent}));
  assert.deepEqual(afterDraft,draft);assert.equal(postCount(),beforeView);records.push({name:'view remains in history and preserves live drafts with zero POST',pass:true});
  await page.locator('[data-history-preview-copy-latex]').click();await page.locator('[data-history-preview-copy-markdown]').click();
  assert.deepEqual(await page.evaluate(()=>window._auditCopies),[normal.latex,'$$'+normal.latex+'$$']);assert.equal(postCount(),beforeView);records.push({name:'exact copies do not regenerate or switch tab',pass:true});
  await page.locator('[data-history-preview-close]').click();assert.equal(await page.locator('#history-preview').isVisible(),false);
  assert.equal(await page.evaluate(()=>document.activeElement?.dataset.historyViewResult),'0');
  records.push({name:'close returns focus to view control',pass:true});
  const geometry=[];
  for(let i=0;i<fixtures.length;i++){
   const f=fixtures[i];histories=[historyItem(f)];await page.locator('#btn-refresh-history').click();await loaded();await page.locator('[data-history-view-result="0"]').click();
   await page.evaluate(()=>document.fonts.ready);
   const r=await page.locator('[data-history-preview-math]').evaluate(e=>{
    const k=e.querySelector('.katex-display')||e.querySelector('.katex'),p=e.getBoundingClientRect();let a=k?.getBoundingClientRect();
    const initial={state:e.dataset.renderState,math:!!k,error:!!e.querySelector('.katex-error'),scrollWidth:e.scrollWidth,clientWidth:e.clientWidth,leftGap:a?a.left-p.left:null};
    e.scrollLeft=e.scrollWidth;a=k?.getBoundingClientRect();initial.rightGap=a?p.right-a.right:null;e.scrollLeft=0;return initial;
   });
   assert.equal(r.state,'rendered',f.id);assert.equal(r.math,true,f.id);assert.equal(r.error,false,f.id);assert.ok(r.leftGap>=-1,f.id+' left clipped '+r.leftGap);assert.ok(r.rightGap>=-1,f.id+' right unreachable '+r.rightGap);
   assert.equal(await page.locator('[data-history-preview-source]').textContent(),f.latex,f.id);geometry.push({id:f.id,...r});
   if(f.id==='general-20-expanded')await page.screenshot({path:path.join(output,'after-large-matrix.png')});
   if((i+1)%25===0)console.log('HISTORY_SWEEP',i+1,'/',fixtures.length);
  }
  records.push({name:'all matrix history render and left/right scroll bounds',pass:true,count:geometry.length});
  fs.writeFileSync(path.join(output,'matrix-geometry.json'),JSON.stringify(geometry,null,2));
  assert.equal(postCount(),beforeView);
  // Malformed saved TeX is visible and safely inspectable, without hidden navigation.
  histories=[{...historyItem(normal),input_text:'<img src=x onerror=alert(1)>',latex:String.raw`\frac{x}{`,valid:false}];
  await page.locator('#btn-refresh-history').click();await loaded();await page.locator('[data-history-view-result="0"]').click();
  assert.equal(await page.locator('[data-history-preview-error]').isVisible(),true);assert.equal(await page.locator('#history-preview img').count(),0);assert.equal(await page.locator('[data-history-preview-source]').textContent(),String.raw`\frac{x}{`);
  records.push({name:'invalid history is safe source with explicit warning',pass:true});
  // An old nl matrix still renders even if its parameters cannot be recovered.
  histories=[{...historyItem(normal,'nl'),input_text:'矩阵预设 {broken',latex:'$$'+normal.latex+'$$'}];
  await page.locator('#btn-refresh-history').click();await loaded();await page.locator('[data-history-view-result="0"]').click();
  assert.equal(await page.locator('[data-history-preview-math] .katex').count(),1);assert.equal(await page.locator('.tab-content.active').getAttribute('id'),'tab-history');
  records.push({name:'legacy history can be viewed without parsing matrix parameters',pass:true});
  // Reuse, unlike View, deliberately switches to Presets and invalidates old results.
  histories=[historyItem(normal)];await page.locator('#btn-refresh-history').click();await loaded();await page.locator('[data-history-view-result="0"]').click();
  await page.locator('[data-history-preview-reuse]').click();assert.equal(await page.locator('.tab-content.active').getAttribute('id'),'tab-shorthand');assert.equal(await page.inputValue('#matrix-rows'),'2');assert.equal(postCount(),beforeView);
  assert.equal(await page.locator('[data-insert-result]').isDisabled(),true);
  await page.locator('#btn-generate-matrix').click();await page.waitForFunction(()=>document.querySelector('#matrix-result')?._texadaResult?.committed===true);
  assert.equal(await page.locator('[data-insert-result]').isDisabled(),false);assert.equal(await page.locator('[data-matrix-preview] .katex').count(),1);assert.equal(postCount(),beforeView+1);
  records.push({name:'only explicit reuse switches tabs; only Generate calls matrix API',pass:true});
  assert.deepEqual(errors,[]);console.log('DONE',JSON.stringify({checks:records.length,matrices:geometry.length,pageErrors:errors.length}));
 }catch(e){records.push({name:'ERROR',pass:false,error:String(e),stack:e.stack});console.error(e);process.exitCode=1;}
 finally{fs.writeFileSync(path.join(output,'report.json'),JSON.stringify({records,requests,errors,scope:'Real Chromium DOM with actual frontend and KaTeX, mocked local APIs; no installed-app replacement or model inference'},null,2));await browser.close();await new Promise(r=>server.close(r));}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
