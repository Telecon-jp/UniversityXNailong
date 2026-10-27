/* 奶蛙下载中心 · MILK FROG DOWNLOAD — 页面逻辑 */
(function () {
  var $ = function (id) { return document.getElementById(id); };

  /* ---------- 奶蛙宇宙导航（三页共用） ---------- */
  var UNI = [
    { href: 'https://neta.art/app/milk-frog-wiki',     label: '奶蛙百科' },
    { href: 'https://neta.art/app/milk-frog-download', label: '奶蛙下载', here: true },
    { href: 'https://neta.art/app/travel-milk-frog',   label: '旅行奶蛙' },
    { href: 'https://neta.art/app/milk-frog-museum',   label: '奶蛙博物馆' },
    { href: 'https://neta.art/app/milk-frog-pack',     label: '奶蛙卡包' },
    { href: 'https://neta.art/app/milk-frog-stamps',   label: '奶蛙集邮册' }
  ];
  if ($('uniLinks')) {
    $('uniLinks').innerHTML = UNI.map(function (u) {
      return '<a target="_top" href="' + u.href + '"' + (u.here ? ' aria-current="page"' : '') + '>' + u.label + '</a>';
    }).join('');
  }

  /* ================= 奶蛙大笑：可玩的小组件 ================= */
  var frog = $('laughFrog');
  var stage = $('laughStage');
  var status = $('laughStatus');
  var counter = $('laughCount');
  var STAGES = ['静默', '愣了一下', '嘴角抽动', '噗嗤一声', '捧腹大笑', '笑得发抖', '喘不上气', '笑晕过去了'];
  var laughs = 0, level = -1, busy = false, audio = null;

  // 用 WebAudio 合成"狂笑"音效——不依赖任何音频文件
  function ctx() {
    if (audio) return audio;
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    try { audio = new AC(); } catch (e) { return null; }
    return audio;
  }
  function laughSound(intensity) {
    var a = ctx(); if (!a) return;
    if (a.state === 'suspended') { try { a.resume(); } catch (e) {} }
    var t0 = a.currentTime;
    var n = 3 + Math.floor(intensity * 3);
    for (var i = 0; i < n; i++) {
      var t = t0 + i * (0.16 + Math.random() * 0.05);
      var o = a.createOscillator(), g = a.createGain();
      o.type = 'square';
      var base = 190 + Math.random() * 90 - i * 7;
      o.frequency.setValueAtTime(base, t);
      o.frequency.exponentialRampToValueAtTime(base * 0.62, t + 0.11);
      var vol = 0.055 + intensity * 0.035;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(vol, t + 0.012);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.13);
      o.connect(g); g.connect(a.destination);
      o.start(t); o.stop(t + 0.16);
    }
  }
  function setStage(i) {
    if (level === i) return;
    level = i;
    var cls = ['s0', 's1', 's2', 's3', 's4', 's5', 's6', 's7'];
    frog.parentNode.className = 'frog-stage ' + (cls[i] || 's0');
    if (status) status.textContent = STAGES[i] || STAGES[0];
  }
  function laugh() {
    if (busy) return;
    busy = true;
    laughs++;
    if (counter) counter.textContent = String(laughs);
    var target = 4 + Math.floor(Math.random() * 4); // 4..7
    var i = 1;
    (function step() {
      if (i > target) {
        setTimeout(function () { setStage(0); busy = false; }, 1300);
        return;
      }
      setStage(i);
      laughSound(i / 7);
      i++;
      setTimeout(step, 260 + Math.random() * 180);
    })();
  }
  if (frog) {
    frog.addEventListener('click', laugh);
    frog.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); laugh(); }
    });
  }
  if ($('laughBtn')) $('laughBtn').addEventListener('click', laugh);
  if ($('laughReset')) $('laughReset').addEventListener('click', function () {
    laughs = 0; setStage(0); if (counter) counter.textContent = '0';
    if (status) status.textContent = STAGES[0];
  });
  setStage(0);

  /* ================= 桌宠：可以拖着走 ================= */
  var pet = $('deskPet');
  if (pet) {
    var dragging = false, sx = 0, sy = 0, ox = 0, oy = 0, moved = false;
    pet.addEventListener('pointerdown', function (e) {
      dragging = true; moved = false;
      var r = pet.getBoundingClientRect();
      ox = r.left; oy = r.top;
      sx = e.clientX; sy = e.clientY;
      pet.setPointerCapture(e.pointerId);
      pet.classList.add('grab');
    });
    pet.addEventListener('pointermove', function (e) {
      if (!dragging) return;
      var dx = e.clientX - sx, dy = e.clientY - sy;
      if (Math.abs(dx) + Math.abs(dy) > 4) moved = true;
      var maxX = window.innerWidth - pet.offsetWidth - 8;
      var maxY = window.innerHeight - pet.offsetHeight - 8;
      pet.style.left = Math.max(8, Math.min(maxX, ox + dx)) + 'px';
      pet.style.top = Math.max(8, Math.min(maxY, oy + dy)) + 'px';
      pet.style.right = 'auto'; pet.style.bottom = 'auto';
      pet.style.position = 'fixed';
    });
    pet.addEventListener('pointerup', function (e) {
      dragging = false; pet.classList.remove('grab');
      try { pet.releasePointerCapture(e.pointerId); } catch (err) {}
    });
    pet.addEventListener('click', function () {
      if (moved) return;
      pet.classList.remove('hop');
      void pet.offsetWidth;
      pet.classList.add('hop');
      laughSound(0.5);
    });
    if ($('petToggle')) {
      $('petToggle').addEventListener('click', function () {
        var on = pet.style.display !== 'none';
        pet.style.display = on ? 'none' : 'block';
        $('petToggle').textContent = on ? '让奶蛙出来' : '收起奶蛙';
      });
    }
  }

  /* ================= 平台标签切换 ================= */
  var tabs = document.querySelectorAll('[data-plat]');
  Array.prototype.forEach.call(tabs, function (t) {
    t.addEventListener('click', function () {
      Array.prototype.forEach.call(tabs, function (x) { x.setAttribute('aria-pressed', String(x === t)); });
      Array.prototype.forEach.call(document.querySelectorAll('[data-plat-panel]'), function (p) {
        p.hidden = p.dataset.platPanel !== t.dataset.plat;
      });
    });
  });

  if ($('yr')) $('yr').textContent = new Date().getFullYear();
})();

/* ---------- 跳转一律升到顶层窗口 ----------
   作品跑在 iframe 里（works.cohub.live）。站内链接若留在 iframe 内跳转，
   就会变成 /app 套 /app 的多层嵌套：地址栏不动，一层层套进去。
   这里统一把跨站跳转交给顶层窗口，地址栏正常切换；
   页内锚点（#xxx）仍留在 iframe 内滚动，不受影响。
   标了 target="_top" 的链接由浏览器原生处理，这里是漏网与未来新增链接的兜底。 */
(function () {
  document.addEventListener('click', function (ev) {
    var a = ev.target && ev.target.closest ? ev.target.closest('a[href]') : null;
    if (!a) return;
    var raw = a.getAttribute('href') || '';
    if (!raw || raw.charAt(0) === '#') return;   // 页内锚点
    if (a.target === '_blank') return;            // 新窗口，不拦
    var url;
    try { url = new URL(a.href, location.href); } catch (e) { return; }
    if (!/^https?:$/.test(url.protocol)) return;  // mailto: 之类
    if (url.origin === location.origin) return;   // 同源（作品自身资源）
    ev.preventDefault();
    try { window.top.location.href = url.href; }
    catch (e) { window.open(url.href, '_blank', 'noopener'); }
  }, true);
})();
