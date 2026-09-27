// ════════════════════════════════════════════════════════════
// Language Toggle
// ════════════════════════════════════════════════════════════
(function() {
  const langBtns = document.querySelectorAll('[data-set-lang]');
  const langElems = document.querySelectorAll('[data-lang]');

  function setLang(lang) {
    langElems.forEach(el => {
      if (el.dataset.lang === lang) {
        el.classList.add('lang-active');
      } else {
        el.classList.remove('lang-active');
      }
    });
    langBtns.forEach(btn => {
      btn.classList.toggle('active', btn.dataset.setLang === lang);
    });
    document.documentElement.lang = lang;
  }

  // Init: default ES
  setLang('es');

  langBtns.forEach(btn => {
    btn.addEventListener('click', () => setLang(btn.dataset.setLang));
  });
})();

// ════════════════════════════════════════════════════════════
// Industry Switcher
// ════════════════════════════════════════════════════════════
(function() {
  const tabs = document.querySelectorAll('.industry-tab');
  const panes = document.querySelectorAll('.industry-pane');

  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const target = tab.dataset.tab;

      // Activate all tabs with same data-tab (ES + EN)
      tabs.forEach(t => {
        t.classList.toggle('active', t.dataset.tab === target);
      });

      // Show only the matching pane
      panes.forEach(p => {
        p.classList.toggle('active', p.dataset.pane === target);
      });
    });
  });
})();
// ════════════════════════════════════════════════════════════
// FAQ Accordion
// ════════════════════════════════════════════════════════════
(function() {
  const items = document.querySelectorAll('.faq-item');
  items.forEach(item => {
    const q = item.querySelector('.faq-q');
    if (!q) return;
    q.addEventListener('click', () => {
      item.classList.toggle('open');
    });
  });
})();

// ════════════════════════════════════════════════════════════
// Stack module detail
// The benefit line is always visible; the technical paragraph opens on
// demand. One card open at a time per group, so a column never turns
// into a wall of text while its neighbours stay short.
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
// Registration form
// Fields mirror the partner hub so both intakes stay comparable:
// full_name, email, company, message and consent, plus categories
// for suppliers only.
// ════════════════════════════════════════════════════════════
(function () {
  const COPY = {
    seller: {
      es: { title: 'Datos del cliente empresa', company: 'Ej. Empresa S.A.', message: '¿Qué productos buscas?' },
      en: { title: 'Company details',           company: 'E.g. Empresa S.A.', message: 'What products are you looking for?' },
    },
    supplier: {
      es: { title: 'Datos del proveedor', company: 'Ej. Empresa S.A.',  message: 'Cuéntanos de tu operación', categories: 'Ej. Switching, UPS, cableado…' },
      en: { title: 'Supplier details',    company: 'E.g. Empresa S.A.', message: 'Tell us about your operation', categories: 'E.g. switching, UPS, cabling…' },
    },
    carrier: {
      es: { title: 'Datos del transportista', company: 'Ej. Transportes Andes Ltda.', message: 'Tamaño de flota, zonas de cobertura…' },
      en: { title: 'Carrier details',         company: 'E.g. Transportes Andes Ltda.', message: 'Fleet size, coverage areas…' },
    },
  };
  const L = {
    es: { fullName: 'Nombre completo', email: 'Email', company: 'Empresa',
          categories: 'Categorías que produces / distribuyes', message: 'Mensaje (opcional)',
          terms: 'Acepto ser contactado por el equipo de Ventu.',
          send: 'Enviar', sending: 'Enviando…', close: 'Cerrar',
          okTitle: '¡Listo!', okBody: 'Recibimos tus datos. Te contactamos a la brevedad.',
          errFields: 'Revisa los campos marcados.', errServer: 'No pudimos guardar tus datos. Inténtalo de nuevo en un momento.' },
    en: { fullName: 'Full name', email: 'Email', company: 'Company',
          categories: 'Categories you make or distribute', message: 'Message (optional)',
          terms: 'I agree to be contacted by the Ventu team.',
          send: 'Send', sending: 'Sending…', close: 'Close',
          okTitle: 'Done', okBody: 'We have your details. We will be in touch shortly.',
          errFields: 'Check the highlighted fields.', errServer: 'We could not save your details. Please try again shortly.' },
  };

  const lang = () => (document.documentElement.lang === 'en' ? 'en' : 'es');
  let overlay = null;
  let lastFocus = null;

  function field(name, label, type, placeholder, required) {
    return `
      <label class="rf-field">
        <span class="rf-label">${label}${required ? '' : ''}</span>
        ${type === 'textarea'
          ? `<textarea name="${name}" rows="3" placeholder="${placeholder || ''}"></textarea>`
          : `<input type="${type}" name="${name}" placeholder="${placeholder || ''}" ${required ? 'required' : ''}>`}
        <span class="rf-err"></span>
      </label>`;
  }

  function build(role) {
    const g = lang();
    const c = (COPY[role] || COPY.seller)[g];
    const t = L[g];
    const el = document.createElement('div');
    el.className = 'rf-overlay';
    el.innerHTML = `
      <div class="rf-modal" role="dialog" aria-modal="true" aria-label="${c.title}">
        <button class="rf-close" type="button" aria-label="${t.close}">&times;</button>
        <div class="rf-head">${c.title}</div>
        <form class="rf-form" novalidate>
          ${field('full_name', t.fullName, 'text', g === 'en' ? 'Ana Soto' : 'Ana Soto', true)}
          ${field('email', t.email, 'email', 'ana@empresa.cl', true)}
          ${field('company', t.company_label || t.company, 'text', c.company, true)}
          ${role === 'supplier' ? field('categories', t.categories, 'text', c.categories, false) : ''}
          ${field('message', t.message, 'textarea', c.message, false)}
          <label class="rf-check">
            <input type="checkbox" name="accept">
            <span>${t.terms}</span>
          </label>
          <span class="rf-err rf-err-accept"></span>
          <input type="text" name="website" class="rf-hp" tabindex="-1" autocomplete="off" aria-hidden="true">
          <div class="rf-form-err"></div>
          <button class="btn btn-primary btn-large rf-submit" type="submit">${t.send}</button>
        </form>
        <div class="rf-ok" hidden>
          <div class="rf-ok-title">${t.okTitle}</div>
          <p>${t.okBody}</p>
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

  function open(role, source) {
    close();
    lastFocus = document.activeElement;
    overlay = build(role);
    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';

    const modal = overlay.querySelector('.rf-modal');
    const form = overlay.querySelector('.rf-form');
    const t = L[lang()];

    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    overlay.querySelector('.rf-close').addEventListener('click', close);
    document.addEventListener('keydown', function esc(e) {
      if (e.key === 'Escape') { close(); document.removeEventListener('keydown', esc); }
    });
    setTimeout(() => modal.querySelector('input[name="full_name"]').focus(), 30);

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      form.querySelectorAll('.rf-err').forEach((x) => (x.textContent = ''));
      form.querySelectorAll('.rf-field').forEach((x) => x.classList.remove('rf-invalid'));
      const box = form.querySelector('.rf-form-err');
      box.textContent = '';

      const data = Object.fromEntries(new FormData(form).entries());
      const payload = {
        role,
        full_name: data.full_name || '',
        email: data.email || '',
        company: data.company || '',
        categories: data.categories || '',
        message: data.message || '',
        website: data.website || '',
        accept: form.querySelector('input[name="accept"]').checked,
        lang: lang(),
        source: source || location.pathname,
      };

      const btn = form.querySelector('.rf-submit');
      btn.disabled = true;
      btn.textContent = t.sending;
      try {
        const r = await fetch('/api/registro', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (r.ok) {
          form.hidden = true;
          overlay.querySelector('.rf-ok').hidden = false;
          return;
        }
        const j = await r.json().catch(() => ({}));
        if (j.error === 'fields' && Array.isArray(j.fields)) {
          j.fields.forEach((name) => {
            if (name === 'accept') {
              form.querySelector('.rf-err-accept').textContent = '←';
              return;
            }
            const input = form.querySelector(`[name="${name}"]`);
            if (input) {
              input.closest('.rf-field').classList.add('rf-invalid');
              input.closest('.rf-field').querySelector('.rf-err').textContent = '·';
            }
          });
          box.textContent = t.errFields;
        } else {
          box.textContent = t.errServer;
        }
      } catch {
        box.textContent = t.errServer;
      } finally {
        btn.disabled = false;
        btn.textContent = t.send;
      }
    });
  }

  document.addEventListener('click', (e) => {
    const trigger = e.target.closest('[data-registro]');
    if (!trigger) return;
    e.preventDefault();
    open(trigger.getAttribute('data-registro'), trigger.textContent.trim().slice(0, 60));
  });
})();
