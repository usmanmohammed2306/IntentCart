/* The optional file workspace. It never changes a plan, permission or quote. */
export function initLibrary(getCsrf){
 const $=id=>document.getElementById(id),el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
 let selected=null,busy=false,context=null,modelAvailable=false,operation=null;
 const message=t=>{$('library-message').textContent=t;};
 const clear=()=>{context=null;operation=null;$('library-results').replaceChildren();$('library-answer').replaceChildren();$('library-ai').hidden=true;$('library-consent').checked=false;$('library-ask').disabled=true;};
 async function request(path,body,method='POST'){
  const options=body===undefined?{}:{method,headers:{'X-CSRF-Token':getCsrf()},body:body instanceof FormData?body:JSON.stringify(body)};
  if(body!==undefined&&!(body instanceof FormData))options.headers['Content-Type']='application/json';
  const response=await fetch(path,options);let data;try{data=await response.json();}catch{throw Error('The connection was interrupted. Check the saved status before trying again.');}
  if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Please check the selected file and question.');return data;
 }
 function lock(value){busy=value;for(const n of $('library-dialog').querySelectorAll('button,input'))if(n.id!=='library-close')n.disabled=value;$('library-ask').disabled=value||!context||!modelAvailable||!$('library-consent').checked;}
 async function action(fn){if(busy)return;lock(true);try{await fn();}catch(e){message(e.message);}finally{lock(false);}}
 async function list(){
  const result=await request('/api/documents');modelAvailable=result.model_budget.enabled;
  $('library-items').replaceChildren(...result.documents.map(d=>{const card=el('article'),choose=el('button'),name=el('strong',d.name),meta=el('small',`${d.pages} page${d.pages===1?'':'s'} · from your file`),remove=el('button','Remove');choose.type=remove.type='button';choose.append(name,meta);choose.className='library-select';choose.setAttribute('aria-pressed',String(selected?.id===d.id));choose.addEventListener('click',()=>{selected=d;clear();$('library-search').hidden=false;for(const n of $('library-items').querySelectorAll('.library-select'))n.setAttribute('aria-pressed',String(n===choose));$('library-question').focus();});remove.className='library-remove';remove.setAttribute('aria-label','Remove '+d.name);remove.addEventListener('click',()=>action(async()=>{await request('/api/documents/'+d.id,{},'DELETE');if(selected?.id===d.id){selected=null;clear();$('library-search').hidden=true;}await list();message('File removed. Your plan has not changed.');}));card.append(choose,remove);return card;}));
 }
 $('library-open').addEventListener('click',()=>{$('advanced-dialog').close();$('library-dialog').showModal();action(list);});
 $('library-close').addEventListener('click',()=>{$('library-dialog').close();});
 $('library-dialog').addEventListener('close',()=>{$('advanced-open').focus();});
 $('library-upload').addEventListener('submit',e=>{e.preventDefault();action(async()=>{const file=$('library-file').files[0];if(!file||file.size>1500000)throw Error('Choose a file up to 1.5 MB.');const data=new FormData();data.append('file',file);message('Reading your file…');selected=await request('/api/documents/import',data);clear();await list();$('library-search').hidden=false;message('Ready. Find a passage in your file.');$('library-question').focus();});});
 $('library-question').addEventListener('input',()=>{clear();});
 $('library-search').addEventListener('submit',e=>{e.preventDefault();action(async()=>{clear();if(!selected)throw Error('Choose a file first.');const query=$('library-question').value.trim();const result=await request('/api/documents/'+selected.id+'/search',{query,revision:selected.revision});context={query,signature:result.context_sha256};$('library-results').replaceChildren(...result.hits.map(h=>{const card=el('article');card.append(el('small','Page '+h.page),el('p',h.text));return card;}));$('library-ai').hidden=!modelAvailable;message('Passages from your file. Relevance is not factual confidence.');});});
 $('library-consent').addEventListener('change',()=>{$('library-ask').disabled=busy||!context||!modelAvailable||!$('library-consent').checked;});
 function answer(data){const area=$('library-answer');area.replaceChildren();if(data.status!=='answered'){area.append(el('p',data.notice||'Answer status is pending.No retry was sent.'));return;}area.append(el('h3',data.quotes.length?'What your file says':'No supported passage selected'));
  for(const quote of data.quotes){const item=el('blockquote',quote.text);item.append(el('cite','Page '+quote.page));area.append(item);}area.append(el('small',data.notice));}
 $('library-ask').addEventListener('click',()=>action(async()=>{if(!selected||!context||!$('library-consent').checked)throw Error('Review the passages and sharing choice first.');operation=crypto.randomUUID().replaceAll('-','');const path='/api/documents/'+selected.id;message('Checking the passages…');try{answer(await request(path+'/ask',{query:context.query,revision:selected.revision,operation_id:operation,context_sha256:context.signature,share_with_astropods:true}));message('Finished. Your plan has not changed.');}catch(e){try{answer(await request(path+'/answers/'+operation));message('Saved status recovered.No model retry was sent.');}catch{throw e;}}finally{$('library-consent').checked=false;}}));
}
