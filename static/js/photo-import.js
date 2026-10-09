(() => {
'use strict';
const root=document.getElementById('photo-import'); if(!root)return;
const $=id=>document.getElementById(id), base=root.dataset.base;
let batch=null,items=[],current=null,busy=false,stop=false,worker=null;
const csrf=root.querySelector('[name=csrfmiddlewaretoken]').value;
const notice=t=>{$('notice').textContent=t;};
const textError=e=>typeof e==='string'?e:JSON.stringify(e);
async function api(path,data){
 const opts={credentials:'same-origin',headers:{'X-CSRFToken':csrf}};
 if(data!==undefined){opts.method='POST';if(data instanceof FormData)opts.body=data;else{opts.headers['Content-Type']='application/json';opts.body=JSON.stringify(data);}}
 const res=await fetch(base+path,opts);let result;
 try{result=await res.json();}catch{throw Error('The server could not respond. Check your login and retry.');}
 if(!res.ok)throw Error(textError(result.error||`Request failed (${res.status})`));return result;
}
const path=id=>`batches/${batch.id}/items/${id}/`;
function replace(item){const i=items.findIndex(x=>x.id===item.id);if(i<0)items.push(item);else items[i]=item;if(current?.id===item.id)current=item;drawList();}
function drawList(){
 $('item-list').replaceChildren();items.sort((a,b)=>a.source_key.localeCompare(b.source_key));
 $('counts').textContent=`${items.length} products · ${items.filter(i=>i.product_id).length} imported`;
 for(const item of items){if(!((item.details.name||'')+' '+item.source_key).toLowerCase().includes($('filter-list').value.toLowerCase()))continue;const b=document.createElement('button');b.className='import-item';b.type='button';b.setAttribute('aria-current',String(item.id===current?.id));
 if(item.photos[0]){const img=document.createElement('img');img.src=item.photos[0].url;img.alt='';img.loading='lazy';b.append(img);}
 const s=document.createElement('span');s.textContent=item.details.name||item.source_key;const sub=document.createElement('small');sub.textContent=item.source_key+' · '+(item.product_id?'Imported':item.details.identity_verified?'Reviewed':'Needs review');s.append(sub);b.append(s);b.onclick=()=>guard(async()=>{await saveCurrent();select(item);});$('item-list').append(b);}
}
function offerInputs(offer={}){
 const row=document.createElement('div');row.className='import-offer';
 for(const [key,type,placeholder,cls] of [['url','url','Retailer product URL','source'],['price','number','Price (₹)',''],['checked_at','date','Date checked',''],['tax_shipping','text','Tax and shipping notes','tax']]){
 const input=document.createElement('input');input.className='form-control '+cls;input.type=type;input.dataset.key=key;input.placeholder=placeholder;input.setAttribute('aria-label',placeholder);input.value=offer[key]||'';if(type==='number'){input.min='.01';input.step='.01';}row.append(input);
 }
 const fetchButton=document.createElement('button');fetchButton.type='button';fetchButton.className='btn btn-sm btn-outline-secondary';fetchButton.textContent='Read retailer price · free';
 fetchButton.onclick=()=>guard(async()=>{if(current?.product_id)throw Error('This product is already imported.');const offer=await api('retailer-offer/',{url:row.querySelector('[data-key=url]').value});for(const el of row.querySelectorAll('input'))if(offer[el.dataset.key])el.value=offer[el.dataset.key];$('review').elements.offers_verified.checked=false;notice(`Read ₹${offer.price}: ${offer.title} (${offer.variant}). Check that this is the exact product before verifying the offers.`);await saveCurrent();});row.append(fetchButton);return row;
}
function select(item){
 current=items.find(i=>i.id===item.id)||item;const d=current.details,form=$('review');form.reset();
 $('editor').hidden=false;$('empty-editor').hidden=true;$('item-title').textContent=current.source_key;$('item-state').textContent=current.product_id?'Imported':'';
 for(const el of form.elements){if(!el.name)continue;if(el.type==='checkbox')el.checked=d[el.name]===true;else el.value=d[el.name]??({unit:'PIECE',unit_value:'1',pricing_policy:'retail_mean'}[el.name]||'');el.disabled=Boolean(current.product_id);}
 $('ocr-text').value=d.ocr_text||'';$('offers').replaceChildren(...Array.from({length:Math.max(3,(d.offers||[]).length)},(_,i)=>offerInputs((d.offers||[])[i])));
 for(const el of $('offers').querySelectorAll('input'))el.disabled=Boolean(current.product_id);
 $('photos').replaceChildren();for(const p of current.photos){const wrap=document.createElement('div');wrap.className='import-photo';const a=document.createElement('a');a.href=p.url;a.target='_blank';a.rel='noopener';const img=document.createElement('img');img.src=p.url;img.alt=d.name||current.source_key;a.append(img);wrap.append(a);if(!current.product_id){const label=document.createElement('label');label.className='d-block small';const check=document.createElement('input');check.type='checkbox';check.dataset.photo=p.id;check.checked=p.selected;label.append(check,document.createTextNode(' Use photo'));wrap.append(label);const b=document.createElement('button');b.type='button';b.textContent='Remove';b.onclick=()=>guard(async()=>{await saveCurrent();replace(await api(path(current.id),{action:'remove_photo',photo_id:p.id}));select(current);});wrap.append(b);}$('photos').append(wrap);}
 $('product-link').hidden=!current.product_id;$('product-link').href=current.product_id?`/management/products/${current.product_id}/`:'#';
 $('ocr').disabled=Boolean(current.product_id);$('add-photo').disabled=Boolean(current.product_id);updateSearch();drawList();
}
function updateSearch(){const name=$('review').elements.name.value||current?.source_key||'';$('search').href='https://www.google.com/search?tbm=shop&gl=in&q='+encodeURIComponent(name+' India');}
$('review').elements.name.addEventListener('input',updateSearch);
$('filter-list').addEventListener('input',drawList);
function details(){const d={};for(const el of $('review').elements){if(el.name)d[el.name]=el.type==='checkbox'?el.checked:el.value;}
 d.ocr_text=$('ocr-text').value;d.offers=[];for(const row of $('offers').children){const offer={currency:'INR',availability:'in_stock',exact_match:true};for(const el of row.querySelectorAll('input'))offer[el.dataset.key]=el.value;if(offer.url||offer.price)d.offers.push(offer);}return d;
}
async function saveCurrent(){if(current&&!current.product_id)replace(await api(path(current.id),{action:'save',details:details(),selected_photo_ids:[...$('photos').querySelectorAll('input:checked')].map(el=>Number(el.dataset.photo))}));}
async function loadBatch(id){batch=await api(`batches/${id}/`);items=batch.items;current=null;$('store').value=batch.store_id||'';$('editor').hidden=true;$('empty-editor').hidden=false;drawList();notice(`Loaded ${items.length} product groups. Select one to review.`);}
async function ensureBatch(){if(batch)return;const b=await api('batches/',{name:'Photos '+new Date().toLocaleDateString()});$('batch').add(new Option(b.name+' · #'+b.id,b.id));$('batch').value=b.id;await loadBatch(b.id);}
async function guard(fn){if(busy){notice('Wait for the current operation, or stop it first.');return;}busy=true;stop=false;const locks=['batch','store','publish','folder','files','load-research'].map(id=>[$(id),$(id).disabled]);for(const [el] of locks)el.disabled=true;$('stop').hidden=false;try{await fn();}catch(e){notice(e.message);}finally{busy=false;for(const [el,disabled] of locks)el.disabled=disabled;$('stop').hidden=true;}}
$('stop').onclick=()=>{stop=true;notice('Stopping after the current item. Saved progress will remain.');};
$('new-batch').onclick=()=>guard(async()=>{await saveCurrent();batch=null;await ensureBatch();});
$('batch').onchange=()=>guard(async()=>{await saveCurrent();if($('batch').value)await loadBatch($('batch').value);});
$('store').onchange=()=>guard(async()=>{await ensureBatch();const result=await api(`batches/${batch.id}/`,{store_id:$('store').value});batch.store_id=result.store_id;notice('Destination Store saved.');});
const hash=async bytes=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
async function compressed(file){
 const image=await createImageBitmap(file,{imageOrientation:'from-image'});const scale=Math.min(1,1600/Math.max(image.width,image.height));const c=document.createElement('canvas');c.width=Math.round(image.width*scale);c.height=Math.round(image.height*scale);const ctx=c.getContext('2d');ctx.fillStyle='white';ctx.fillRect(0,0,c.width,c.height);ctx.drawImage(image,0,0,c.width,c.height);image.close();const blob=await new Promise(resolve=>c.toBlob(resolve,'image/jpeg',.88));if(!blob)throw Error('Could not process '+file.name);return new File([blob],file.name.replace(/\.[^.]+$/,'')+'.jpg',{type:'image/jpeg'});
}
async function uploadPhoto(item,file){const data=new FormData();data.set('action','upload');data.set('image',await compressed(file));const updated=await api(path(item.id),data);replace(updated);return updated;}
async function upload(files){
 await saveCurrent();await ensureBatch();const groups=new Map();let unsupported=0;
 for(const file of files){if(!/\.(jpg|jpeg|png|webp)$/i.test(file.name)){unsupported++;continue;}const parts=(file.webkitRelativePath||file.name).split('/');const key=parts.length>2?parts.slice(1,-1).join('/'):file.name.replace(/\.[^.]+$/,'');if(!groups.has(key))groups.set(key,[]);groups.get(key).push(file);}
 let n=0,failed=0;const logs=[];
 for(const [key,group] of groups){if(stop)break;notice(`Preparing ${key} (${n+1}/${groups.size})…`);try{
  const unique=new Map();for(const file of group){const h=await hash(await file.arrayBuffer());if(!unique.has(h))unique.set(h,file);}
  const fingerprint=await hash(new TextEncoder().encode([...unique.keys()].sort().join('')));
  let item=await api(`batches/${batch.id}/items/`,{source_key:key,source_hash:fingerprint});replace(item);
  if(!item.product_id){for(const file of [...unique.values()].slice(0,30)){if(stop)break;item=await uploadPhoto(item,file);}if(unique.size>5)logs.push(`${key}: ${Math.min(30,unique.size)} review photos uploaded. Select up to five per listing and split different variants.`);if(unique.size>30)logs.push(`${key}: ${unique.size-30} excess photos remain on your device.`);}
 }catch(e){failed++;logs.push(`${key}: ${e.message}`);}n++;$('progress').value=n/groups.size*100;}
 notice(`${stop?'Stopped':'Upload complete'}: ${n} groups processed, ${failed} failed, ${unsupported} unsupported files skipped. Re-select the same folder to retry.`);$('results').textContent=logs.join('\n');if(items.length)select(items[0]);
}
for(const id of ['folder','files'])$(id).onchange=e=>{const files=[...e.target.files];guard(()=>upload(files));e.target.value='';};
$('add-photo').onchange=e=>{const file=e.target.files[0];if(file&&current)guard(async()=>{await saveCurrent();await uploadPhoto(current,file);select(current);});e.target.value='';};
$('split').onclick=()=>guard(async()=>{if(!current||current.product_id)throw Error('Select an unimported group first.');await saveCurrent();await api(path(current.id),{action:'split',source_key:$('split-name').value,photo_ids:[...$('photos').querySelectorAll('input:checked')].map(el=>Number(el.dataset.photo))});await loadBatch(batch.id);notice('Variant separated. Review each group before importing.');});
$('review').onsubmit=e=>{e.preventDefault();guard(async()=>{await saveCurrent();notice('Review saved.');});};
async function processAll(action){await saveCurrent();if(!batch)throw Error('Create an import first.');const logs=[];let passed=0,failed=0;for(const [index,item] of items.entries()){if(stop)break;try{const result=await api(path(item.id),{action,publish:$('publish').checked});logs.push(`${item.source_key}: ${result.state}${result.final_price?' · ₹'+result.final_price:''}${result.research?.limited_sources?' · fewer than 3 sources':''}`);passed++;}catch(e){logs.push(`${item.source_key}: needs review — ${e.message}`);failed++;}$('results').textContent=logs.join('\n');$('progress').value=(index+1)/items.length*100;notice(`${passed} passed · ${failed} need review`);}await loadBatch(batch.id);notice(`${action==='dry_run'?'Check':'Import'} ${stop?'stopped':'finished'}: ${passed} passed, ${failed} need review.`);}
$('check-all').onclick=()=>guard(()=>processAll('dry_run'));$('import-all').onclick=()=>guard(()=>processAll('import'));
$('check-item').onclick=()=>guard(async()=>{await saveCurrent();const r=await api(path(current.id),{action:'dry_run',publish:$('publish').checked});$('results').textContent=JSON.stringify(r,null,2);notice('Product check passed.');});
$('export').onclick=()=>guard(async()=>{await saveCurrent();if(!batch)throw Error('Choose an import first.');const data=await api(`batches/${batch.id}/`);const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`zuuvi-import-${batch.id}.json`;a.click();URL.revokeObjectURL(url);notice('Progress downloaded. Re-select source photos if you move to a new browser.');});
$('load-research').onchange=e=>{const file=e.target.files[0];if(file)guard(async()=>{await saveCurrent();if(!batch)throw Error('Upload photos or select a saved import first.');const data=JSON.parse(await file.text());const rows=Array.isArray(data)?data:data.items;if(!Array.isArray(rows))throw Error('Expected an items array with source_key and details.');let n=0;for(const row of rows){const item=items.find(i=>i.source_key===row.source_key);if(item&&!item.product_id&&row.details){replace(await api(path(item.id),{action:'save',details:row.details}));n++;}}if(current)select(current);notice(`Loaded research for ${n} groups. Check identities and source offers before publishing.`);});e.target.value='';};
$('ocr').onclick=()=>guard(async()=>{
 if(!current?.photos.length)throw Error('Upload photos first.');notice('Loading free text recognition. The first download may take a moment…');
 if(!window.Tesseract)await new Promise((resolve,reject)=>{const s=document.createElement('script');s.src='https://cdn.jsdelivr.net/npm/tesseract.js@6.0.1/dist/tesseract.min.js';s.onload=resolve;s.onerror=()=>reject(Error('Text recognition could not load. You can enter product details manually.'));document.head.append(s);});
 if(!worker)worker=await Tesseract.createWorker('eng',1,{logger:m=>{if(m.status==='recognizing text')notice(`Reading label text… ${Math.round(m.progress*100)}%`);}});
 const texts=[];for(const p of current.photos){if(stop)break;const res=await fetch(p.url);if(!res.ok)throw Error('Could not read photo. Refresh the batch and retry.');const r=await worker.recognize(await res.blob());texts.push(r.data.text);}
 $('ocr-text').value=texts.join('\n\n');await saveCurrent();notice('Label text saved. Check it against the photos before using it.');
});
})();
