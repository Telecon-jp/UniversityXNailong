import {api} from './client/api.js';
import {esc,icon} from './client/ui.js';
import {createCatalogView} from './client/catalog.js';
import {openSubmission} from './client/submission.js';
import {bindHeroLaugh} from './client/hero-laugh.js';
import {openSponsorship} from './client/sponsorship.js';
import {friendLinkCard} from './client/friend-links.js';
const memes=[],videos=[],software=[],links=[];

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const page = document.body.dataset.page || 'home';
const params = new URLSearchParams(location.search);
const catalog = page === 'links' ? links : page === 'videos' ? videos : page === 'software' ? software : memes;

const state = {
  query: params.get('q') || '',
  filter: params.get('category') || '全部',
  format: ['GIF', '静态'].includes(params.get('format')) ? params.get('format') : '全部',
  page: Math.max(1, Number.parseInt(params.get('page'),10) || 1),
  favorites: new Set()
};
try {
  const saved = JSON.parse(localStorage.getItem('naiwa-favorites') || '[]');
  if (Array.isArray(saved)) state.favorites = new Set(saved.filter(id => typeof id === 'string'));
} catch { /* Browsing does not depend on storage. */ }
const pageSize = 16;
let toastTimer;
let currentMeme = null;
let gifPlaying = false;
function toast(message) {
  $('#toast').textContent = message;
  $('#toast').classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('#toast').classList.remove('visible'), 2800);
}
function scrollBehavior() { return matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'; }
bindHeroLaugh({button:$('#hero-laugh-button'),image:$('#hero-laugh-button img'),audio:$('#hero-laugh-audio'),notify:toast});
function matches(item) {
  const text = [item.title,item.name,item.author,item.category,item.tag,item.keyword,item.desc,item.platform,item.university,item.url].filter(Boolean).join(' ').toLocaleLowerCase();
  return state.query.trim().toLocaleLowerCase().split(/\s+/).every(word => text.includes(word));
}
function filtered(items, useCategory = true) {
  return items.filter(item => matches(item) &&
    (!useCategory || state.filter === '全部' || (state.filter === '收藏' ? state.favorites.has(item.id) : item.category === state.filter)) &&
    (items !== memes || state.format === '全部' || item.format === state.format));
}
function syncUrl() {
  if (page === 'about') return;
  const next = new URLSearchParams();
  if (state.query) next.set('q',state.query);
  if (state.filter !== '全部') next.set('category',state.filter);
  if (page === 'memes' && state.format !== '全部') next.set('format',state.format);
  if (page === 'memes' && state.page > 1) next.set('page',String(state.page));
  history.replaceState(null,'',location.pathname+(next.size?'?'+next:'')+location.hash);
}
const {gifPoster,favoriteButton,memeVisual,memeCard,videoCard,softwareCard}=createCatalogView({isFavorite:id=>state.favorites.has(id),page});
function renderPagination(total) {
  const pages = Math.max(1,Math.ceil(total/pageSize));
  const el = $('#pagination');
  if (!el) return;
  el.hidden = total <= pageSize;
  el.innerHTML = '<button data-page="'+(state.page-1)+'" '+(state.page===1?'disabled':'')+' aria-label="上一页">上一页</button>'+Array.from({length:pages},(_,i)=>'<button data-page="'+(i+1)+'" '+(state.page===i+1?'aria-current="page"':'')+' aria-label="第 '+(i+1)+' 页">'+(i+1)+'</button>').join('')+'<button data-page="'+(state.page+1)+'" '+(state.page===pages?'disabled':'')+' aria-label="下一页">下一页</button>';
}
function render() {
  if (page === 'about') return;
  let total;
  if (page === 'home') {
    const m = filtered(memes);
    const v = filtered(videos,false);
    const s = filtered(software,false);
    const l = filtered(links,false);
    $('#meme-grid').innerHTML = m.slice(0,8).map(memeCard).join('');
    $('#meme-empty').hidden = m.length !== 0;
    $('#video-grid').innerHTML = v.slice(0,3).map(videoCard).join('') || '<p class="dialog-intro">没有找到相关视频，换个关键词试试。</p>';
    $('#software-grid').innerHTML = s.slice(0,3).map(softwareCard).join('') || '<p class="dialog-intro">没有找到相关资源，换个关键词试试。</p>';
    $('#friend-grid').innerHTML = l.slice(0,6).map(friendLinkCard).join('') || '<p class="dialog-intro">暂时没有匹配的友站，可换个关键词或推荐新站点。</p>';
    $('.art-feature').hidden = !!state.query;
    total = m.length+v.length+s.length+l.length;
  } else {
    const items = filtered(catalog);
    total = items.length;
    state.page = Math.min(state.page,Math.max(1,Math.ceil(total/pageSize)));
    const shown = page === 'memes' ? items.slice((state.page-1)*pageSize,state.page*pageSize) : items;
    $('#'+(page==='links'?'friend':page==='memes'?'meme':page==='videos'?'video':'software')+'-grid').innerHTML = shown.map(page==='links'?friendLinkCard:page==='memes'?memeCard:page==='videos'?videoCard:softwareCard).join('');
    $('#catalog-empty').hidden = total !== 0;
    $('#result-count').textContent = total ? '找到 '+total+' '+(page==='links'?'个友站':page==='memes'?'只奶蛙':page==='videos'?'个视频':'项资源')+(page==='memes'?' · 本页 '+shown.length+' 只':'') : '没有匹配的内容';
    renderPagination(total);
  }
  $$('.filter').forEach(b => {const active=b.dataset.filter===state.filter;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});
  const status = $('#search-status');
  status.hidden = !state.query;
  status.replaceChildren();
  if (state.query) {
    status.append(document.createTextNode('“'+state.query+'” · '+total+' 条结果 '));
    const clear = document.createElement('button');clear.type='button';clear.dataset.reset='';clear.textContent='清除搜索';status.append(clear);
  }
  syncUrl();
}
function resetFilters() {
  state.query='';state.filter='全部';state.format='全部';state.page=1;
  if ($('#search')) $('#search').value='';
  if ($('#format-filter')) $('#format-filter').value='全部';
  render();
}
function saveFavorite(id) {
  if (state.favorites.has(id)) state.favorites.delete(id); else state.favorites.add(id);
  try {localStorage.setItem('naiwa-favorites',JSON.stringify([...state.favorites]));toast(state.favorites.has(id)?'已收藏，换个分区也能找到这只奶蛙。':'已取消收藏。');}
  catch {toast('浏览器未能保存，收藏暂时只在本页有效。');}
  render();
  if (dialog.open && currentMeme?.id===id) {
    const b = $('#dialog-body [data-favorite]');
    if (b) {b.setAttribute('aria-pressed',String(state.favorites.has(id)));b.setAttribute('aria-label',(state.favorites.has(id)?'取消收藏':'收藏')+'：'+currentMeme.title);}
  } else {
    $('[data-favorite="'+id+'"]')?.focus({preventScroll:true});
  }
}
const dialog = $('#content-dialog');
let dialogRevision = 0;
function openDialog(html) {
  const revision = ++dialogRevision;
  currentMeme=null;
  $('#dialog-body').innerHTML=html;
  if (!dialog.open) dialog.showModal();
  dialog.setAttribute('aria-labelledby','dialog-title');
  document.body.classList.add('dialog-open');
  return {isCurrent:()=>dialog.open && revision===dialogRevision};
}
function closeDialog() {dialog.close();}
dialog.addEventListener('close',()=>{if(dialog.open)return;dialogRevision++;document.body.classList.remove('dialog-open');currentMeme=null;});
$('.dialog-close').addEventListener('click',closeDialog);
dialog.addEventListener('click',event=>{
  if(event.target!==dialog)return;
  const r=dialog.getBoundingClientRect();
  if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)closeDialog();
});
function openMeme(id) {
  const m=memes.find(item=>item.id===id);if(!m)return;
  openDialog('<span class="concept-tag">'+esc(m.category)+' · '+m.format+'</span><h2 id="dialog-title">'+esc(m.title)+'</h2>'+memeVisual(m,true)+'<div class="lightbox-controls"><button data-meme-step="-1" aria-label="上一张表情包">← 上一张</button>'+favoriteButton(m,'dialog-favorite')+'<button data-meme-step="1" aria-label="下一张表情包">下一张 →</button></div><div class="dialog-actions"><a class="button primary" href="'+esc(m.image)+'" download="'+esc(m.title)+'.'+m.image.split('.').pop()+'">'+icon('download')+'保存图片</a>'+(m.format==='GIF'?'<button class="button secondary" data-gif-toggle>暂停动图</button>':'<button class="button secondary" data-random>'+icon('dice')+'随机一只</button>')+'</div><p class="dialog-attribution">来源：<a href="'+esc(m.source)+'" target="_blank" rel="noopener noreferrer">'+esc(m.author)+' · 原作品 ↗</a><br>'+esc(m.license)+'。<a href="about.html#sources">查看收录说明</a></p>');
  currentMeme=m;gifPlaying=m.format==='GIF';
}
function stepMeme(delta) {
  const filteredMemes=filtered(memes);
  const scope=filteredMemes.some(m=>m.id===currentMeme?.id)?filteredMemes:memes;
  const index=scope.findIndex(m=>m.id===currentMeme?.id);
  openMeme(scope[(index+delta+scope.length)%scope.length].id);
}
dialog.addEventListener('keydown',e=>{
  if(!currentMeme)return;
  if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();stepMeme(e.key==='ArrowLeft'?-1:1);}
});
function openSoftware(id) {
  const s=software.find(item=>item.id===id);if(!s)return;
  openDialog('<span class="concept-tag">'+esc(s.type)+' · '+esc(s.platform)+'</span><h2 id="dialog-title">'+esc(s.name)+'</h2><p class="dialog-intro">'+esc(s.desc)+'</p><ul class="concept-list">'+s.features.map(f=>'<li>'+esc(f)+'</li>').join('')+'</ul><dl class="resource-details"><dt>创作者</dt><dd>'+esc(s.author)+'</dd><dt>分享说明</dt><dd>'+esc(s.license)+'</dd><dt>来源核对</dt><dd>'+s.checkedAt+'</dd></dl><p class="form-note">本站提供原页入口，未安装或验证运行这些第三方软件。功能和平台要求以作者最新说明为准。</p><a class="button primary" href="'+esc(s.url)+'" target="_blank" rel="noopener noreferrer">'+(s.id==='naiwa-camera'?'前往作者在线体验':'查看作者项目与说明')+icon('external')+'</a>'+(s.source&&s.source!==s.url?'<p class="dialog-attribution"><a href="'+esc(s.source)+'" target="_blank" rel="noopener noreferrer">作者演示与发布说明 ↗</a></p>':''));
}
function openSubmit(initialType) { openSubmission({openDialog,toast,initialType}); }

document.addEventListener('click',event=>{
  const t=event.target.closest('button,a');if(!t)return;
  if('meme' in t.dataset)openMeme(t.dataset.meme);
  if('favorite' in t.dataset)saveFavorite(t.dataset.favorite);
  if('random' in t.dataset){const choices=filtered(memes);const pool=choices.length?choices:memes;openMeme(pool[Math.floor(Math.random()*pool.length)]?.id);}
  if('memeStep' in t.dataset)stepMeme(Number(t.dataset.memeStep));
  if('gifToggle' in t.dataset && currentMeme){gifPlaying=!gifPlaying;$('.dialog-meme img').src=gifPlaying?currentMeme.image:gifPoster(currentMeme);$('.dialog-meme .gif-label').textContent=gifPlaying?'GIF · 播放中':'GIF · 已暂停';t.textContent=gifPlaying?'暂停动图':'播放动图';}
  if('submit' in t.dataset)openSubmit(t.dataset.submit==='links'?'links':undefined);
  if('sponsor' in t.dataset)openSponsorship({openDialog});
  if('software' in t.dataset)openSoftware(t.dataset.software);
  if('close' in t.dataset)closeDialog();
  if('filter' in t.dataset){state.filter=t.dataset.filter;state.page=1;render();}
  if('reset' in t.dataset)resetFilters();
  if('search' in t.dataset){state.query=t.dataset.search;$('#search').value=state.query;state.filter='全部';state.page=1;render();$('#memes')?.scrollIntoView({behavior:scrollBehavior()});}
  if('page' in t.dataset){state.page=Number(t.dataset.page);render();$('.catalog')?.scrollIntoView({behavior:scrollBehavior()});}
});
$('#search-form')?.addEventListener('submit',e=>{e.preventDefault();state.query=$('#search').value.trim();state.page=1;render();if(page==='home')$('#memes').scrollIntoView({behavior:scrollBehavior()});});
$('#search')?.addEventListener('input',()=>{state.query=$('#search').value.trim();state.page=1;render();});
$('#format-filter')?.addEventListener('change',e=>{state.format=e.target.value;state.page=1;render();});
$('.menu-button').addEventListener('click',()=>{const open=$('#main-nav').classList.toggle('open');$('.menu-button').setAttribute('aria-expanded',String(open));$('.menu-button').setAttribute('aria-label',open?'收起导航':'展开导航');});
$('#main-nav').addEventListener('click',e=>{if(e.target.closest('a,button')){$('#main-nav').classList.remove('open');$('.menu-button').setAttribute('aria-expanded','false');}});
$('.back-top').addEventListener('click',()=>window.scrollTo({top:0,behavior:scrollBehavior()}));
window.addEventListener('scroll',()=>{$('.back-top').hidden=window.scrollY<500;},{passive:true});
window.addEventListener('storage',e=>{
  if(e.key!=='naiwa-favorites')return;
  try{const ids=JSON.parse(e.newValue||'[]');state.favorites=new Set(Array.isArray(ids)?ids:[]);render();}catch{}
});
if($('#search'))$('#search').value=state.query;
if($('#format-filter'))$('#format-filter').value=state.format;
const loading = document.createElement('div');
loading.className='catalog-status wrap'; loading.setAttribute('role','status');
document.querySelector('main').prepend(loading);
async function loadCatalog() {
  loading.innerHTML='<span>奶蛙正在集合…</span>'; loading.hidden=false;
  try {
    const data=await api('/api/catalog');
    memes.splice(0,memes.length,...data.memes); videos.splice(0,videos.length,...data.videos); software.splice(0,software.length,...data.software);
    links.splice(0,links.length,...(data.links||[]));
    const categories=['全部',...new Set(catalog.map(item=>item.category)),...(page==='home'||page==='memes'?['收藏']:[])];
    if(!categories.includes(state.filter))state.filter='全部';
    const filters=$('.filter-row');
    if(filters) filters.innerHTML=categories.map(label=>'<button class="filter" data-filter="'+esc(label)+'" aria-pressed="false">'+esc(label==='全部'?(page==='links'?'全部友站':'全部奶蛙'):label==='收藏'?'我的收藏':label)+'</button>').join('');
    const counts={memes:memes.length,videos:videos.length,software:software.length,links:links.length};
    const feature=$('[data-featured-video]');
    if(feature){
      feature.hidden=!videos.length;
      if(videos.length){const video=videos[0];feature.href=video.url;$('img',feature).src=video.image;$('img',feature).alt=video.title+'封面';$('strong',feature).textContent=video.title;$('small',feature).textContent=video.author+' · '+video.platform;}
    }
    $$('[data-count]').forEach(el=>el.textContent=counts[el.dataset.count]);
    $$('[data-updated]').forEach(el=>el.textContent='收录更新于 '+new Date(data.updatedAt).toLocaleDateString('zh-CN'));
    render(); loading.hidden=true;
  } catch(error) {
    loading.innerHTML='<span>'+esc(error.message)+'</span><button class="button secondary" type="button" id="retry-catalog">重新加载</button>';
    $('#retry-catalog').addEventListener('click',loadCatalog);
  }
}
loadCatalog();
