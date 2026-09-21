(() => {
  const visible = e => !!e && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
  const text = e => (e?.getAttribute('aria-label') || e?.textContent || '').trim();
  const buttons = () => [...document.querySelectorAll('button')].filter(visible);
  const button = label => buttons().find(e => text(e) === label);
  const sidebarOpener=()=>{
    const matches=buttons().filter(e=>/^(Open sidebar|Expand sidebar|打开侧边栏|展开侧边栏)$/.test(text(e)));
    return matches.length===1&&!matches[0].disabled&&matches[0].getAttribute('aria-disabled')!=='true'?matches[0]:null;
  };
  const changeMailboxButtons=()=>buttons().filter(e=>/^(更改|Change|Change email)$/i.test(text(e))||/^(更改|Change)$/i.test((e.textContent||'').trim()));
  const changeMailboxDialog=()=>{
    const roles=[...document.querySelectorAll('[role="dialog"],[role="alertdialog"]')].filter(visible).filter(e=>/更换邮箱地址|Change email address/i.test(e.textContent));
    const headed=[...document.querySelectorAll('h1,h2,h3')].filter(visible).filter(e=>/^(更换邮箱地址|Change email address)$/i.test(text(e))).map(e=>e.parentElement?.parentElement).filter(e=>visible(e)&&/确定要更换邮箱吗/.test(e.textContent));
    const unique=[...new Set([...roles,...headed])];return unique.length===1?unique[0]:null;
  };
  const changeConfirm=()=>{const d=changeMailboxDialog();return d?[...d.querySelectorAll('button')].filter(visible).filter(e=>/^(确定|Confirm)$/i.test(text(e))):[]};
  const inputs = () => [...document.querySelectorAll('input')].filter(visible);
  const hydrated = e => !!e && Object.keys(e).some(k => k.startsWith('__reactProps'));
  const field = name => inputs().find(e => e.name === name);
  const set = (e, value) => {
    if (!visible(e) || e.disabled) throw Error('输入框尚未就绪');
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, value);
    e.dispatchEvent(new Event('input', {bubbles: true}));
    e.dispatchEvent(new Event('change', {bubbles: true}));
  };
  const verification = () => [...document.querySelectorAll('a')].find(e => {
    if (text(e) !== 'Verify Email') return false;
    try { const u = new URL(e.href); return u.origin === 'https://arena.ai' && u.pathname === '/nextjs-api/callback/email'; }
    catch { return false; }
  });
  const read = () => {
    const headings = [...document.querySelectorAll('h1,h2,h3')].filter(visible).map(text);
    const alerts = [...document.querySelectorAll('[role="alert"],[data-sonner-toast]')].filter(visible).map(text).join(' ');
    const challenge = [...document.querySelectorAll('[role="dialog"]')].filter(visible).some(e => /Security Verification|人机身份验证|Verify you are human/i.test(e.textContent));
    const account = buttons().map(text).find(t => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(t)) || '';
    const form = document.querySelector('form');
    let stage = 'loading';
    if (location.host === '10minutemail.one') stage = 'mail';
    else if (location.host === 'arena.ai') {
      if (headings.includes('Invalid Link')) stage = 'invalid';
      else if (account) stage = 'authenticated';
      else if (headings.some(t => /Verify your email address/i.test(t))) stage = 'verification';
      else if (field('confirmPassword') && hydrated(form) && visible(form)) stage = 'setPassword';
      else if (inputs().some(e => e.type === 'password') && hydrated(form)) stage = 'loginPassword';
      else if (headings.includes('Create Account')) stage = 'create';
      else if (button('Continue with email')) stage = 'email';
      else if (button('Log In')) stage = 'loggedOut';
      else if (sidebarOpener()) stage = 'expand';
    }
    const mailbox = document.querySelector('input[aria-label="Email Address"]');
    const mailRow = [...document.querySelectorAll('div')].find(e => e.textContent === 'Confirm Your Signup' && /team@everify\.arena\.ai/.test(e.parentElement.textContent));
    const changes=changeMailboxButtons();
    const confirmChange=changeConfirm();
    return {stage, account, mailbox: mailbox?.value || '', mailAvailable: !!mailRow,canChangeMailbox:changes.length===1&&!changes[0].disabled,canConfirmMailboxChange:confirmChange.length===1&&!confirmChange[0].disabled,
      verifyUrl: verification()?.href || '', path: location.origin + location.pathname,
      blocker: challenge ? '需要亲自完成人机验证' : /too many requests|rate limit|try again later/i.test(alerts) ? '网站限流，请稍后再试' : '',
      error: alerts.slice(0, 500), headings, buttons: buttons().map(text),mailChangePanels:location.host==='10minutemail.one'?[...document.querySelectorAll('h1,h2,h3')].filter(e=>/更换邮箱地址|Change email address/i.test(text(e))).map(e=>e.parentElement.parentElement.outerHTML.slice(0,4200)):[]};
  };
  const click = label => { const b = button(label); if (!b || b.disabled) throw Error('按钮尚未就绪：' + label); b.click(); };
  window.__arenaAuth = {read, act: (action, data) => {
    const v = read();
    if (v.blocker) throw Error(v.blocker);
    if (action === 'expand' || action === 'openLogin') {
      const expected = action === 'expand' ? 'expand' : 'loggedOut';
      const b = action === 'expand' ? sidebarOpener() : button('Log In');
      if (v.stage !== expected || !b || b.disabled) return {ok: true, deferred: true, stage: v.stage};
      b.click();
      return {ok: true};
    }
    if (action === 'email' && v.stage === 'email') {
      set(inputs().find(e => e.type === 'email' || e.placeholder === 'Your email'), data.email);
    } else if (action === 'submitEmail' && v.stage === 'email') click('Continue with email');
    else if (action === 'name' && v.stage === 'create') {
      const nickname = typeof data.name === 'string' ? data.name.trim() : '';
      if (!nickname || nickname.length > 40 || /[\u0000-\u001f\u007f-\u009f]/.test(data.name)) throw Error('请先设置有效的注册昵称');
      set(inputs().find(e => !e.disabled && e.type === 'text'), nickname);
    } else if (action === 'create' && v.stage === 'create') click('Create Account');
    else if (action === 'password' && (v.stage === 'setPassword' || v.stage === 'loginPassword')) {
      inputs().filter(e => e.type === 'password').forEach(e => set(e, data.password));
    } else if (action === 'submitPassword' && (v.stage === 'setPassword' || v.stage === 'loginPassword')) {
      const form = document.querySelector('form');
      if (!hydrated(form) || !visible(form)) throw Error('密码表单尚未完成初始化');
      form.addEventListener('submit', e => e.preventDefault(), {once: true});
      const b = [...form.querySelectorAll('button[type="submit"]')].find(visible);
      if (!b || b.disabled) throw Error('提交按钮尚未就绪'); b.click();
    } else if (action === 'openMail' && v.stage === 'mail') {
      const row = [...document.querySelectorAll('div')].find(e => e.textContent === 'Confirm Your Signup' && /team@everify\.arena\.ai/.test(e.parentElement.textContent));
      if (!row) throw Error('确认邮件尚未收到'); row.click();
    } else if (action === 'refreshMail' && v.stage === 'mail') {
      const matches=changeMailboxButtons();
      if(matches.length!==1||matches[0].disabled)throw Error('更改邮箱按钮尚未就绪');matches[0].click();
    } else if(action==='confirmRefreshMail'&&v.stage==='mail') {
      const matches=changeConfirm();if(matches.length!==1||matches[0].disabled)throw Error('更换邮箱确认按钮尚未就绪');matches[0].click();
    } else if (action === 'extendMail' && v.stage === 'mail') click('再延长10分钟');
    else throw Error('当前页面不支持此操作：' + action + '（页面阶段：' + v.stage + '）');
    return {ok: true};
  }};
})();
