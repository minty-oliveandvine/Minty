'use client';

// MintyDatePicker — themed calendar dropdown matching the mint design system.
// Usage: <MintyDatePicker value={isoString} onChange={(iso) => …} placeholder="Select a date" />
import { useState, useRef, useEffect } from 'react';

const DP_MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const DP_DOW = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

function dpParse(iso) {
  if (!iso) return null;
  const [y, m, d] = iso.split('-').map(Number);
  if (!y || !m || !d) return null;
  return new Date(y, m - 1, d);
}
function dpFormat(date) {
  if (!date) return '';
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}
function dpPretty(date) {
  if (!date) return '';
  return `${String(date.getDate()).padStart(2, '0')} ${DP_MONTHS[date.getMonth()].slice(0, 3)} ${date.getFullYear()}`;
}
function dpSameDay(a, b) {
  return a && b && a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

export default function MintyDatePicker({ value, onChange, placeholder = 'Select a date', minDate }) {
  const selected = dpParse(value);
  const today = new Date();
  const isToday = dpSameDay(selected, today);
  const [open, setOpen] = useState(false);
  const [view, setView] = useState(selected || today);
  const ref = useRef(null);

  const minD = minDate ? new Date(minDate) : null;
  const isBeforeMin = (d) => minD && d < new Date(minD.getFullYear(), minD.getMonth(), minD.getDate());
  const canStepPrev = !minD || new Date(view.getFullYear(), view.getMonth(), 1) > new Date(minD.getFullYear(), minD.getMonth(), 1);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const year = view.getFullYear();
  const month = view.getMonth();
  const firstDow = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells = [];
  for (let i = 0; i < firstDow; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(new Date(year, month, d));
  while (cells.length % 7 !== 0) cells.push(null);

  const stepMonth = (dir) => {
    if (dir < 0 && !canStepPrev) return;
    setView(new Date(year, month + dir, 1));
  };
  const pick = (d) => {
    if (isBeforeMin(d)) return;
    onChange(dpFormat(d));
    setOpen(false);
  };

  return (
    <div className="mdp" ref={ref}>
      <button type="button" className={'mdp-trigger' + (open ? ' open' : '')} onClick={() => setOpen((o) => !o)}>
        <span className={'mdp-value' + (selected ? '' : ' placeholder')}>{selected ? dpPretty(selected) : placeholder}</span>
        {isToday && <span className="mdp-today-tag">Today</span>}
        <span className="mdp-cal-icon" aria-hidden>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="5" width="18" height="16" rx="3" />
            <path d="M3 9h18M8 3v4M16 3v4" />
          </svg>
        </span>
      </button>
      {open && (
        <div className="mdp-pop">
          <div className="mdp-head">
            <button type="button" className="mdp-nav" onClick={() => stepMonth(-1)} aria-label="Previous month" disabled={!canStepPrev}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M15 18l-6-6 6-6" />
              </svg>
            </button>
            <div className="mdp-title">
              {DP_MONTHS[month]} {year}
            </div>
            <button type="button" className="mdp-nav" onClick={() => stepMonth(1)} aria-label="Next month">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 6l6 6-6 6" />
              </svg>
            </button>
          </div>
          <div className="mdp-dow">
            {DP_DOW.map((d, i) => (
              <div key={i} className="mdp-dow-cell">
                {d}
              </div>
            ))}
          </div>
          <div className="mdp-grid">
            {cells.map((d, i) =>
              d === null ? (
                <div key={i} className="mdp-cell empty" />
              ) : (
                <button
                  key={i}
                  type="button"
                  className={'mdp-cell' + (dpSameDay(d, selected) ? ' selected' : '') + (dpSameDay(d, today) ? ' today' : '') + (isBeforeMin(d) ? ' disabled' : '')}
                  onClick={() => pick(d)}
                  disabled={isBeforeMin(d)}
                >
                  {d.getDate()}
                </button>
              )
            )}
          </div>
          <div className="mdp-foot">
            <button type="button" className="mdp-today-btn" onClick={() => pick(today)}>
              Today
            </button>
            {selected && (
              <button
                type="button"
                className="mdp-clear-btn"
                onClick={() => {
                  onChange('');
                  setOpen(false);
                }}
              >
                Clear
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
