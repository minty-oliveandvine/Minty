'use client';

import { useState, useEffect, useMemo, useRef } from 'react';
import Icon from './Icon';
import NavMenu from './NavMenu';
import {
  StepCreateEntity,
  StepSelectModule,
  StepConnectXero,
  StepSalesSetting,
  StepAccountCode,
  StepOthers,
  StepBills,
  StepInvite,
  StepAllSet,
} from './OnboardingSteps';

// Baked-in defaults that used to live in TWEAK_DEFAULTS (tweaks-panel removed from prod build)
const ACCENT_DEFAULTS = {
  accent: '#36c3b4',
  accentInk: '#0f7a6e',
  accentSoft: '#e6f7f4',
};

// Scoped only to the Xero OAuth round-trip: we stash progress here right
// before leaving for Xero and restore it on return. Cleared immediately after,
// so it does NOT persist across an ordinary refresh.
const XERO_RESUME_KEY = 'minty_onboarding_xero_resume';

const STORAGE_KEY = 'minty_onboarding_session';

// Session storage is keyed per entity so multiple in-progress entities don't
// clobber each other. Before an entity is created it has no id yet, so its
// draft lives under the bare global key; once `submitEntity` assigns an id,
// writes move to `minty_onboarding_session:<id>` and the bare draft is cleared.
const sessionKey = (entityId) => (entityId ? `${STORAGE_KEY}:${entityId}` : STORAGE_KEY);

// No signature verification — client-side cache invalidation only.
function readJwtClaims(token) {
  if (!token) return null;
  try {
    const part = token.split('.')[1];
    if (!part) return null;
    const padded = part.replace(/-/g, '+').replace(/_/g, '/');
    const padding = '='.repeat((4 - (padded.length % 4)) % 4);
    const payload = JSON.parse(atob(padded + padding));
    return { user_id: payload.user_id || null, exp: payload.exp || 0 };
  } catch {
    return null;
  }
}

// Backend module codes → frontend module ids (inverse of FE_TO_BACKEND_MODULE).
const BACKEND_TO_FE_MODULE = { PETTY_CASH: 'pettyCash', BILL: 'bills' };

// Derive the frontend step id to land on from a backend /state payload. The
// backend's own `current_step` is derived from a different ordering (modules →
// Xero → petty-cash → bills/invite) than the FE flow (1 Basic, 2 Module,
// 3 Invite, 4 Accounting/Xero, …), so we recompute against the FE order here
// instead of trusting it as a raw index. We resume the user on the LAST step
// they saved — the page they were on when they clicked "Save and Next" — rather
// than the step after it. So we walk the FE steps in order and return the last
// complete one. We only consider steps 1–4, because the resume payload doesn't
// carry petty-cash / bill detail, so we can't judge those later steps; never
// resume deeper than "Connect to Accounting" (4) and let per-step GETs refill.
function deriveResumeStep(s) {
  // "Saved" per step. Invite (3) is optional, so isStepComplete always passes
  // it — but for resume we only count it as saved when invites were actually
  // added, otherwise saving at Module Selection would skip the user onto Invite.
  const isSaved = (id) => {
    if (id === 3) return Array.isArray(s.invites) && s.invites.length > 0;
    return isStepComplete(id, s);
  };
  // "Add later" with no invites: the user deferred inviting but wants to return.
  // Resume on Invite (3) and don't let a later saved step (e.g. Xero) win.
  if (s.inviteDeferred && !(Array.isArray(s.invites) && s.invites.length > 0)) {
    return isStepComplete(1, s) && isStepComplete(2, s) ? 3 : isStepComplete(1, s) ? 2 : 1;
  }
  let lastSaved = 1; // Basic Info is always the entry point.
  for (const id of [1, 2, 3, 4]) {
    if (isSaved(id)) {
      lastSaved = id;
    } else if (id === 3) {
      // Invite is optional and skippable: an empty Invite doesn't end the flow,
      // so keep scanning — a later saved step (e.g. connected Xero) still wins.
      continue;
    } else {
      break; // a required step isn't saved → land on the last saved one.
    }
  }
  return lastSaved;
}

const STEPS = [
  { id: 1, label: 'Basic Information', short: 'Basic Information', tiny: 'Basic' },
  { id: 2, label: 'Select Module', short: 'Select Module', tiny: 'Module' },
  { id: 3, label: 'User Invite', short: 'User Invite', tiny: 'Invite' },
  { id: 4, label: 'Connect to Accounting System', short: 'Connect to Accounting System', tiny: 'Accounting' },
  { id: 5, label: 'Sales Setting', short: 'Sales Setting', tiny: 'Sales' },
  { id: 6, label: 'Account Code Setting', short: 'Account Code Setting', tiny: 'Account Code' },
  { id: 7, label: 'Others', short: 'Others', tiny: 'Others' },
  { id: 8, label: 'Bill Settings', short: 'Bill Settings', tiny: 'Bill' },
  { id: 9, label: 'All Set', short: 'All Set', tiny: 'All Set' },
];

// Display-only structure: collapses Sales (5) + Account Code (6) + Others (7)
// into a single "Petty Cash Settings" segment with sub-items. Petty Cash and
// Bill segments only appear when their respective modules are selected on step 2.
function getDisplaySteps(modules) {
  const hasPetty = modules.includes('pettyCash');
  const hasBills = modules.includes('bills');
  const out = [
    { label: 'Basic Information', tiny: 'Basic', ids: [1] },
    { label: 'Select Module', tiny: 'Module', ids: [2] },
    { label: 'User Invite', tiny: 'Invite', ids: [3] },
    { label: 'Connect to Accounting System', tiny: 'Accounting', ids: [4] },
  ];
  if (hasPetty) {
    out.push({
      label: 'Petty Cash Settings',
      tiny: 'Petty Cash',
      ids: [5, 6, 7],
      subs: [
        { id: 5, label: 'Sales' },
        { id: 6, label: 'Account Code' },
        { id: 7, label: 'Others' },
      ],
    });
  }
  if (hasBills) {
    out.push({ label: 'Bill Settings', tiny: 'Bill', ids: [8] });
  }
  out.push({ label: 'All Set', tiny: 'All Set', ids: [9] });
  return out.map((d, i) => ({ idx: i + 1, ...d }));
}

// Flat list of step ids that are part of the active flow given the selected modules.
function getActiveStepIds(modules) {
  const hasPetty = modules.includes('pettyCash');
  const hasBills = modules.includes('bills');
  const ids = [1, 2, 3, 4];
  if (hasPetty) ids.push(5, 6, 7);
  if (hasBills) ids.push(8);
  ids.push(9);
  return ids;
}

const initialState = () => ({
  entity: {
    name: '',
    type: 'Private Limited',
    industry: 'Retail & E-commerce',
    country: 'Hong Kong',
    currency: 'Hong Kong Dollar',
    fyStart: 'Jan',
    phone: '',
    email: '',
  },
  modules: [],
  xero: { connected: false, org: '' },
  pettyCash: {
    float: 2000,
    claimLimit: 200,
    defaultAccount: '6420 · Office Supplies',
    requireReceipt: true,
    autoReplenish: false,
    notifyCustodian: true,
    electronicMethods: [],
    deliveryMethods: [],
    expenseCodes: { all: true, selected: {} },
    pcAccount: '',
    depositAccount: '',
    directorCode: '',
    cashSalesCode: '',
    discrepancyCode: '',
    directorContact: '',
    cashSaleContact: '',
    discrepancyContact: '',
    openingDate: (() => {
      const d = new Date();
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      return `${y}-${m}-${day}`;
    })(),
  },
  bills: {
    terms: 'Net 30',
    threshold: 5000,
    flow: 'Two-step',
    glAccount: '2100 · Accounts Payable',
    ocr: true,
    partial: true,
    dedupe: true,
  },
  invites: [],
  // Set when the user clicks "Add later" on the Invite step with no invites
  // added — they advance now but want to come back to invite people. On resume
  // (and only while invites is still empty) this lands them back on Invite.
  inviteDeferred: false,
});

// Validation rules for completion gate
function isStepComplete(id, state) {
  switch (id) {
    case 1: {
      const e = state.entity;
      // Phone and email are optional — valid only if non-empty.
      const emailOk = e.email.trim() === '' || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e.email);
      const phoneDigits = e.phone.replace(/\D/g, '');
      const phoneOk = phoneDigits.length === 0 || (phoneDigits.length >= 8 && phoneDigits.length <= 11);
      return e.name.trim().length > 1 && phoneOk && emailOk;
    }
    case 2:
      return state.modules.length > 0;
    case 3:
      return true; // Invite is optional
    case 4:
      return !!(state.xero && state.xero.connected); // Accounting connection is required
    case 5: {
      const b = state.pettyCash && state.pettyCash.openingBalance;
      return b !== undefined && b !== null && String(b).trim() !== '';
    }
    case 6:
      return true;
    case 7:
      return true;
    case 8:
      return true;
    default:
      return false;
  }
}

function Stepper({ current, onClick, maxReached, displaySteps }) {
  const ref = useRef(null);
  const [hoverPettyCash, setHoverPettyCash] = useState(false);

  // (Step-entry / squish animations removed.)

  useEffect(() => {
    if (!ref.current) return;
    const check = () => {
      ref.current.querySelectorAll('.step .label').forEach((label) => {
        if (getComputedStyle(label).display === 'none') return;
        const inner = label.querySelector('.label-inner');
        if (!inner) return;
        const overflow = inner.scrollWidth - label.clientWidth;
        if (overflow > 1) {
          label.classList.add('is-overflow');
          inner.style.setProperty('--scroll-end', -overflow - 8 + 'px');
        } else {
          label.classList.remove('is-overflow');
          inner.style.removeProperty('--scroll-end');
        }
      });
    };
    check();
    const ro = new ResizeObserver(check);
    ro.observe(ref.current);
    window.addEventListener('resize', check);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', check);
    };
  }, [current, maxReached]);

  // When the number of visible steps changes, trigger a brief jello squeeze
  // on existing (non-newly-mounted) tiles to match the grid reflow.
  const prevCountRef = useRef(displaySteps.length);
  const [pulseId, setPulseId] = useState(0);
  useEffect(() => {
    if (prevCountRef.current !== displaySteps.length) {
      setPulseId((n) => n + 1);
      prevCountRef.current = displaySteps.length;
    }
  }, [displaySteps.length]);

  return (
    <div className="stepper" ref={ref} data-screen-label="Stepper" style={{ '--step-count': displaySteps.length }}>
      {displaySteps.map((d) => {
        const isActive = d.ids.includes(current);
        const isDone = d.ids.every((i) => current > i);
        const status = isDone ? 'done' : isActive ? 'active' : 'todo';
        const firstId = d.ids[0];
        const reachable = firstId <= maxReached;
        const hasSubs = !!d.subs;
        const showSubs = hasSubs && (isActive || hoverPettyCash);
        return (
          <div
            key={d.ids[0]}
            data-step-key={d.ids[0]}
            data-pulse={pulseId}
            className={'step ' + status + (reachable ? '' : ' locked') + (hasSubs ? ' has-subs' : '')}
            onClick={() => reachable && onClick(firstId)}
            onMouseEnter={() => hasSubs && setHoverPettyCash(true)}
            onMouseLeave={() => hasSubs && setHoverPettyCash(false)}
            title={reachable ? undefined : 'Complete the previous steps first'}
          >
            {(isDone || !reachable) && <span className="num">{isDone ? <Icon.Check /> : <Icon.Lock />}</span>}
            <span className="label label-full">
              <span className="label-inner">{d.label}</span>
            </span>
            <span className="label label-tiny">
              <span className="label-inner">{d.tiny}</span>
            </span>
            {hasSubs && false && (
              <div className={'substep-popover' + (showSubs ? ' open' : '')}>
                {d.subs.map((sub) => {
                  const isSubActive = current === sub.id;
                  const isSubDone = current > sub.id;
                  const subReachable = sub.id <= maxReached;
                  return (
                    <button
                      type="button"
                      key={sub.id}
                      className={'substep' + (isSubActive ? ' active' : '') + (isSubDone ? ' done' : '')}
                      onClick={(e) => {
                        e.stopPropagation();
                        subReachable && onClick(sub.id);
                      }}
                      disabled={!subReachable}
                    >
                      <span className="substep-circle">{isSubDone && <Icon.CheckSm />}</span>
                      <span className="substep-label">{sub.label}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default function OnboardingApp() {
  const [current, setCurrent] = useState(1);
  const [state, setState] = useState(initialState);
  const [maxReached, setMaxReached] = useState(1);
  // Logged-in user, passed in by Module 1 on the launch URL after entity creation
  // (e.g. /?first=Dan&last=Smith or /?name=Dan%20Smith). No backend call needed.
  const [user, setUser] = useState({ first: '', last: '', name: '' });
  // Short-lived JWT from Module 1 used to create the entity on Step 1.
  const [token, setToken] = useState('');
  // Module 2 profile handoff URL (no entity context) passed in by Module 1.
  const [profileUrl, setProfileUrl] = useState('');
  const [accountOptions, setAccountOptions] = useState({ bank: [], cashSale: [], director: [], discrepancy: [], expense: [], contacts: [], bill: [] });

  const activeIds = useMemo(() => getActiveStepIds(state.modules), [state.modules]);
  const displaySteps = useMemo(() => getDisplaySteps(state.modules), [state.modules]);

  // Helper: find the next active step id after `c`, or stay if at end.
  const nextActiveId = (c) => {
    const i = activeIds.indexOf(c);
    if (i === -1 || i === activeIds.length - 1) return c;
    return activeIds[i + 1];
  };
  const prevActiveId = (c) => {
    const i = activeIds.indexOf(c);
    if (i <= 0) return c;
    return activeIds[i - 1];
  };

  const set = (patch) => setState((prev) => ({ ...prev, ...patch }));
  const next = () => {
    if (!isStepComplete(current, state)) return;
    setCurrent((c) => {
      const n = nextActiveId(c);
      setMaxReached((m) => Math.max(m, n));
      return n;
    });
  };
  // Dev-only skip: advances without validation (will be removed at the end)
  const skip = () => {
    setCurrent((c) => {
      const n = nextActiveId(c);
      setMaxReached((m) => Math.max(m, n));
      return n;
    });
  };
  const back = () => setCurrent((c) => prevActiveId(c));
  const goto = (id) => {
    if (!activeIds.includes(id)) return;
    if (id > maxReached) return;
    // Block forward jumps from a step that isn't complete (e.g. sub-step "Account Code" from "Sales")
    if (id > current && !isStepComplete(current, state)) {
      window.dispatchEvent(new CustomEvent('onb-validation-blocked', { detail: { from: current, to: id } }));
      return;
    }
    setCurrent(id);
  };
  const restart = () => {
    setState(initialState());
    setCurrent(1);
    setMaxReached(1);
  };

  // If the user toggles a module off after reaching a step belonging to it,
  // snap back to a still-active step so we never sit on a hidden one.
  useEffect(() => {
    if (!activeIds.includes(current)) {
      // walk backwards to the closest still-active id
      let target = 1;
      for (let i = current - 1; i >= 1; i--) {
        if (activeIds.includes(i)) {
          target = i;
          break;
        }
      }
      setCurrent(target);
    }
    // Also clamp maxReached so we don't leave it pointing at a removed step
    if (!activeIds.includes(maxReached)) {
      let mt = 1;
      for (let i = maxReached; i >= 1; i--) {
        if (activeIds.includes(i)) {
          mt = i;
          break;
        }
      }
      setMaxReached(Math.max(mt, current));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeIds.join(',')]);

  // Without this gate the persist effect fires on first mount with the empty
  // initialState and overwrites the saved session before the load effect can
  // read it (effects run in declaration order, but setState calls from inside
  // them don't take effect until the next render).
  const hydratedRef = useRef(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (!hydratedRef.current) return;
    try {
      const key = sessionKey(state.entity.id);
      window.localStorage.setItem(
        key,
        JSON.stringify({ current, maxReached, state, token, profileUrl, user }),
      );
      // Once an id exists, the pre-id draft under the bare key is obsolete —
      // drop it so it can't be replayed by a later fresh load.
      if (key !== STORAGE_KEY) window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore quota / serialization errors */
    }
  }, [current, maxReached, state, token, profileUrl, user]);

  // Cold resume: rehydrate the whole wizard from the backend `entities` row
  // (status='onboarding') instead of localStorage, so resume works in a fresh
  // browser / incognito / cleared storage / another device. The backend GET
  // /api/onboarding/state is authoritative; localStorage is a cache-only
  // fallback used if the fetch fails. `resumeToken` is the fresh JWT the resume
  // redirect minted; it authorizes calls for this entity_id (membership-checked).
  const resumeFromServer = async (entityId, resumeToken) => {
    const base = (process.env.NEXT_PUBLIC_MODULE1_API_URL || 'http://localhost:5001').replace(/\/$/, '');
    let payload = null;
    try {
      const res = await fetch(
        `${base}/api/onboarding/state?entity_id=${encodeURIComponent(entityId)}`,
        { headers: { Authorization: `Bearer ${resumeToken}` } },
      );
      if (res.ok) payload = await res.json().catch(() => null);
      // 401/403/404 → fall through to localStorage fallback below.
    } catch {
      /* network error → fall back to localStorage */
    }

    if (payload && payload.entity_id) {
      const modules = (Array.isArray(payload.modules) ? payload.modules : [])
        .map((code) => BACKEND_TO_FE_MODULE[code])
        .filter(Boolean);
      // The backend /state payload doesn't carry the "Add later" deferral, so
      // recover it from this entity's own cached session. It only matters while
      // the user is still on the same device/browser, which is the normal
      // re-entry case; the server's invites list stays authoritative.
      let cachedDeferred = false;
      try {
        const cached = JSON.parse(window.localStorage.getItem(sessionKey(payload.entity_id)) || 'null');
        cachedDeferred = !!(cached && cached.state && cached.state.inviteDeferred);
      } catch {
        /* ignore corrupt storage */
      }
      // Build the FE-shaped state once so the wizard and the resume-step
      // derivation see exactly the same data (deriveResumeStep/isStepComplete
      // read the FE `state` shape, not the raw backend payload).
      let nextState;
      setState((prev) => {
        nextState = {
          ...prev,
          entity: {
            ...prev.entity,
            id: payload.entity_id,
            // Keep FE display defaults when the server omits a field.
            ...(payload.entity?.name ? { name: payload.entity.name } : {}),
            ...(payload.entity?.country ? { country: payload.entity.country } : {}),
            ...(payload.entity?.currency ? { currency: payload.entity.currency } : {}),
          },
          modules,
          xero: payload.xero?.connected
            ? { connected: true, org: payload.xero.org || prev.xero.org }
            : prev.xero,
          invites: Array.isArray(payload.invites) ? payload.invites : prev.invites,
          inviteDeferred: cachedDeferred,
        };
        return nextState;
      });
      // Land on the FE step derived from saved data — the first step whose data
      // isn't complete. We do NOT use the backend's current_step as a forward
      // floor: its index space differs and a stale/higher value would shove the
      // user past an incomplete step (the bug where resume jumped straight to
      // "Connect to Accounting"). current_step/max_reached only raise the
      // ceiling so already-reached steps stay unlocked in the stepper.
      const derived = deriveResumeStep(nextState);
      const landing = Math.max(derived, 1);
      const ceiling = Math.max(
        landing,
        Number(payload.current_step) || 0,
        Number(payload.max_reached) || 0,
      );
      setCurrent(landing);
      setMaxReached(ceiling);
      return;
    }

    // Fallback: server resume unavailable — try this entity's own cached
    // session (per-entity key). (Different/expired sessions are ignored.)
    try {
      const saved = JSON.parse(window.localStorage.getItem(sessionKey(entityId)) || 'null');
      if (saved && saved.state) {
        const sameEntity = saved.state.entity && saved.state.entity.id === entityId;
        if (sameEntity) {
          setState(saved.state);
          if (typeof saved.current === 'number' && saved.current >= 1) setCurrent(saved.current);
          if (typeof saved.maxReached === 'number' && saved.maxReached >= 1) setMaxReached(saved.maxReached);
        }
      }
    } catch {
      /* ignore corrupt storage */
    }
  };

  // Pick up the logged-in user (and optionally the new entity name) from the
  // launch URL that Module 1 opens after the entity is created. Falls back to
  // nothing if absent, so running the app standalone still works.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    try { hydrateOnce(); } finally { hydratedRef.current = true; }
    function hydrateOnce() {
    const p = new URLSearchParams(window.location.search);

    // Module 1 sends ?fresh=1 when the user clicks "+" (create new entity).
    // fresh and entity_id are mutually exclusive. Start clean: drop any saved
    // pre-id draft so we never resume the last in-progress entity. Per-entity
    // sessions (minty_onboarding_session:<id>) are left intact so other
    // in-progress entities keep their saved progress.
    const isFresh = p.get('fresh') === '1';
    if (isFresh) {
      try { window.localStorage.removeItem(STORAGE_KEY); } catch { /* ignore */ }
    }

    // Returning from the real Xero OAuth round-trip (Module 1 → Xero → here).
    // Restore the progress we stashed before leaving and land on the
    // Accounting step (3). Cleared immediately so a later refresh won't resume.
    const xeroParam = (p.get('xero') || '').trim();
    if (xeroParam) {
      let resumed = null;
      try {
        resumed = JSON.parse(window.sessionStorage.getItem(XERO_RESUME_KEY) || 'null');
      } catch {
        /* ignore corrupt storage */
      }
      try {
        window.sessionStorage.removeItem(XERO_RESUME_KEY);
      } catch {
        /* ignore */
      }
      const today = new Date().toLocaleDateString('en-GB', {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
      });
      // The Xero tenant/org name reported back by Xero (real connected entity).
      const xeroOrg = (p.get('org') || '').trim();
      if (resumed) {
        if (resumed.token) setToken(resumed.token);
        if (resumed.profileUrl) setProfileUrl(resumed.profileUrl);
        if (resumed.user) setUser(resumed.user);
        setState((prev) => ({
          ...prev,
          ...(resumed.state || {}),
          xero:
            xeroParam === 'connected'
              ? { connected: true, org: xeroOrg, lastConnected: today }
              : (resumed.state && resumed.state.xero) || prev.xero,
        }));
        setMaxReached((m) => Math.max(m, resumed.maxReached || 4, 4));
      } else if (xeroParam === 'connected') {
        setState((prev) => ({
          ...prev,
          xero: { connected: true, org: xeroOrg, lastConnected: today },
        }));
      }
      setCurrent(4);
      setMaxReached((m) => Math.max(m, 4));
      // Strip the params so an ordinary refresh doesn't re-trigger the resume.
      try {
        const url = new URL(window.location.href);
        url.searchParams.delete('xero');
        url.searchParams.delete('step');
        url.searchParams.delete('org');
        window.history.replaceState({}, '', url.pathname + url.search + url.hash);
      } catch {
        /* ignore */
      }
      return;
    }

    // Cold resume from the backend. The resume redirect carries both
    // entity_id and a fresh token. When present, the DB row is authoritative —
    // set identity from the URL synchronously, kick off the async server fetch,
    // and skip the localStorage path (resumeFromServer falls back to it on
    // failure). This is what makes resume survive empty localStorage.
    const resumeEntityId = (p.get('entity_id') || '').trim();
    const resumeUrlToken = (p.get('token') || '').trim();
    if (resumeEntityId && resumeUrlToken) {
      setToken(resumeUrlToken);
      const rFirst = (p.get('first') || '').trim();
      const rLast = (p.get('last') || '').trim();
      const rName = (p.get('name') || '').trim();
      if (rFirst || rLast || rName) {
        setUser({ first: rFirst, last: rLast, name: rName || `${rFirst} ${rLast}`.trim() });
      }
      const rEntityName = (p.get('entity_name') || p.get('entity') || '').trim();
      if (rEntityName) {
        setState((prev) => ({ ...prev, entity: { ...prev.entity, name: rEntityName } }));
      }
      // Not awaited — the init effect stays synchronous; setters land on the
      // next render. Strip resume params so a later refresh doesn't replay.
      resumeFromServer(resumeEntityId, resumeUrlToken);
      try {
        const url = new URL(window.location.href);
        ['entity_id', 'token', 'entity_name', 'entity', 'first', 'last', 'name', 'profile_url'].forEach((k) =>
          url.searchParams.delete(k),
        );
        window.history.replaceState({}, '', url.pathname + url.search + url.hash);
      } catch {
        /* ignore */
      }
      return;
    }

    const urlToken = (p.get('token') || '').trim();
    // No URL entity_id reached here (the resume branch above returns early), so
    // this is the pre-id draft under the bare global key. On a fresh launch it
    // was just cleared, so `saved` will be null and we start clean.
    let saved = null;
    if (!isFresh) {
      try {
        saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || 'null');
      } catch {
        /* ignore corrupt storage */
      }
    }
    if (saved) {
      const savedClaims = readJwtClaims(saved.token);
      const urlClaims = readJwtClaims(urlToken);
      const now = Math.floor(Date.now() / 1000);
      const savedExpired = !!(savedClaims && savedClaims.exp && savedClaims.exp <= now);
      const differentUser = !!(urlClaims && savedClaims && urlClaims.user_id !== savedClaims.user_id);
      // A launch URL that names an entity is an explicit "onboard THIS entity"
      // intent from Module 1. If the saved blob is for a different entity, it's
      // stale (e.g. a prior abandoned session) — discard it so the new entity
      // wins instead of replaying the old id/name and 403-ing on its modules.
      const urlEntityName = (p.get('entity_name') || p.get('entity') || '').trim();
      const savedEntityName = ((saved.state && saved.state.entity && saved.state.entity.name) || '').trim();
      const differentEntity = !!(urlEntityName && savedEntityName &&
        urlEntityName.toLowerCase() !== savedEntityName.toLowerCase());
      if (savedExpired || differentUser || differentEntity) {
        try { window.localStorage.removeItem(STORAGE_KEY); } catch { /* ignore */ }
      } else {
        if (urlToken) setToken(urlToken);
        else if (saved.token) setToken(saved.token);
        if (saved.profileUrl) setProfileUrl(saved.profileUrl);
        if (saved.user) setUser(saved.user);
        if (saved.state) setState(saved.state);
        if (typeof saved.current === 'number' && saved.current >= 1) setCurrent(saved.current);
        if (typeof saved.maxReached === 'number' && saved.maxReached >= 1) {
          setMaxReached(saved.maxReached);
        }
        return;
      }
    }

    const first = (p.get('first') || '').trim();
    const last = (p.get('last') || '').trim();
    const name = (p.get('name') || '').trim();
    if (first || last || name) {
      setUser({ first, last, name: name || `${first} ${last}`.trim() });
    }
    const entityName = (p.get('entity_name') || p.get('entity') || '').trim();
    if (entityName) {
      setState((prev) => ({ ...prev, entity: { ...prev.entity, name: entityName } }));
    }
    const t = (p.get('token') || '').trim();
    if (t) setToken(t);
    const pu = (p.get('profile_url') || '').trim();
    if (pu) setProfileUrl(pu);
    }
  }, []);

  // Kick off the real Xero OAuth flow (Step 3), mirroring Module 1's
  // "Connect to Xero". Stashes progress so the round-trip returns here at the
  // Accounting step. When run standalone (no entity created), it simulates a
  // connection so the prototype still works.
  const connectXero = () => {
    const today = new Date().toLocaleDateString('en-GB', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
    });
    if (!state.entity.id) {
      set({ xero: { connected: true, org: state.entity.name || 'Olive & Vine Inc', lastConnected: today } });
      return;
    }
    try {
      window.sessionStorage.setItem(
        XERO_RESUME_KEY,
        JSON.stringify({ state, token, profileUrl, user, maxReached }),
      );
    } catch {
      /* ignore quota / serialization errors */
    }
    const base = (process.env.NEXT_PUBLIC_MODULE1_API_URL || 'http://localhost:5001').replace(/\/$/, '');
    // Pass the entity context so the backend resolves the exact entity on the
    // OAuth callback (it embeds this into the OAuth state). entity_id is the
    // preferred exact match; entity_name is the fallback. Passing neither falls
    // back to the user's latest in-progress entity — safe, but not exact.
    window.location.href =
      `${base}/xero_connect?from=onboarding` +
      `&entity_id=${encodeURIComponent(state.entity.id)}` +
      `&entity_name=${encodeURIComponent(state.entity.name || '')}`;
  };

  // Disconnect Xero from the Accounting step. The entity stays in onboarding
  // (still resumable); the backend revokes on Xero's side and clears the token.
  // When run standalone (no entity/token), just flip local state so the
  // prototype still works.
  const disconnectXero = async () => {
    if (!token || !state.entity.id) {
      set({ xero: { connected: false, org: '' } });
      return { ok: true };
    }
    const base = (process.env.NEXT_PUBLIC_MODULE1_API_URL || 'http://localhost:5001').replace(/\/$/, '');
    try {
      const res = await fetch(`${base}/api/onboarding/xero/disconnect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ entity_id: state.entity.id }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: data.error || 'Failed to disconnect from Xero. Please try again.' };
      set({ xero: { connected: false, org: '' } });
      return { ok: true };
    } catch {
      return { ok: false, error: 'Could not reach the server. Please try again.' };
    }
  };

  // Create the entity in Module 1 (Step 1). Token-authenticated; no cookies.
  // When launched standalone (no token), it no-ops so the prototype still runs.
  const submitEntity = async () => {
    if (state.entity.id) return { ok: true }; // already created (revisiting step)
    if (!token) return { ok: true }; // standalone / no Module 1 handoff
    const base = (process.env.NEXT_PUBLIC_MODULE1_API_URL || 'http://localhost:5001').replace(/\/$/, '');
    try {
      const res = await fetch(`${base}/api/onboarding/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          entity_name: state.entity.name,
          country: state.entity.country,
          currency: state.entity.currency,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: data.error || 'Failed to create entity. Please try again.' };
      if (data.entity_id) {
        setState((prev) => ({ ...prev, entity: { ...prev.entity, id: data.entity_id } }));
      }
      return { ok: true };
    } catch {
      return { ok: false, error: 'Could not reach the server. Please try again.' };
    }
  };

  const FE_TO_BACKEND_MODULE = { pettyCash: 'PETTY_CASH', bills: 'BILL' };
  const submitModule = async () => {
    if (!token || !state.entity.id) return { ok: true };
    const moduleCodes = (state.modules || [])
      .map((id) => FE_TO_BACKEND_MODULE[id])
      .filter(Boolean);
    if (moduleCodes.length === 0) return { ok: false, error: 'Pick at least one module.' };
    const base = (process.env.NEXT_PUBLIC_MODULE1_API_URL || 'http://localhost:5001').replace(/\/$/, '');
    try {
      const res = await fetch(`${base}/api/onboarding/modules`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ entity_id: state.entity.id, modules: moduleCodes }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: data.error || 'Failed to save module selection. Please try again.' };
      return { ok: true };
    } catch {
      return { ok: false, error: 'Could not reach the server. Please try again.' };
    }
  };

  const submitSalesMethods = async () => {
    if (!token || !state.entity.id) return { ok: true };
    const base = (process.env.NEXT_PUBLIC_MODULE1_API_URL || 'http://localhost:5001').replace(/\/$/, '');
    try {
      const res = await fetch(`${base}/api/onboarding/sales-methods`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          entity_id: state.entity.id,
          electronic: state.pettyCash.electronicMethods || [],
          delivery: state.pettyCash.deliveryMethods || [],
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: data.error || 'Failed to save sales methods. Please try again.' };
      return { ok: true };
    } catch {
      return { ok: false, error: 'Could not reach the server. Please try again.' };
    }
  };

  const submitOpeningBalance = async () => {
    if (!token || !state.entity.id) return { ok: true };
    const p = state.pettyCash;
    const empty = p.openingBalance === undefined || p.openingBalance === null || String(p.openingBalance).trim() === '';
    if (empty) return { ok: true };
    const base = (process.env.NEXT_PUBLIC_MODULE1_API_URL || 'http://localhost:5001').replace(/\/$/, '');
    try {
      const res = await fetch(`${base}/api/onboarding/opening-balance`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          entity_id: state.entity.id,
          opening_date: p.openingDate,
          cash_addition: p.openingBalance,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: data.error || 'Failed to save opening balance. Please try again.' };
      return { ok: true };
    } catch {
      return { ok: false, error: 'Could not reach the server. Please try again.' };
    }
  };

  const accountLoadedRef = useRef(false);
  useEffect(() => {
    if ((current !== 5 && current !== 6) || accountLoadedRef.current) return;
    if (!token || !state.entity.id) return;
    accountLoadedRef.current = true;
    const base = (process.env.NEXT_PUBLIC_MODULE1_API_URL || 'http://localhost:5001').replace(/\/$/, '');
    fetch(`${base}/api/onboarding/account-codes?entity_id=${encodeURIComponent(state.entity.id)}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!data || !data.connected) return;
        const bank = data.bank_accounts || [];
        const cashSale = data.cash_sale_accounts || [];
        const director = data.director_accounts || [];
        const discrepancy = data.discrepancy_accounts || [];
        const expense = data.expense_codes || [];
        const contacts = data.contacts || [];
        setAccountOptions({ bank, cashSale, director, discrepancy, expense, contacts });

        const md = data.mapping_defaults || {};
        const cd = data.contact_defaults || {};
        const labelFor = (list, id) => {
          const found = id ? list.find((o) => o.id === id) : null;
          return found ? found.label : '';
        };
        let expenseCodesVal;
        if (data.default_all) {
          expenseCodesVal = { all: true, selected: {} };
        } else {
          const selMap = {};
          (data.selected_codes || []).forEach((c) => {
            selMap[c] = true;
          });
          expenseCodesVal = { all: false, selected: selMap };
        }
        setState((prev) => ({
          ...prev,
          pettyCash: {
            ...prev.pettyCash,
            expenseCodes: expenseCodesVal,
            pcAccount: prev.pettyCash.pcAccount || labelFor(bank, md.pettycash),
            depositAccount: prev.pettyCash.depositAccount || labelFor(bank, md.deposit),
            directorCode: prev.pettyCash.directorCode || labelFor(director, md.director),
            cashSalesCode: prev.pettyCash.cashSalesCode || labelFor(cashSale, md.cash_sale),
            discrepancyCode: prev.pettyCash.discrepancyCode || labelFor(discrepancy, md.discrepancy),
            directorContact: prev.pettyCash.directorContact || labelFor(contacts, cd.director),
            cashSaleContact: prev.pettyCash.cashSaleContact || labelFor(contacts, cd.cash_sale),
            discrepancyContact: prev.pettyCash.discrepancyContact || labelFor(contacts, cd.discrepancy),
          },
        }));
      })
      .catch(() => {
        /* leave the step empty if the fetch fails */
      });
  }, [current, token, state.entity.id]);

  const submitAccountCodes = async () => {
    if (!token || !state.entity.id) return { ok: true };
    const base = (process.env.NEXT_PUBLIC_MODULE1_API_URL || 'http://localhost:5001').replace(/\/$/, '');
    const p = state.pettyCash;
    const idFor = (list, label) => {
      const found = label ? (list || []).find((o) => o.label === label) : null;
      return found ? found.id : '';
    };
    const mapping = {
      pettycash: idFor(accountOptions.bank, p.pcAccount),
      deposit: idFor(accountOptions.bank, p.depositAccount),
      director: idFor(accountOptions.director, p.directorCode),
      cash_sale: idFor(accountOptions.cashSale, p.cashSalesCode),
      discrepancy: idFor(accountOptions.discrepancy, p.discrepancyCode),
    };
    const allCodes = (accountOptions.expense || []).map((e) => e.code);
    const ec = p.expenseCodes || { all: true, selected: {} };
    const isAll = ec.all !== false;
    const sel = ec.selected || {};
    const selectedCodes = allCodes.filter((c) => (isAll ? sel[c] !== false : sel[c] === true));
    try {
      const res = await fetch(`${base}/api/onboarding/account-codes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ entity_id: state.entity.id, expense_codes: selectedCodes, mapping }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: data.error || 'Failed to save account codes. Please try again.' };
      return { ok: true };
    } catch {
      return { ok: false, error: 'Could not reach the server. Please try again.' };
    }
  };

  const submitContacts = async () => {
    if (!token || !state.entity.id) return { ok: true };
    const base = (process.env.NEXT_PUBLIC_MODULE1_API_URL || 'http://localhost:5001').replace(/\/$/, '');
    const p = state.pettyCash;
    const idFor = (label) => {
      const found = label ? (accountOptions.contacts || []).find((o) => o.label === label) : null;
      return found ? found.id : '';
    };
    const contacts = {
      director: idFor(p.directorContact),
      cash_sale: idFor(p.cashSaleContact),
      discrepancy: idFor(p.discrepancyContact),
    };
    try {
      const res = await fetch(`${base}/api/onboarding/contacts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ entity_id: state.entity.id, contacts }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: data.error || 'Failed to save contacts. Please try again.' };
      return { ok: true };
    } catch {
      return { ok: false, error: 'Could not reach the server. Please try again.' };
    }
  };

  // Create a brand-new Xero contact inline from the contacts step, so users
  // don't have to leave onboarding to add one. On success the returned
  // {id, label} is appended to accountOptions.contacts (no re-fetch needed) and
  // returned so the caller can select it in the relevant role dropdown.
  const createContact = async (name) => {
    const trimmed = (name || '').trim();
    if (!trimmed) return { ok: false, error: 'Enter a contact name.' };
    if (!token || !state.entity.id) {
      // Standalone / no Module 1 handoff: fake an option so the prototype works.
      const option = { id: `local-${trimmed}`, label: trimmed };
      setAccountOptions((prev) => ({ ...prev, contacts: [...(prev.contacts || []), option] }));
      return { ok: true, option };
    }
    const base = (process.env.NEXT_PUBLIC_MODULE1_API_URL || 'http://localhost:5001').replace(/\/$/, '');
    try {
      const res = await fetch(`${base}/api/onboarding/contacts/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ entity_id: state.entity.id, name: trimmed }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        // 409 means Xero isn't connected yet — surface that so the step can
        // route the user back to the Xero step.
        return {
          ok: false,
          error: data.error || 'Failed to create contact. Please try again.',
          notConnected: res.status === 409 || data.connected === false,
        };
      }
      const option = { id: data.id, label: data.label || trimmed };
      setAccountOptions((prev) => ({ ...prev, contacts: [...(prev.contacts || []), option] }));
      return { ok: true, option };
    } catch {
      return { ok: false, error: 'Could not reach the server. Please try again.' };
    }
  };

  const billLoadedRef = useRef(false);
  useEffect(() => {
    if (current !== 7 || billLoadedRef.current) return;
    if (!token || !state.entity.id) return;
    billLoadedRef.current = true;
    const base = (process.env.NEXT_PUBLIC_MODULE1_API_URL || 'http://localhost:5001').replace(/\/$/, '');
    fetch(`${base}/api/onboarding/bill-codes?entity_id=${encodeURIComponent(state.entity.id)}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!data || !data.connected) return;
        const bill = data.bill_codes || [];
        setAccountOptions((prev) => ({ ...prev, bill }));
        let billCodesVal;
        if (data.default_all) {
          billCodesVal = { all: true, selected: {} };
        } else {
          const selMap = {};
          (data.selected_codes || []).forEach((c) => {
            selMap[c] = true;
          });
          billCodesVal = { all: false, selected: selMap };
        }
        setState((prev) => ({ ...prev, bills: { ...prev.bills, billCodes: billCodesVal } }));
      })
      .catch(() => {
        /* leave the step empty if the fetch fails */
      });
  }, [current, token, state.entity.id]);

  const submitBills = async () => {
    if (!token || !state.entity.id) return { ok: true };
    const base = (process.env.NEXT_PUBLIC_MODULE1_API_URL || 'http://localhost:5001').replace(/\/$/, '');
    const allCodes = (accountOptions.bill || []).map((e) => e.code);
    const bc = state.bills.billCodes || { all: true, selected: {} };
    const isAll = bc.all !== false;
    const sel = bc.selected || {};
    const selectedCodes = allCodes.filter((c) => (isAll ? sel[c] !== false : sel[c] === true));
    try {
      const res = await fetch(`${base}/api/onboarding/bill-codes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ entity_id: state.entity.id, selected_codes: selectedCodes }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: data.error || 'Failed to save bill account codes. Please try again.' };
      return { ok: true };
    } catch {
      return { ok: false, error: 'Could not reach the server. Please try again.' };
    }
  };

  const submitInvite = async ({ email, role }) => {
    // Standalone prototype (no Module 1 handoff): keep the invite local-only.
    if (!token || !state.entity.id) return { ok: true, invitation: { email, role } };
    const base = (process.env.NEXT_PUBLIC_MODULE1_API_URL || 'http://localhost:5001').replace(/\/$/, '');
    try {
      const res = await fetch(`${base}/api/onboarding/invite`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ entity_id: state.entity.id, email, role }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: data.error || 'Failed to send invitation. Please try again.' };
      return { ok: true, invitation: data.invitation };
    } catch {
      return { ok: false, error: 'Could not reach the server. Please try again.' };
    }
  };

  const cancelInvite = async (invitationId) => {
    if (!token || !invitationId) return { ok: true };
    const base = (process.env.NEXT_PUBLIC_MODULE1_API_URL || 'http://localhost:5001').replace(/\/$/, '');
    try {
      const res = await fetch(`${base}/api/onboarding/invite/cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ invitation_id: invitationId }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: data.error || 'Failed to cancel invitation.' };
      return { ok: true };
    } catch {
      return { ok: false, error: 'Could not reach the server. Please try again.' };
    }
  };

  const invitesLoadedRef = useRef(false);
  useEffect(() => {
    if (current !== 8 || invitesLoadedRef.current) return;
    if (!token || !state.entity.id) return;
    invitesLoadedRef.current = true;
    const base = (process.env.NEXT_PUBLIC_MODULE1_API_URL || 'http://localhost:5001').replace(/\/$/, '');
    fetch(`${base}/api/onboarding/invite?entity_id=${encodeURIComponent(state.entity.id)}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!data || !Array.isArray(data.invitations)) return;
        setState((prev) => {
          // Keep any names typed this session (backend stores only email/role),
          // matching by email; fall back to email-derived initials otherwise.
          const known = {};
          (prev.invites || []).forEach((x) => {
            if (x.email) known[x.email.toLowerCase()] = x;
          });
          const invites = data.invitations.map((inv) => {
            const prior = known[(inv.email || '').toLowerCase()] || {};
            return {
              id: inv.id,
              email: inv.email,
              role: inv.role,
              first: prior.first || '',
              last: prior.last || '',
            };
          });
          return { ...prev, invites };
        });
      })
      .catch(() => {
        /* leave the list empty if the fetch fails */
      });
  }, [current, token, state.entity.id]);

  // Commits the deferred opening balance (when petty cash was the
  // selection) then redirects to the right module's landing page.
  // Bill-only users skip the opening-balance commit and go straight to
  // Module 2's Bills home via Module 1's /entity/<id>/bills handoff
  // (which mints the JWT and forwards). Returns { ok, redirect } so
  // All Set can show errors / stay put.
  const finishOnboarding = async () => {
    // Onboarding done — drop this entity's saved session (and any bare draft).
    try {
      window.localStorage.removeItem(sessionKey(state.entity.id));
      window.localStorage.removeItem(STORAGE_KEY);
    } catch { /* ignore */ }
    if (!token || !state.entity.id) return { ok: true, redirect: false };
    const chosen = state.modules[0]; // 'pettyCash' | 'bills' | undefined
    if (chosen !== 'bills') {
      const result = await submitOpeningBalance();
      if (!result?.ok) return result;
    }
    const base = (process.env.NEXT_PUBLIC_MODULE1_API_URL || 'http://localhost:5001').replace(/\/$/, '');
    // Clear the mid-onboarding flag so the entity routes to its dashboard
    // on the next entity-list click instead of bouncing back here.
    // Best-effort — even if it fails we still navigate the user out.
    try {
      await fetch(`${base}/api/onboarding/finalize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ entity_id: state.entity.id }),
      });
    } catch { /* ignore */ }
    const dest = chosen === 'bills'
      ? `${base}/entity/${state.entity.id}/bills`
      : `${base}/entity/${state.entity.id}`;
    window.location.href = dest;
    return { ok: true, redirect: true };
  };

  // Save-and-exit from any step: best-effort save of the current step's data
  // (each submitX no-ops on empty/standalone), then leave to the entity-list
  // dashboard. localStorage already persists current+state, so re-entering
  // onboarding resumes the user where they left off. A failed save does NOT
  // block the exit — we save what's valid and go.
  const saveAndExit = async (submitFn) => {
    try {
      if (typeof submitFn === 'function') await submitFn();
    } catch {
      /* best-effort — never block the exit on a save failure */
    }
    const base = (process.env.NEXT_PUBLIC_MODULE1_API_URL || 'http://localhost:5001').replace(/\/$/, '');
    window.location.href = `${base}/entity`;
  };

  const fetchExistingSalesMethods = async () => {
    if (!token || !state.entity.id) return null;
    const base = (process.env.NEXT_PUBLIC_MODULE1_API_URL || 'http://localhost:5001').replace(/\/$/, '');
    try {
      const res = await fetch(`${base}/api/onboarding/sales-methods?entity_id=${encodeURIComponent(state.entity.id)}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  };

  // Avatar initials — prefer the connected user, fall back to entity name.
  const profileInitials = (() => {
    if (user.first || user.last) {
      return ((user.first[0] || '') + (user.last[0] || '')).toUpperCase() || 'DD';
    }
    const source = user.name || state.entity.name || '';
    const fromWords = source
      .trim()
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0])
      .join('')
      .toUpperCase();
    return fromWords || 'DD';
  })();
  const profileLabel = user.name || state.entity.name || 'Your entity';

  // Apply accent CSS vars from baked-in defaults
  useEffect(() => {
    const r = document.documentElement;
    r.style.setProperty('--accent', ACCENT_DEFAULTS.accent);
    r.style.setProperty('--accent-ink', ACCENT_DEFAULTS.accentInk);
    r.style.setProperty('--accent-soft', ACCENT_DEFAULTS.accentSoft);
    r.style.setProperty('--accent-hover', ACCENT_DEFAULTS.accent);
  }, []);

  const stepProps = { state, set, next, back, skip, restart, submitEntity, submitModule, connectXero, disconnectXero, submitSalesMethods, fetchExistingSalesMethods, accountOptions, submitAccountCodes, submitContacts, createContact, submitBills, submitInvite, cancelInvite, finishOnboarding, saveAndExit };

  return (
    <>
      <div className="topbar" data-screen-label="Top bar">
        <div className="topbar-inner">
          <div className="brand">
            <img className="brand-mark-img" src="/assets/minty-logo.png" alt="Minty" />
            <span>Minty</span>
          </div>
          <h1>Getting Started</h1>
          <div className="right pl-0.5 sm:pl-2">
            <button
              type="button"
              className="avatar"
              title={profileLabel}
              aria-label="Open profile"
              onClick={() => {
                if (profileUrl) window.location.href = profileUrl;
              }}
            >
              {profileInitials}
            </button>
            {/* Nav stays Logout-only through onboarding; full menu populates on the final "All Set" step. */}
            <NavMenu companyName={state.entity.name || 'Minty'} showFullMenu={current === 9} />
          </div>
        </div>
      </div>

      <Stepper current={current} onClick={goto} maxReached={maxReached} displaySteps={displaySteps} />

      <main className="page" data-screen-label={`0${current} ${STEPS[current - 1].label}`}>
        {(current === 5 || current === 6 || current === 7) && (
          <aside className="pc-side-menu" aria-label="Petty Cash sub-steps">
            <div className="pc-side-title">Petty Cash Settings</div>
            <div className={'pc-side-item' + (current === 5 ? ' active' : '') + (current > 5 ? ' done' : '')}>
              <span className="substep-circle">{current > 5 ? <Icon.CheckSm /> : '1'}</span>
              <span className="substep-label">Sales</span>
            </div>
            <div className={'pc-side-item' + (current === 6 ? ' active' : '') + (current > 6 ? ' done' : '')}>
              <span className="substep-circle">{current > 6 ? <Icon.CheckSm /> : '2'}</span>
              <span className="substep-label">Account Code</span>
            </div>
            <div className={'pc-side-item' + (current === 7 ? ' active' : '') + (current > 7 ? ' done' : '')}>
              <span className="substep-circle">{current > 7 ? <Icon.CheckSm /> : '3'}</span>
              <span className="substep-label">Others</span>
            </div>
          </aside>
        )}
        {current === 1 && <StepCreateEntity {...stepProps} />}
        {current === 2 && <StepSelectModule {...stepProps} />}
        {current === 3 && <StepInvite {...stepProps} />}
        {current === 4 && <StepConnectXero {...stepProps} />}
        {current === 5 && <StepSalesSetting {...stepProps} />}
        {current === 6 && <StepAccountCode {...stepProps} />}
        {current === 7 && <StepOthers {...stepProps} />}
        {current === 8 && <StepBills {...stepProps} />}
        {current === 9 && <StepAllSet {...stepProps} />}
      </main>
    </>
  );
}