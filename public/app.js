const $ = (id)=>document.getElementById(id);
let token = localStorage.getItem('baghdad_live_token') || '';
let deviceId = '';
let me = null;
let map = null;
let selectedPoint = null;
let userPoint = null;
let userMarker = null;
let groups = [];
let captions = [];
let selectedGroup = null;
let selectedCaption = null;
let groupMarkers = new Map();
let captionMarkers = new Map();
let refreshTimer = null;
let messageTimer = null;
let countdownTimer = null;
let secureTimer = null;
let currentSecureRoom = null;
let currentSecureToken = null;
let avatarData = '';
let prevGroupIds = new Set();
let createMode = null;
let pickMarker = null;
let didInitialSnapshot = false;
let notifiedKeys = new Set(JSON.parse(localStorage.getItem('baghdad_notified_events') || '[]'));
let peopleMarkers = new Map();
let peopleMode = false;
let activeProfileUser = null;
let dmTargetUser = null;
let notificationsTimer = null;
let dmsTimer = null;

function esc(s){return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
function fmtDate(ts){try{return new Date(ts*1000).toLocaleString('ar-IQ',{hour:'2-digit',minute:'2-digit',day:'2-digit',month:'2-digit'})}catch{return '-'}}
function fmtCountdown(sec){if(sec===null||sec===undefined)return 'دائمة'; sec=Math.max(0,Math.floor(sec)); const h=Math.floor(sec/3600),m=Math.floor((sec%3600)/60),s=sec%60; return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`}
function toast(msg){const t=$('toast');t.textContent=msg;t.classList.remove('hidden');clearTimeout(t._x);t._x=setTimeout(()=>t.classList.add('hidden'),3200)}
function icon(id){return `<svg><use href="#${id}"/></svg>`}
function renderMentions(text){return esc(text).replace(/(^|\s)@([\w\u0600-\u06FF._-]{2,28})/g,(m,sp,n)=>`${sp}<span class="mention-tag">@${n}</span>`)}
function saveNotifiedKeys(){localStorage.setItem('baghdad_notified_events', JSON.stringify([...notifiedKeys].slice(-600)))}
function distanceMeters(a,b){
  if(!a||!b)return Infinity;
  const R=6371000, toRad=x=>x*Math.PI/180;
  const dLat=toRad(b.lat-a.lat), dLng=toRad(b.lng-a.lng);
  const s1=Math.sin(dLat/2), s2=Math.sin(dLng/2);
  const q=s1*s1+Math.cos(toRad(a.lat))*Math.cos(toRad(b.lat))*s2*s2;
  return 2*R*Math.atan2(Math.sqrt(q),Math.sqrt(1-q));
}
function browserNotify(title, body){
  toast(body || title);
  try{ if('Notification' in window && Notification.permission==='granted') new Notification(title,{body,icon:'favicon.svg'}); }catch{}
}
function requestNotifyPermission(){try{if('Notification' in window && Notification.permission==='default') Notification.requestPermission();}catch{}}

async function sha256(text){const buf=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text));return [...new Uint8Array(buf)].map(b=>b.toString(16).padStart(2,'0')).join('')}
function setCookie(name,value){document.cookie=`${name}=${encodeURIComponent(value)};path=/;max-age=34560000;SameSite=Lax`}
function getCookie(name){return document.cookie.split(';').map(x=>x.trim()).find(x=>x.startsWith(name+'='))?.split('=').slice(1).join('=')||''}
async function loadDeviceId(){
  const fromCookie=decodeURIComponent(getCookie('baghdad_device_id')||'');
  const fromLocal=localStorage.getItem('baghdad_device_id')||'';
  if(fromLocal || fromCookie){deviceId=fromLocal||fromCookie;localStorage.setItem('baghdad_device_id',deviceId);setCookie('baghdad_device_id',deviceId);return deviceId}
  const fp=[navigator.userAgent,navigator.language,screen.width+'x'+screen.height,screen.colorDepth,Intl.DateTimeFormat().resolvedOptions().timeZone,crypto.randomUUID()].join('|');
  deviceId='bdg-'+await sha256(fp);
  localStorage.setItem('baghdad_device_id',deviceId);setCookie('baghdad_device_id',deviceId);return deviceId;
}

async function api(path,opt={}){
  const headers={'Content-Type':'application/json',...(opt.headers||{})};
  if(token) headers.Authorization='Bearer '+token;
  const res=await fetch(path,{...opt,headers,cache:'no-store'});
  const data=await res.json().catch(()=>({ok:false,error:'رد غير مفهوم من السيرفر'}));
  if(!res.ok || data.ok===false) throw new Error(data.error||'حدث خطأ');
  return data;
}

function readImage(file, max=850){
  return new Promise((resolve,reject)=>{
    if(!file)return reject(new Error('لا توجد صورة'));
    if(!file.type.startsWith('image/'))return reject(new Error('الملف ليس صورة'));
    const img=new Image(); const r=new FileReader();
    r.onload=()=>{img.onload=()=>{
      const scale=Math.min(1,max/Math.max(img.width,img.height));
      const c=document.createElement('canvas'); c.width=Math.max(1,Math.round(img.width*scale)); c.height=Math.max(1,Math.round(img.height*scale));
      const ctx=c.getContext('2d'); ctx.drawImage(img,0,0,c.width,c.height);
      resolve(c.toDataURL('image/jpeg',0.82));
    }; img.onerror=()=>reject(new Error('تعذر قراءة الصورة')); img.src=r.result;};
    r.onerror=()=>reject(new Error('تعذر قراءة الصورة')); r.readAsDataURL(file);
  });
}

function switchAuth(mode){
  const login=mode==='login';
  $('loginTab').classList.toggle('active',login);$('registerTab').classList.toggle('active',!login);
  $('loginForm').classList.toggle('hidden',!login);$('registerForm').classList.toggle('hidden',login);
}
$('loginTab').onclick=()=>switchAuth('login');$('registerTab').onclick=()=>switchAuth('register');
$('avatarPick').onclick=()=>$('avatarInput').click();
$('avatarInput').addEventListener('change',async e=>{try{avatarData=await readImage(e.target.files[0],650);$('avatarPreview').src=avatarData;$('avatarPreview').classList.remove('hidden');$('avatarPick').querySelector('span').textContent='تم رفع الصورة الشخصية'}catch(err){toast(err.message)}});
$('resetStoredBtn').onclick=async()=>{
  if(!confirm('سيتم حذف الحساب المرتبط بهذا الجهاز من قاعدة البيانات المحلية حتى تكدر تنشئ حساب جديد. هل تريد المتابعة؟')) return;
  try{ await api('/api/account/device_reset',{method:'POST',body:JSON.stringify({deviceId})}); }catch{}
  localStorage.removeItem('baghdad_live_token');
  localStorage.removeItem('baghdad_device_id');
  localStorage.removeItem('baghdad_notified_events');
  document.cookie='baghdad_device_id=;path=/;max-age=0;SameSite=Lax';
  token=''; deviceId='';
  toast('تم حذف الحساب/المعرف المخزن، سيتم إعادة تحميل الصفحة');
  setTimeout(()=>location.reload(),900);
};

$('registerForm').addEventListener('submit',async e=>{
  e.preventDefault();
  if(!avatarData)return toast('لا يمكن إنشاء الحساب: شرط وضع صورتك الشخصية للدخول.');
  if(!$('regUsername').value.trim()) return toast('لا يمكن إنشاء الحساب: اكتب اسم المستخدم أولاً.');
  if(($('regPassword').value||'').length<6) return toast('لا يمكن إنشاء الحساب: كلمة المرور لازم تكون 6 أحرف أو أكثر.');
  try{
    const data=await api('/api/account/register',{method:'POST',body:JSON.stringify({deviceId,username:$('regUsername').value.trim(),password:$('regPassword').value,avatarData,phone:$('regPhone').value.trim(),address:$('regAddress').value.trim(),bio:$('regBio').value.trim()})});
    token=data.token;me=data.user;localStorage.setItem('baghdad_live_token',token);await showApp();toast('تم إنشاء الحساب لهذا الجهاز');
  }catch(err){toast(err.message)}
});
$('loginForm').addEventListener('submit',async e=>{
  e.preventDefault();
  try{
    const data=await api('/api/account/login',{method:'POST',body:JSON.stringify({deviceId,username:$('loginUsername').value.trim(),password:$('loginPassword').value})});
    token=data.token;me=data.user;localStorage.setItem('baghdad_live_token',token);await showApp();
  }catch(err){toast(err.message)}
});
$('logoutBtn').onclick=async()=>{try{await api('/api/account/logout',{method:'POST',body:'{}'})}catch{} localStorage.removeItem('baghdad_live_token'); token=''; location.reload()};
$('settingsBtn').onclick=()=>toast('لتعديل المعلومات: اضغط على صورتك الشخصية ثم حدّث النسخة القادمة من الإعدادات.');
$('meProfileBtn').onclick=()=>me&&showProfile(me.id);

function initMap(){
  if(map)return;
  map=L.map('map',{zoomControl:true,attributionControl:true}).setView([33.3152,44.3661],12);
  const esri=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'Tiles © Esri'}).addTo(map);
  const labels=L.tileLayer('https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:''}).addTo(map);
  map.on('click',e=>{
    selectedPoint={lat:e.latlng.lat,lng:e.latlng.lng};
    if(pickMarker) map.removeLayer(pickMarker);
    pickMarker=L.marker([selectedPoint.lat,selectedPoint.lng],{icon:makeIcon(createMode==='caption'?'caption':'group')}).addTo(map).bindPopup('النقطة المختارة بدقة').openPopup();
    $('mapTip').textContent=`تم تحديد الموقع: ${selectedPoint.lat.toFixed(5)}, ${selectedPoint.lng.toFixed(5)}`;
    if(createMode==='group'){
      $('groupPointText').textContent=`تم اختيار الموقع بدقة: ${selectedPoint.lat.toFixed(5)}, ${selectedPoint.lng.toFixed(5)}`;
      createMode=null; document.body.classList.remove('picking-map'); openDialog($('groupDialog'));
    }else if(createMode==='caption'){
      $('captionPointText').textContent=`تم اختيار الموقع بدقة: ${selectedPoint.lat.toFixed(5)}, ${selectedPoint.lng.toFixed(5)}`;
      createMode=null; document.body.classList.remove('picking-map'); openDialog($('captionDialog'));
    }
  });
  updateDayNight(); setInterval(updateDayNight,60000);
  requestLocation(true);
}
function updateDayNight(){
  const hr=new Date().getHours(); const night=hr>=18||hr<6;
  $('mapLiveMask').classList.toggle('night',night);$('dayNightText').textContent=night?'ليل حي - الخريطة داكنة':'نهار حي - سحب متحركة';
}
function requestLocation(auto=false){
  if(!navigator.geolocation){if(!auto)toast('المتصفح لا يدعم تحديد الموقع');return}
  navigator.geolocation.getCurrentPosition(pos=>{
    userPoint={lat:pos.coords.latitude,lng:pos.coords.longitude};selectedPoint=userPoint;
    if(map){map.setView([userPoint.lat,userPoint.lng],15); if(userMarker)map.removeLayer(userMarker); userMarker=L.marker([userPoint.lat,userPoint.lng],{icon:makeIcon('me')}).addTo(map).bindPopup('موقعك الحالي').openPopup();}
    api('/api/location',{method:'POST',body:JSON.stringify(userPoint)}).catch(()=>{});
    $('mapTip').textContent='تم تحديد موقعك، يمكنك الآن إنشاء دردشة أو كتابة فوق البيوت.';
  },()=>{if(!auto)toast('لم يتم السماح بتحديد الموقع')},{enableHighAccuracy:true,timeout:8000,maximumAge:60000});
}
$('locateBtn').onclick=()=>requestLocation(false);

function makeIcon(type, privacy='public'){
  let cls='marker-wrap', sym='i-chat';
  if(type==='caption'){cls+=' caption';sym='i-house'}
  else if(type==='me'){cls+=' me';sym='i-pin'}
  else if(privacy==='private'){cls+=' group-private'}
  const html=`<div class="${cls}">${icon(sym)}</div>`;
  return L.divIcon({className:'neon-marker',html,iconSize:[42,42],iconAnchor:[21,40],popupAnchor:[0,-38]});
}
function popupGroup(g){return `<div class="map-popup"><h4>${esc(g.name)}</h4><p>المنطقة: ${esc(g.district)}</p><p>النوع: ${g.privacy==='private'?'خاص':'عام'} · ${g.lifetime==='temp24'?'مؤقتة 24 ساعة':'دائمة'}</p><p>المالك: ${esc(g.owner)}</p><p>المتبقي: <b>${fmtCountdown(g.expiresIn)}</b></p><div class="pop-actions"><button class="btn primary thin" onclick="window.pickGroup(${g.id})">فتح</button></div></div>`}
function popupCaption(c){return `<div class="map-popup"><h4>${esc(c.title)}</h4><p>المنطقة: ${esc(c.district)}</p><p>بواسطة: ${esc(c.owner)}</p><p>${esc(c.bodyPreview)}</p><div class="pop-actions"><button class="btn secondary thin" onclick="window.pickCaption(${c.id})">إضافة تعليقات</button></div></div>`}
window.pickGroup=id=>selectGroup(id,true);window.pickCaption=async id=>{await selectCaption(id,true);setTimeout(()=>$('captionCommentInput')?.focus(),200)};

function renderMapObjects(){
  if(!map)return;
  for(const[id,m]of groupMarkers.entries()) if(!groups.find(g=>g.id===id)){map.removeLayer(m);groupMarkers.delete(id)}
  for(const[id,m]of captionMarkers.entries()) if(!captions.find(c=>c.id===id)){map.removeLayer(m);captionMarkers.delete(id)}
  groups.forEach(g=>{let m=groupMarkers.get(g.id); if(!m){m=L.marker([g.lat,g.lng],{icon:makeIcon('group',g.privacy)}).addTo(map);m.on('click',()=>selectGroup(g.id,false));groupMarkers.set(g.id,m)}else{m.setLatLng([g.lat,g.lng]);m.setIcon(makeIcon('group',g.privacy))}m.bindPopup(popupGroup(g))});
  captions.forEach(c=>{let m=captionMarkers.get(c.id); if(!m){m=L.marker([c.lat,c.lng],{icon:makeIcon('caption')}).addTo(map);m.on('click',()=>selectCaption(c.id,false));captionMarkers.set(c.id,m)}else m.setLatLng([c.lat,c.lng]);m.bindPopup(popupCaption(c))});
}
function renderStats(hasNew=false){
  $('statGroups').textContent=groups.length;$('statCaptions').textContent=captions.length;$('statPrivate').textContent=groups.filter(g=>g.privacy==='private').length;$('statLive').textContent=hasNew?'نشاط':'حي';
  $('listBadge').textContent=groups.length;$('captionBadge').textContent=captions.length;
}
function cardAvatar(src, name, uid){return src?`<img class="small-avatar" src="${src}" onclick="event.stopPropagation();showProfile(${uid})" alt="${esc(name)}">`:`<div class="small-avatar avatar" onclick="event.stopPropagation();showProfile(${uid})">${esc((name||'?').slice(0,1))}</div>`}
function renderGroupList(){
  $('groupList').innerHTML=groups.length?groups.map(g=>`<article class="item-card ${selectedGroup?.id===g.id?'active':''}" onclick="selectGroup(${g.id},true)"><div class="row">${cardAvatar(g.ownerAvatar,g.owner,g.ownerId)}<div><h3>${esc(g.name)}</h3><p>${esc(g.district)} · ${esc(g.owner)}</p></div></div><div class="badge-line"><span class="badge ${g.privacy==='private'?'private':''}">${g.privacy==='private'?'خاص':'عام'}</span><span class="badge ${g.lifetime==='temp24'?'temp':'live'}">${g.lifetime==='temp24'?'24 ساعة '+fmtCountdown(g.expiresIn):'دائمة'}</span><span class="badge">${g.members} عضو</span></div></article>`).join(''):`<div class="empty-state small"><h3>لا توجد دردشات</h3></div>`;
}
function renderCaptionList(){
  $('captionList').innerHTML=captions.length?captions.map(c=>`<article class="item-card ${selectedCaption?.id===c.id?'active':''}" onclick="selectCaption(${c.id},true)"><div class="row">${cardAvatar(c.ownerAvatar,c.owner,c.ownerId)}<div><h3>${esc(c.title)}</h3><p>${esc(c.district)} · ${c.commentsCount} رد</p></div></div><p>${esc(c.bodyPreview)}</p></article>`).join(''):`<div class="empty-state small"><h3>لا توجد كتابات</h3></div>`;
}

function applySelectedGroup(){
  if(!selectedGroup)return;
  $('emptyChat').classList.add('hidden');$('chatBox').classList.remove('hidden');
  $('chatTitle').textContent=selectedGroup.name;$('chatMeta').textContent=`المالك: ${selectedGroup.owner} · آخر نشاط: ${fmtDate(selectedGroup.lastActivity)}`;
  $('chatDistrictChip').textContent=selectedGroup.district;$('chatTypeChip').textContent=selectedGroup.privacy==='private'?'خاص':'عام';$('chatLifeChip').textContent=selectedGroup.lifetime==='temp24'?'مؤقتة 24 ساعة':'دائمة';
  $('infoName').textContent=selectedGroup.name;$('infoPrivacy').textContent=selectedGroup.privacy==='private'?'خاص':'عام';$('infoLife').textContent=selectedGroup.lifetime==='temp24'?fmtCountdown(selectedGroup.expiresIn):'دائمة';$('infoDistrict').textContent=selectedGroup.district;$('infoOwner').textContent=selectedGroup.owner;$('infoMembers').textContent=selectedGroup.members;
  const canWrite=selectedGroup.myStatus==='accepted'||selectedGroup.myRole==='owner';const canJoin=!(canWrite||selectedGroup.myStatus==='pending'||selectedGroup.myStatus==='rejected');
  $('joinBtn').classList.toggle('hidden',!canJoin);$('joinBtn').textContent=selectedGroup.privacy==='private'?'إرسال طلب دخول':'دخول الدردشة';$('messageForm').classList.toggle('hidden',!canWrite);
  $('chatCover').style.backgroundImage=selectedGroup.coverData?`linear-gradient(120deg,rgba(4,13,28,.5),rgba(9,24,45,.2)),url(${selectedGroup.coverData})`:'';
  startCountdown();
}
function startCountdown(){
  clearInterval(countdownTimer); if(!selectedGroup)return;
  $('countdownText').textContent=selectedGroup.lifetime==='temp24'?'المتبقي: '+fmtCountdown(selectedGroup.expiresIn):'دائمة';
  countdownTimer=setInterval(()=>{if(!selectedGroup)return;if(selectedGroup.expiresIn!==null&&selectedGroup.expiresIn!==undefined){selectedGroup.expiresIn=Math.max(0,selectedGroup.expiresIn-1)}$('countdownText').textContent=selectedGroup.lifetime==='temp24'?'المتبقي: '+fmtCountdown(selectedGroup.expiresIn):'دائمة';$('infoLife').textContent=selectedGroup.lifetime==='temp24'?fmtCountdown(selectedGroup.expiresIn):'دائمة'},1000)
}
async function selectGroup(id,pan){
  const g=groups.find(x=>x.id===id); if(!g)return; selectedGroup=g; renderGroupList(); applySelectedGroup();
  if(pan&&map){map.setView([g.lat,g.lng],Math.max(map.getZoom(),15));groupMarkers.get(g.id)?.openPopup()}
  await loadMessages(true); await loadRequests(true);
}
$('joinBtn').onclick=async()=>{if(!selectedGroup)return;try{const data=await api(`/api/groups/${selectedGroup.id}/join`,{method:'POST',body:'{}'});toast(data.message||'تم');await loadAll();await selectGroup(selectedGroup.id,false)}catch(err){toast(err.message)}};
async function loadMessages(silent=false){
  if(!selectedGroup)return;
  try{const data=await api(`/api/groups/${selectedGroup.id}/messages`);const rows=data.messages||[];$('messages').innerHTML=rows.length?rows.map(m=>`<div class="message-row ${m.mine?'mine':''}">${m.avatarData?`<img class="avatar" src="${m.avatarData}" onclick="showProfile(${m.userId})">`:`<div class="avatar" onclick="showProfile(${m.userId})">${esc((m.username||'?').slice(0,1))}</div>`}<div class="message-bubble"><div class="message-top"><span class="message-name">${esc(m.username)}</span><span>${fmtDate(m.createdAt)}</span></div><div class="message-text">${renderMentions(m.text)}</div></div></div>`).join(''):'<div class="empty-state small"><h3>لا توجد رسائل</h3><p>ابدأ أول رسالة.</p></div>';$('messages').scrollTop=$('messages').scrollHeight}catch(err){if(!silent)toast(err.message)}
}
$('messageForm').onsubmit=async e=>{e.preventDefault();const text=$('messageInput').value.trim();if(!text||!selectedGroup)return;try{await api(`/api/groups/${selectedGroup.id}/messages`,{method:'POST',body:JSON.stringify({text})});$('messageInput').value='';await loadAll();await selectGroup(selectedGroup.id,false)}catch(err){toast(err.message)}};
async function loadRequests(silent=false){
  if(!selectedGroup||selectedGroup.ownerId!==me?.id){$('ownerRequests').classList.add('hidden');$('ownerRequests').innerHTML='';return}
  try{const data=await api(`/api/groups/${selectedGroup.id}/requests`);const reqs=data.requests||[];const box=$('ownerRequests');if(!reqs.length){box.classList.add('hidden');box.innerHTML='';return}box.classList.remove('hidden');box.innerHTML='<b>طلبات الدخول</b>'+reqs.map(r=>`<div class="request-row"><span>${esc(r.username)}</span><div class="request-actions"><button class="accept-btn" onclick="handleRequest(${r.id},'accept')">قبول</button><button class="reject-btn" onclick="handleRequest(${r.id},'reject')">رفض</button></div></div>`).join('')}catch(err){if(!silent)toast(err.message)}
}
window.handleRequest=async(uid,action)=>{try{await api(`/api/groups/${selectedGroup.id}/requests/${uid}/${action}`,{method:'POST',body:'{}'});toast(action==='accept'?'تم القبول':'تم الرفض');await selectGroup(selectedGroup.id,false)}catch(err){toast(err.message)}};
$('uploadCoverBtn').onclick=()=>selectedGroup?$('coverInput').click():toast('اختر دردشة أولاً');
$('coverInput').onchange=e=>{const file=e.target.files?.[0];if(!file||!selectedGroup)return;readImage(file,1200).then(async data=>{await api(`/api/groups/${selectedGroup.id}/cover`,{method:'POST',body:JSON.stringify({imageData:data})});toast('تم رفع الغلاف');await loadAll();await selectGroup(selectedGroup.id,false)}).catch(err=>toast(err.message))};

function applySelectedCaption(){if(!selectedCaption)return;$('emptyCaption').classList.add('hidden');$('captionBox').classList.remove('hidden');$('captionTitle').textContent=selectedCaption.title;$('captionMeta').textContent=`${selectedCaption.district} · ${selectedCaption.owner} · ${fmtDate(selectedCaption.createdAt)}`;$('captionBody').textContent=selectedCaption.body}
async function selectCaption(id,pan){const c=captions.find(x=>x.id===id);if(!c)return;selectedCaption=c;renderCaptionList();applySelectedCaption();if(pan&&map){map.setView([c.lat,c.lng],Math.max(map.getZoom(),16));captionMarkers.get(c.id)?.openPopup()}await loadCaptionComments(true)}
async function loadCaptionComments(silent=false){if(!selectedCaption)return;try{const data=await api(`/api/captions/${selectedCaption.id}/comments`);const rows=data.comments||[];$('captionComments').innerHTML=rows.length?rows.map(r=>`<div class="caption-comment"><div class="message-top"><span class="message-name">${esc(r.username)}</span><span>${fmtDate(r.createdAt)}</span></div><div class="message-text">${renderMentions(r.text)}</div></div>`).join(''):'<div class="empty-state small"><h3>لا توجد ردود</h3></div>'}catch(err){if(!silent)toast(err.message)}}
$('captionCommentForm').onsubmit=async e=>{e.preventDefault();const text=$('captionCommentInput').value.trim();if(!text||!selectedCaption)return;try{await api(`/api/captions/${selectedCaption.id}/comments`,{method:'POST',body:JSON.stringify({text})});$('captionCommentInput').value='';await loadAll();await selectCaption(selectedCaption.id,false)}catch(err){toast(err.message)}};

function notifyNearbyEvents(){
  const radius=140;
  if(!userPoint||!didInitialSnapshot)return;
  for(const g of groups){
    const key='g:'+g.id;
    if(notifiedKeys.has(key)) continue;
    notifiedKeys.add(key);
    if(g.ownerId!==me?.id && distanceMeters(userPoint,{lat:g.lat,lng:g.lng})<=radius){
      browserNotify('دردشة بغداد', `صارت دردشة فوق موقعك: ${g.name}`);
    }
  }
  for(const c of captions){
    const key='c:'+c.id;
    if(notifiedKeys.has(key)) continue;
    notifiedKeys.add(key);
    if(c.ownerId!==me?.id && distanceMeters(userPoint,{lat:c.lat,lng:c.lng})<=radius){
      browserNotify('دردشة بغداد', `أحد كتب فوق بيتك/موقعك: ${c.title}`);
    }
  }
  saveNotifiedKeys();
}
async function loadAll(showMsg=false){
  try{
    const data=await api('/api/snapshot');
    const old=prevGroupIds;
    groups=(data.groups||[]);captions=(data.captions||[]);
    const ids=new Set(groups.map(g=>g.id));
    const hasNew=[...ids].some(id=>!old.has(id)&&old.size>0);
    if(!didInitialSnapshot){
      groups.forEach(g=>notifiedKeys.add('g:'+g.id));
      captions.forEach(c=>notifiedKeys.add('c:'+c.id));
      saveNotifiedKeys();
      didInitialSnapshot=true;
    }else{
      notifyNearbyEvents();
    }
    prevGroupIds=ids;renderStats(hasNew);renderGroupList();renderCaptionList();renderMapObjects();
    if(selectedGroup){const fresh=groups.find(g=>g.id===selectedGroup.id);if(fresh){selectedGroup=fresh;applySelectedGroup()}else{selectedGroup=null;$('chatBox').classList.add('hidden');$('emptyChat').classList.remove('hidden')}}
    if(selectedCaption){const fresh=captions.find(c=>c.id===selectedCaption.id);if(fresh){selectedCaption=fresh;applySelectedCaption()}}
    if(map)setTimeout(()=>map.invalidateSize(true),80);if(showMsg)toast('تم التحديث')
  }catch(err){toast(err.message)}
}
$('refreshBtn').onclick=()=>loadAll(true);

function pointForCreate(){return selectedPoint||userPoint||{lat:map?.getCenter().lat||33.3152,lng:map?.getCenter().lng||44.3661}}
function openDialog(d){if(typeof d.showModal==='function')d.showModal();else d.classList.remove('hidden')}
document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>b.closest('dialog')?.close());
$('createGroupBtn').onclick=()=>{createMode='group';selectedPoint=null;document.body.classList.add('picking-map');$('mapTip').textContent='اختر الموقع من الخريطة بدقة لوضع دبوس الدردشة فوق البيت أو الشارع.';toast('اضغط على الخريطة لتحديد موقع الدردشة بدقة');};
$('groupForm').onsubmit=async e=>{e.preventDefault();if(!selectedPoint)return toast('لازم تختار الموقع من الخريطة بدقة أولاً.');const p=selectedPoint;try{const data=await api('/api/groups',{method:'POST',body:JSON.stringify({name:$('groupName').value.trim(),privacy:$('groupPrivacy').value,lifetime:$('groupLifetime').value,lat:p.lat,lng:p.lng})});$('groupDialog').close();$('groupName').value='';if(pickMarker){map.removeLayer(pickMarker);pickMarker=null}await loadAll();await selectGroup(data.group.id,true);toast('تم إنشاء الدردشة') }catch(err){toast(err.message)}};
$('createCaptionBtn').onclick=()=>{createMode='caption';selectedPoint=null;document.body.classList.add('picking-map');$('mapTip').textContent='اختر الموقع من الخريطة بدقة لوضع الكتابة فوق البيت أو المبنى.';toast('اضغط على الخريطة لتحديد مكان الكتابة بدقة');};
$('captionForm').onsubmit=async e=>{e.preventDefault();if(!selectedPoint)return toast('لازم تختار الموقع من الخريطة بدقة أولاً.');const p=selectedPoint;try{const data=await api('/api/captions',{method:'POST',body:JSON.stringify({title:$('captionTitleInput').value.trim(),text:$('captionText').value.trim(),lat:p.lat,lng:p.lng})});$('captionDialog').close();$('captionTitleInput').value='';$('captionText').value='';if(pickMarker){map.removeLayer(pickMarker);pickMarker=null}await loadAll();await selectCaption(data.caption.id,true);toast('تمت الكتابة فوق البيوت')}catch(err){toast(err.message)}};

$('createSecureBtn').onclick=()=>{ $('secureLinkBox').classList.add('hidden');$('secureTitle').value='';openDialog($('secureDialog')) };
$('secureCreateForm').onsubmit=async e=>{e.preventDefault();try{const data=await api('/api/secure_rooms',{method:'POST',body:JSON.stringify({title:$('secureTitle').value.trim()||'دردشة فائقة التشفير'})});const link=secureUrl(data.room.shareToken);$('secureLinkText').textContent=link;$('secureLinkBox').classList.remove('hidden');currentSecureToken=data.room.shareToken;$('secureDialog').close();openSecureRoom(data.room);toast('تم إنشاء الرابط المشفر')}catch(err){toast(err.message)}};
function secureUrl(t){return `${location.origin}${location.pathname}?secure=${encodeURIComponent(t)}`}
$('copySecureLink').onclick=()=>copyText($('secureLinkText').textContent);
$('copyOpenSecureLink').onclick=()=>copyText($('secureRoomLink').textContent);
function copyText(t){navigator.clipboard?.writeText(t).then(()=>toast('تم نسخ الرابط')).catch(()=>toast('انسخ الرابط يدوياً'))}

async function openSecureByToken(t){try{const data=await api(`/api/secure_rooms/by_token/${encodeURIComponent(t)}`);currentSecureToken=t;openSecureRoom(data.room);history.replaceState(null,'',location.pathname)}catch(err){toast(err.message)}}
function openSecureRoom(room){
  currentSecureRoom=room;$('secureRoom').classList.remove('hidden');$('secureRoomTitle').textContent=room.title;$('secureRoomLink').textContent=secureUrl(room.shareToken);$('secureExitBtn').textContent=room.isOwner?'حذف الدردشة والخروج':'خروج من الدردشة';renderSecureMembers(room.members||[]);loadSecureMessages();clearInterval(secureTimer);secureTimer=setInterval(loadSecureMessages,1800);
}
function renderSecureMembers(rows){$('secureMembers').innerHTML=rows.length?rows.map(m=>`<div class="secure-member"><img src="${m.avatarData}" alt=""><div><b>${esc(m.username)}</b><small style="display:block;color:#8fa9c5">${fmtDate(m.lastSeen)}</small></div></div>`).join(''):'<div class="empty-state small"><h3>لا أحد حالياً</h3></div>'}
async function loadSecureMessages(){if(!currentSecureRoom)return;try{const data=await api(`/api/secure_rooms/${currentSecureRoom.id}/messages`);currentSecureRoom=data.room;renderSecureMembers(data.room.members||[]);const rows=data.messages||[];$('secureMessages').innerHTML=rows.length?rows.map(m=>`<div class="secure-message ${m.mine?'mine':''}"><img src="${m.avatarData}" onclick="showProfile(${m.userId})"><div class="secure-bubble"><div class="message-top"><span class="message-name">${esc(m.username)}</span><span>${fmtDate(m.createdAt)}</span></div><div class="message-text">${renderMentions(m.text)}</div></div></div>`).join(''):'<div class="empty-state small"><h3 style="color:white">لا توجد رسائل مشفرة</h3></div>';$('secureMessages').scrollTop=$('secureMessages').scrollHeight}catch(err){clearInterval(secureTimer);$('secureRoom').classList.add('hidden');currentSecureRoom=null;toast(err.message)}}
$('secureMessageForm').onsubmit=async e=>{e.preventDefault();const text=$('secureMessageInput').value.trim();if(!text||!currentSecureRoom)return;try{await api(`/api/secure_rooms/${currentSecureRoom.id}/messages`,{method:'POST',body:JSON.stringify({text})});$('secureMessageInput').value='';await loadSecureMessages()}catch(err){toast(err.message)}};
$('secureExitBtn').onclick=async()=>{if(!currentSecureRoom)return;try{await api(`/api/secure_rooms/${currentSecureRoom.id}/leave`,{method:'POST',body:'{}'})}catch{}clearInterval(secureTimer);$('secureRoom').classList.add('hidden');currentSecureRoom=null;toast('تم الخروج من الدردشة المشفرة')};

async function showProfile(uid){try{const data=await api(`/api/users/${uid}`);const u=data.user;activeProfileUser=u;$('profileAvatar').src=u.avatarData;$('profileName').textContent=u.username;$('profilePhone').textContent=u.phone||'غير مضاف';$('profileAddress').textContent=u.address||'غير مضاف';$('profileBio').textContent=u.bio||'غير مضاف';$('profileLocation').textContent=u.hasLocation?'محدد على الخريطة':'موجود لكن لم يحدد موقعه';openDialog($('profileDialog'))}catch(err){toast(err.message)}}
window.showProfile=showProfile;
document.querySelector('[data-close-profile]').onclick=()=>$('profileDialog').close();
$('cityPeopleBtn').onclick=togglePeopleOnMap;
$('notificationsBtn').onclick=async()=>{await loadNotifications(false);openDialog($('notificationsDialog'))};
$('directMessagesBtn').onclick=async()=>{await loadDirectMessages(false);openDialog($('directMessagesDialog'))};
$('profileSendMsgBtn').onclick=()=>{if(activeProfileUser)openDmTo(activeProfileUser.id,false)};
$('profileShareChatBtn').onclick=()=>{if(!selectedGroup)return toast('اختر دردشة أولاً حتى تشاركها'); if(activeProfileUser)openDmTo(activeProfileUser.id,true)};
$('directMessageForm').onsubmit=async e=>{e.preventDefault();const receiverId=+$('directTargetId').value;const text=$('directMessageText').value.trim();const groupId=$('directShareGroupId').value||null;if(!receiverId||!text)return toast('اكتب الرسالة أولاً');try{await api('/api/direct_messages',{method:'POST',body:JSON.stringify({receiverId,text,groupId})});$('directMessageDialog').close();toast('تم إرسال الرسالة الخاصة');await loadDirectMessages(true)}catch(err){toast(err.message)}};


function personVirtualPoint(u){
  if(u.hasLocation) return {lat:u.lat,lng:u.lng,located:true};
  const a=(u.id*37)%360, r=0.025+((u.id*17)%40)/1000;
  return {lat:33.3152+Math.sin(a)*r,lng:44.3661+Math.cos(a)*r,located:false};
}
function makePersonIcon(u){
  const cls=u.hasLocation?'person-marker located':'person-marker unlocated';
  const av=u.avatarData?`<img src="${u.avatarData}" alt="">`:`<span>${esc((u.username||'?').slice(0,1))}</span>`;
  return L.divIcon({className:'person-div-icon',html:`<div class="${cls}">${av}</div>`,iconSize:[48,48],iconAnchor:[24,42],popupAnchor:[0,-38]});
}
async function togglePeopleOnMap(){
  if(!map)return;
  if(peopleMode){for(const m of peopleMarkers.values())map.removeLayer(m);peopleMarkers.clear();peopleMode=false;$('cityPeopleBtn').classList.remove('active');$('mapTip').textContent='تم إخفاء بروفايلات اهالي المدينة.';return}
  try{
    const data=await api('/api/people');
    const people=data.people||[];
    people.forEach(u=>{
      const p=personVirtualPoint(u);
      const marker=L.marker([p.lat,p.lng],{icon:makePersonIcon(u)}).addTo(map);
      const note=u.hasLocation?'هذا الشخص محدد موقعه':'اللون المختلف معناتها الشخص موجود بس ممحدد موقعه';
      marker.bindPopup(`<div class="map-popup person-pop"><h4>${esc(u.username)}</h4><p>${note}</p><div class="pop-actions"><button class="btn primary thin" onclick="showProfile(${u.id})">الملف الشخصي</button><button class="btn secondary thin" onclick="openDmTo(${u.id})">إرسال رسالة</button></div></div>`);
      peopleMarkers.set(u.id,marker);
    });
    peopleMode=true;$('cityPeopleBtn').classList.add('active');
    $('mapTip').textContent='ظهرت بروفايلات الناس. اللون المختلف معناتها الشخص موجود بس ممحدد موقعه.';
    toast('تم عرض اهالي المدينة على الخريطة');
  }catch(err){toast(err.message)}
}
async function loadNotifications(silent=true){
  if(!token)return;
  try{
    const data=await api('/api/notifications');
    $('notificationsCount').textContent=data.unread||0;
    const rows=data.notifications||[];
    $('notificationsList').innerHTML=rows.length?rows.map(n=>`<article class="notify-card ${n.read_at?'':'unread'}" onclick="openNotification(${n.id},'${esc(n.ref_type)}',${n.ref_id||0})"><b>${esc(n.title)}</b><p>${esc(n.body)}</p><span>${fmtDate(n.created_at)}</span></article>`).join(''):'<div class="empty-state small"><h3>لا توجد اشعارات</h3></div>';
  }catch(err){if(!silent)toast(err.message)}
}
async function openNotification(id,type,refId){
  try{await api(`/api/notifications/${id}/read`,{method:'POST',body:'{}'});await loadNotifications(true)}catch{}
  if(type==='group'&&refId){await loadAll();selectGroup(refId,true);$('notificationsDialog').close()}
  if(type==='caption'&&refId){await loadAll();selectCaption(refId,true);$('notificationsDialog').close()}
}
async function loadDirectMessages(silent=true){
  if(!token)return;
  try{
    const data=await api('/api/direct_messages');
    const rows=data.messages||[];
    const unread=rows.filter(r=>!r.mine&&!r.read_at).length;
    $('dmCount').textContent=unread;
    $('directMessagesList').innerHTML=rows.length?rows.map(m=>`<article class="dm-card"><div><b>${esc(m.mine?'أنت':m.sender_name)}</b><span> إلى ${esc(m.receiver_name)}</span></div><p>${renderMentions(m.text)}</p>${m.group_id?`<button class="btn primary thin" onclick="openSharedGroup(${m.group_id})">فتح الدردشة المشتركة: ${esc(m.group_name||'دردشة')}</button>`:''}<small>${fmtDate(m.created_at)}</small></article>`).join(''):'<div class="empty-state small"><h3>لا توجد رسائل خاصة</h3></div>';
  }catch(err){if(!silent)toast(err.message)}
}
async function openSharedGroup(gid){await loadAll();selectGroup(gid,true);$('directMessagesDialog').close()}
function openDmTo(uid, share=false){
  dmTargetUser=uid;
  $('directTargetId').value=uid;
  $('directShareGroupId').value=share&&selectedGroup?selectedGroup.id:'';
  const name=activeProfileUser&&activeProfileUser.id===uid?activeProfileUser.username:'المستخدم';
  $('directTargetName').textContent='إلى: '+name;
  $('directMessageText').value=share&&selectedGroup?`تمت مشاركة الدردشة وياك: ${selectedGroup.name}\nادخل عليها من الرسائل الخاصة.`:'';
  openDialog($('directMessageDialog'));
}
window.openDmTo=openDmTo;window.openNotification=openNotification;window.openSharedGroup=openSharedGroup;

async function showApp(){
  $('authScreen').classList.add('hidden');$('appScreen').classList.remove('hidden');
  $('meName').textContent=me?.username||'-';$('meAvatar').src=me?.avatarData||'';
  initMap();requestNotifyPermission();await loadAll();await loadNotifications(true);await loadDirectMessages(true);clearInterval(refreshTimer);refreshTimer=setInterval(loadAll,5000);clearInterval(messageTimer);messageTimer=setInterval(async()=>{if(selectedGroup){await loadMessages(true);await loadRequests(true)}if(selectedCaption)await loadCaptionComments(true)},2500);clearInterval(notificationsTimer);notificationsTimer=setInterval(()=>loadNotifications(true),5000);clearInterval(dmsTimer);dmsTimer=setInterval(()=>loadDirectMessages(true),6000);setTimeout(()=>map.invalidateSize(true),300);
  const pending=new URLSearchParams(location.search).get('secure'); if(pending) setTimeout(()=>openSecureByToken(pending),600);
}
async function boot(){await loadDeviceId();const qs=new URLSearchParams(location.search);const secure=qs.get('secure');if(!token){if(secure)toast('سجل دخولك أولاً حتى تدخل الرابط المشفر');return}try{const data=await api('/api/me');if(data.user){me=data.user;await showApp()}}catch{localStorage.removeItem('baghdad_live_token');token=''}}
boot();
