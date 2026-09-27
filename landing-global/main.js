// ════════════════════════════════════════════════════════════
// Contact form
// Writes into the same registrations table ventu.cl uses, tagged with a
// different source and role, so every inbound contact lands in one place.
// ════════════════════════════════════════════════════════════
(function () {
  const COPY = {
    investor: { title: 'Investor enquiry', company: 'Fund or firm', message: 'What would you like to see?' },
    partner:  { title: 'Partnership enquiry', company: 'Company', message: 'What are you proposing?' },
    talent:   { title: 'Work with us', company: 'Where you work today', message: 'What would you want to build here?' },
  };

  let overlay = null;
  let lastFocus = null;

  function build(role) {
    const c = COPY[role] || COPY.investor;
    const el = document.createElement('div');
    el.className = 'cf-overlay';
    el.innerHTML = `
      <div class="cf-modal" role="dialog" aria-modal="true" aria-label="${c.title}">
        <button class="cf-close" type="button" aria-label="Close">&times;</button>
        <div class="cf-head">${c.title}</div>
        <form class="cf-form" novalidate>
          <label class="cf-field">
            <span class="cf-label">Full name</span>
            <input type="text" name="full_name" placeholder="Ana Soto" required>
            <span class="cf-err"></span>
          </label>
          <label class="cf-field">
            <span class="cf-label">Email</span>
            <input type="email" name="email" placeholder="ana@fund.com" required>
            <span class="cf-err"></span>
          </label>
          <label class="cf-field">
            <span class="cf-label">${c.company}</span>
            <input type="text" name="company" placeholder="" required>
            <span class="cf-err"></span>
          </label>
          <label class="cf-field">
            <span class="cf-label">Message (optional)</span>
            <textarea name="message" rows="3" placeholder="${c.message}"></textarea>
            <span class="cf-err"></span>
          </label>
          <label class="cf-check">
            <input type="checkbox" name="accept">
            <span>I agree to be contacted by the Ventu team.</span>
          </label>
          <span class="cf-err cf-err-accept"></span>
          <input type="text" name="website" class="cf-hp" tabindex="-1" autocomplete="off" aria-hidden="true">
          <div class="cf-form-err"></div>
          <button class="btn cf-submit" type="submit">Send</button>
        </form>
        <div class="cf-ok" hidden>
          <div class="cf-ok-title">Thank you</div>
          <p>We have your details and will be in touch shortly.</p>
        </div>
      </div>`;
    return el;
  }

  function close() {
    if (!overlay) return;
    overlay.remove();
    overlay = null;
    document.body.style.overflow = '';
    if (lastFocus) lastFocus.focus();
  }

  function open(role) {
    close();
    lastFocus = document.activeElement;
    overlay = build(role);
    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';

    const form = overlay.querySelector('.cf-form');
    const first = form.querySelector('input[name="full_name"]');
    if (first) first.focus();

    overlay.querySelector('.cf-close').addEventListener('click', close);
    overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) close(); });

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = form.querySelector('.cf-submit');
      const formErr = form.querySelector('.cf-form-err');
      form.querySelectorAll('.cf-err').forEach((s) => (s.textContent = ''));
      formErr.textContent = '';

      const data = {
        role,
        full_name: form.full_name.value,
        email: form.email.value,
        company: form.company.value,
        message: form.message.value,
        website: form.website.value,
        accept: form.accept.checked,
      };

      btn.disabled = true;
      btn.textContent = 'Sending…';
      try {
        const res = await fetch('/api/contact', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data),
        });
        const out = await res.json().catch(() => ({}));
        if (res.ok && out.ok) {
          form.hidden = true;
          overlay.querySelector('.cf-ok').hidden = false;
          return;
        }
        if (res.status === 422 && Array.isArray(out.fields)) {
          out.fields.forEach((name) => {
            if (name === 'accept') {
              form.querySelector('.cf-err-accept').textContent = 'Please tick this box.';
              return;
            }
            const field = form.querySelector(`[name="${name}"]`);
            const err = field && field.parentElement.querySelector('.cf-err');
            if (err) err.textContent = 'Please check this field.';
          });
          formErr.textContent = 'Check the highlighted fields.';
        } else if (res.status === 429) {
          formErr.textContent = 'Too many attempts. Please try again shortly.';
        } else {
          formErr.textContent = 'We could not save your details. Please try again shortly.';
        }
      } catch {
        formErr.textContent = 'We could not save your details. Please try again shortly.';
      } finally {
        btn.disabled = false;
        btn.textContent = 'Send';
      }
    });
  }

  document.addEventListener('click', (e) => {
    const trigger = e.target.closest('[data-contact]');
    if (!trigger) return;
    e.preventDefault();
    open(trigger.dataset.contact);
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') close();
  });
})();

// ════════════════════════════════════════════════════════════
// Stack module detail
// Same behaviour as ventu.cl: the benefit line is always visible and the
// technical paragraph opens on demand, one card at a time per engine, so a
// column never turns into a wall of text while its neighbours stay short.
// ════════════════════════════════════════════════════════════
(function () {
  document.querySelectorAll('.stk-modcard-more').forEach(btn => {
    btn.addEventListener('click', () => {
      const card = btn.closest('.stk-modcard');
      const opening = !card.classList.contains('open');
      card.closest('.stk-modlist').querySelectorAll('.stk-modcard.open').forEach(other => {
        other.classList.remove('open');
        other.querySelector('.stk-modcard-more').setAttribute('aria-expanded', 'false');
      });
      card.classList.toggle('open', opening);
      btn.setAttribute('aria-expanded', String(opening));
    });
  });
})();

// ════════════════════════════════════════════════════════════
// Hero 10x tiles
// One tile open at a time: the hero has a job to do, and four open panels
// turn it into a section.
// ════════════════════════════════════════════════════════════
(function () {
  const items = [...document.querySelectorAll('.thesis-item')];
  items.forEach(item => {
    const btn = item.querySelector('.thesis-btn');
    if (!btn) return;
    btn.addEventListener('click', () => {
      const opening = !item.classList.contains('open');
      items.forEach(other => {
        other.classList.remove('open');
        other.querySelector('.thesis-btn').setAttribute('aria-expanded', 'false');
      });
      item.classList.toggle('open', opening);
      btn.setAttribute('aria-expanded', String(opening));
    });
  });
})();
