function $(id){return document.getElementById(id);}
function hpRole(){
  var r=$('hp-role').value;
  $('hp-ward-g').classList.toggle('step-hidden', !(r==='Ward Officer'||r==='Citizen'));
  $('hp-con-g').classList.toggle('step-hidden', r!=='Contractor');
}
var OTP_IDS=['b1','b2','b3','b4'], otpTimer=null;
function maskEmail(e){var p=e.split('@'), u=p[0];return (u.length<=2?u[0]+'•':u.slice(0,2)+'•'.repeat(Math.min(6,Math.max(2,u.length-2))))+'@'+p[1];}
function otpCode(){return OTP_IDS.map(function(id){return $(id).value;}).join('');}
function otpSync(){
  OTP_IDS.forEach(function(id){$(id).classList.toggle('filled',!!$(id).value);});
  $('hp-verify').disabled=otpCode().length!==4;
  document.querySelector('.otp-row').classList.remove('bad');
  $('hp-otp-err').textContent='';
}
function otpStartTimer(){
  var left=30, b=$('hp-resend'); clearInterval(otpTimer); b.disabled=true;
  var tick=function(){ b.textContent='Resend in 0:'+String(left).padStart(2,'0'); if(left--<=0){clearInterval(otpTimer); b.disabled=false; b.textContent='Resend code';} };
  tick(); otpTimer=setInterval(tick,1000);
}
function hpSendOTP(){
  var email=$('hp-email').value.trim(), role=$('hp-role').value, err=$('hp-err');
  if(!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)){err.textContent='Enter a valid email address.';$('hp-email').focus();return;}
  if(!role){err.textContent='Select your role to continue.';return;}
  if(role==='Ward Officer'&&!$('hp-ward').value){err.textContent='Ward Officers must pick their ward.';return;}
  if(role==='Contractor'&&!$('hp-con').value){err.textContent='Pick your company.';return;}
  err.textContent='';
  $('hp-otp-to').textContent=maskEmail(email);
  OTP_IDS.forEach(function(id){$(id).value='';}); otpSync();
  $('login-step-1').classList.add('step-hidden');
  $('login-step-2').classList.remove('step-hidden');
  otpStartTimer();
  if (!OTP_IDS.includes(document.activeElement && document.activeElement.id)) $('b1').focus();   // immediate: a delayed focus could steal fast typing / autofill
}
function hpResend(){
  OTP_IDS.forEach(function(id){$(id).value='';}); otpSync();
  $('hp-otp-err').style.color='#1d7a48'; $('hp-otp-err').textContent='A new code is on its way (demo: still 1234).';
  setTimeout(function(){$('hp-otp-err').style.color='';},2500);
  otpStartTimer(); $('b1').focus();
}
function bn(el,nextId){
  el.value=el.value.replace(/\D/g,'').slice(-1);
  otpSync();
  if(el.value&&nextId)$(nextId).focus();
  if(otpCode().length===4) hpVerify();      // auto-submit once all 4 digits are in
}
var otpBusy=false;
async function hpVerify(){
  var otp=otpCode(), err=$('hp-otp-err'), role=$('hp-role').value, btn=$('hp-verify'), row=document.querySelector('.otp-row');
  if(otp.length!==4||otpBusy) return;
  otpBusy=true; btn.disabled=true; btn.innerHTML='<span class="spin"></span>Verifying…';
  try{
    var r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      email:$('hp-email').value.trim(), role:role, otp:otp, ward:$('hp-ward').value||null, contractor_id:$('hp-con').value||null})});
    var j=await r.json();
    if(!r.ok){
      err.textContent=r.status===400&&/OTP/i.test(j.detail||'')?'That code isn’t right. Check it and try again.':(j.detail||'Sign-in failed.');
      row.classList.remove('shake');void row.offsetWidth;row.classList.add('shake','bad');
      OTP_IDS.forEach(function(id){$(id).value='';$(id).classList.remove('filled');});$('b1').focus();
      return;
    }
    sessionStorage.setItem('cp_token',j.token);
  }catch(e){err.textContent='Cannot reach the RastaNidhi server. Start it with: python server.py';return;}
  finally{otpBusy=false; btn.innerHTML='Verify &amp; sign in'; btn.disabled=otpCode().length!==4;}
  row.classList.add('good'); clearInterval(otpTimer);
  setTimeout(function(){
    $('hp-welcome').textContent='Signed in as '+role+'. Your personalised dashboard is ready.';
    $('login-step-2').classList.add('step-hidden');
    $('login-step-3').classList.remove('step-hidden');
    setNav();
  },450);
}
function hpBack(){
  clearInterval(otpTimer);
  $('login-step-2').classList.add('step-hidden');
  $('login-step-1').classList.remove('step-hidden');
  OTP_IDS.forEach(function(id){$(id).value='';});
  $('hp-email').focus();
}
function setNav(){
  if(sessionStorage.getItem('cp_token')){var a=document.querySelector('.nav-cta');a.textContent='My dashboard';a.href='/dashboard';}
}
function setText(id,v){var e=$(id);if(e&&v!==undefined&&v!==null)e.textContent=v;}
(async function(){
  setNav();
  try{
    var o=await (await fetch('/api/options')).json();
    o.wards.forEach(function(w){var op=document.createElement('option');op.value=w.ward_code;op.textContent=w.ward_code+' – '+w.ward_name;$('hp-ward').appendChild(op);});
    o.contractors.forEach(function(c){var op=document.createElement('option');op.value=c.contractor_id;op.textContent=c.contractor_name;$('hp-con').appendChild(op);});
    var s=await (await fetch('/api/public/stats')).json();
    setText('st-spend',s.spend);setText('st-complaints',s.complaints);setText('st-risk',s.at_risk);setText('st-wards',s.wards);
    setText('st-wos',s.work_orders);setText('st-hot',s.hotspots);
    setText('im-risk',s.at_risk);setText('im-risk-n',s.at_risk_wos);setText('im-dlp',s.dlp_count);setText('im-dlp-amt',s.dlp_amount);
    setText('im-reopen',s.reopen_rate);setText('im-never',s.never_fixed);setText('im-issues',s.issues.toLocaleString('en-IN'));
    setText('ft-risk',s.at_risk);setText('ft-wards',s.wards);setText('ft-complaints',s.complaints);setText('im-cold',s.cold_mix_reopen);if(window.countUpStats)countUpStats();setText('im-ward',s.worst_ward);setText('im-ward-flags',s.worst_ward_flags);setText('im-ward-risk',s.worst_ward_risk);
  }catch(e){console.warn('RastaNidhi server not reachable – showing built-in numbers.');}
})();

/* ---------- motion & click feedback ---------- */
(function(){
  var reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  // scroll reveal (class added by JS, so content stays visible if JS fails)
  var groups = ['.section-tag','.section-title','.section-sub','.step','.gallery-item','.cat-card','.feat-item','.feat-img','.role-card','.impact-card','.login-left','.login-card'];
  if (!reduced && 'IntersectionObserver' in window) {
    var io = new IntersectionObserver(function(es){ es.forEach(function(e){ if(e.isIntersecting){ e.target.classList.add('in'); io.unobserve(e.target); } }); }, {threshold: .12});
    groups.forEach(function(sel){
      document.querySelectorAll('section:not(.hero) ' + sel).forEach(function(el, i){
        el.classList.add('reveal'); el.style.setProperty('--d', (i % 6) * 0.07 + 's'); io.observe(el);
      });
    });
  }
  // nav shadow once scrolled
  var onScroll = function(){ document.body.classList.toggle('scrolled', scrollY > 10); };
  addEventListener('scroll', onScroll, {passive: true}); onScroll();
  // count up the hero stats after the live numbers arrive
  window.countUpStats = function(){
    if (reduced) return;
    document.querySelectorAll('.hero-stat-num').forEach(function(el){
      var txt = el.textContent, m = txt.match(/[\d,]*\.?\d+/); if(!m) return;
      var raw = m[0], target = parseFloat(raw.replace(/,/g,'')), dec = (raw.split('.')[1]||'').length, t0 = performance.now();
      (function step(now){ var p = Math.min(1,(now-t0)/1100), e = 1-Math.pow(1-p,3);
        el.textContent = txt.replace(raw, (target*e).toLocaleString('en-IN',{minimumFractionDigits:dec,maximumFractionDigits:dec}));
        if (p<1) requestAnimationFrame(step); else el.textContent = txt; })(t0);
    });
  };
  // click ripple on buttons
  document.addEventListener('pointerdown', function(e){
    var b = e.target.closest('.btn-primary,.btn-outline,.login-submit,.nav-cta,.brand__cta'); if(!b || reduced) return;
    var r = b.getBoundingClientRect(), d = document.createElement('span');
    d.className = 'ripple-dot'; d.style.left = (e.clientX-r.left)+'px'; d.style.top = (e.clientY-r.top)+'px';
    b.appendChild(d); setTimeout(function(){ d.remove(); }, 650);
  });
  // OTP: paste a 4-digit code, backspace jumps back, Enter submits
  var boxes = ['b1','b2','b3','b4'].map($);
  boxes.forEach(function(b, i){
    b.setAttribute('inputmode','numeric');
    b.addEventListener('paste', function(e){ var t=(e.clipboardData||window.clipboardData).getData('text').replace(/\D/g,'').slice(0,4);
      if(t.length){ e.preventDefault(); t.split('').forEach(function(c,k){ boxes[k].value=c; }); boxes[Math.min(t.length,3)].focus(); otpSync(); if(t.length===4) hpVerify(); } });
    b.addEventListener('keydown', function(e){
      if(e.key==='Backspace' && !b.value && i>0){ boxes[i-1].focus(); boxes[i-1].value=''; otpSync(); }
      if(e.key==='ArrowLeft' && i>0) boxes[i-1].focus(); if(e.key==='ArrowRight' && i<3) boxes[i+1].focus();
      if(e.key==='Enter') hpVerify();
    });
  });
  $('hp-email').addEventListener('keydown', function(e){ if(e.key==='Enter') hpSendOTP(); });
})();
