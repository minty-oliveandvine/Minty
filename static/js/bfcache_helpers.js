// Lightweight BFCache / history.state helpers for instant restore on Back/Forward

const BFCache = (function(){
  const STORAGE_PREFIX = 'bf_'; // sessionStorage fallback prefix

  function safeJsonParse(s){ try { return JSON.parse(s); } catch(e){ return null; } }

  function mergeHistoryState(obj){
    try {
      const next = Object.assign({}, history.state || {}, obj);
      history.replaceState(next, document.title);
    } catch(e){ /* ignore */ }
  }

  function saveSnapshot(key, data){
    try {
      const snapshot = { v: 1, ts: Date.now(), data: data };
      mergeHistoryState({ [key]: snapshot });
      try { sessionStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(snapshot)); } catch(e){ /* ignore */ }
    } catch(e){}
  }

  function saveButtonState(button){
    try {
      if (!button) return;
      const btn = (button.tagName === 'BUTTON') ? button : (button.closest ? button.closest('button') : null);
      if (!btn) return;
      if (!btn.dataset.originalText) btn.dataset.originalText = btn.innerHTML;
      // also save a marker in history state indicating button swap happened
      mergeHistoryState({ __btn_states: (Object.assign({}, history.state && history.state.__btn_states || {}, { [location.pathname]: true })) });
    } catch(e){}
  }

  function restoreUIAndData(opts = {}){
    try {
      const keys = opts.keys || [];
      // hide global loading overlays
      document.querySelectorAll('#loadingOverlay, #publishLoadingOverlay').forEach(el => el?.classList?.add('hidden'));

      // restore buttons that saved originalText
      document.querySelectorAll('button[data-original-text]').forEach(btn => {
        try { btn.disabled = false; btn.innerHTML = btn.dataset.originalText; } catch(e){}
      });
      // restore any disabled buttons or buttons showing a spinner/"Saving..." state
      document.querySelectorAll('button[disabled]').forEach(btn => {
        try { if (btn.dataset && btn.dataset.originalText) btn.innerHTML = btn.dataset.originalText; btn.disabled = false; } catch(e){}
      });
      // Some buttons may have been mutated to show spinner but not be disabled or lack dataset; detect by content
      document.querySelectorAll('button').forEach(btn => {
        try {
          const hasSpinner = !!btn.querySelector && btn.querySelector('.animate-spin');
          const text = btn.textContent || '';
          const showsSaving = /saving\.{0,3}/i.test(text);
          if ((hasSpinner || showsSaving) && btn.dataset && btn.dataset.originalText) {
            btn.innerHTML = btn.dataset.originalText;
            btn.disabled = false;
          } else if (hasSpinner || showsSaving) {
            // best-effort fallback: replace with a sensible default label
            btn.disabled = false;
            if (btn.dataset && btn.dataset.originalText) btn.innerHTML = btn.dataset.originalText;
            else {
              // try to remove spinner elements only
              const spinner = btn.querySelector && btn.querySelector('.animate-spin');
              if (spinner) spinner.remove();
              // remove excessive whitespace and 'Saving' text
              btn.innerHTML = (btn.textContent || '').replace(/Saving\.{0,3}/i, '').trim() || 'Save & Next';
            }
          }
        } catch(e){}
      });

      const state = history.state || {};
      keys.forEach(key => {
        try {
          let snap = state[key];
          if (!snap) {
            const raw = sessionStorage.getItem(STORAGE_PREFIX + key);
            snap = safeJsonParse(raw);
          }
          if (snap && snap.data) {
            if (key === 'pending_expenses') {
              if (window.expenses && Array.isArray(snap.data)) {
                window.expenses = snap.data.slice();
                if (typeof window.renderExpenses === 'function') window.renderExpenses();
                if (typeof window.updateTotalExpense === 'function') window.updateTotalExpense();
              }
            }
            if (key === 'pending_sales') {
              if (window.calculateTotals && (typeof window.calculateTotals === 'function')) {
                // we saved form inputs; trigger calculateTotals to refresh UI
                try { window.calculateTotals(); } catch(e){}
              }
            }
            try { sessionStorage.removeItem(STORAGE_PREFIX + key); } catch(e){}
            try { mergeHistoryState({ [key]: null }); } catch(e){}
          }
        } catch(e){}
      });

      if (opts.sync) {
        Object.keys(opts.sync).forEach(k => {
          const url = opts.sync[k];
          if (!url) return;
          fetch(url, { cache: 'no-store', credentials: 'same-origin' }).then(resp => {
            if (!resp.ok) return null;
            return resp.json().catch(()=>null);
          }).then(data => {
            if (!data) return;
            if (opts.onSync && typeof opts.onSync === 'function') opts.onSync(k, data);
          }).catch(()=>{/* ignore */});
        });
      }
    } catch(e){
      console.warn('BFCache restore error', e);
    }
  }

  // The draft totals need the company and the day. Since 2026-10-05 the company is in the
  // page's path (/entity/<shortid>/<name>/petty-cash/reports/...), not its query, so it is taken from the
  // form's hidden entity_id field and added to whatever query the page has.
  function draftTotalsUrl(){
    var params = new URLSearchParams(location.search);
    var field = document.querySelector('input[name="entity_id"]');
    if (!params.get('entity_id') && field && field.value) params.set('entity_id', field.value);
    var query = params.toString();
    return '/api/get_draft_totals' + (query ? '?' + query : '');
  }

  window.addEventListener('pageshow', function(event){
    restoreUIAndData({
      keys: ['pending_expenses','pending_sales','pending_opening','pending_deposit','pending_cash_count','pending_ending'],
      sync: {
        pending_expenses: window.location.pathname.includes('/expense') ? draftTotalsUrl() : null,
        pending_sales: window.location.pathname.includes('/sale') ? draftTotalsUrl() : null
      },
      onSync: function(key, data){
        try {
          if (key === 'pending_expenses') {
            window.updateTotalExpenseAfterDeletion?.() || window.updateTotalExpense?.();
          }
          if (key === 'pending_sales') {
            window.calculateTotals?.();
          }
        } catch(e){}
      }
    });
  });

  return { saveSnapshot, saveButtonState, restoreUIAndData };
})();
