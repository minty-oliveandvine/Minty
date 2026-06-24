'use client';

// Themed dropdown — replaces native <select> for unified styling.
// `searchable` turns the field itself into a type-to-filter combobox
// (like Module 1 create-entity: type in the field, suggestions filter below).
import { useState, useRef, useEffect, useMemo } from 'react';

export default function MintySelect({ value, onChange, options, placeholder = 'Select an option', disabled = false, searchable = false, onCreate = null, createNoun = 'contact' }) {
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
  // null = not typing (show the selected value); a string = the live search text.
  const [query, setQuery] = useState(null);
  // Inline "new contact" panel: null = closed; a string = the pre-filled name.
  const [creating, setCreating] = useState(null);
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState('');
  const rootRef = useRef(null);
  const menuRef = useRef(null);
  const inputRef = useRef(null);
  const createRef = useRef(null);

  const filtered = useMemo(() => {
    if (!searchable || query === null || query.trim() === '') return options;
    const q = query.trim().toLowerCase();
    return options.filter((o) => o.toLowerCase().includes(q));
  }, [searchable, query, options]);

  // The typed-but-not-yet-a-contact name. Show the "+ Add '<name>'" row whenever
  // a create handler exists, the user has typed something, and it isn't already
  // an exact (case-insensitive) match of an existing option.
  const typed = (query || '').trim();
  const exactMatch = typed !== '' && options.some((o) => o.toLowerCase() === typed.toLowerCase());
  const canCreate = !!onCreate && searchable && typed !== '' && !exactMatch;

  const close = () => {
    setOpen(false);
    setQuery(null);
    setCreating(null);
    setCreateError('');
  };
  const choose = (opt) => {
    onChange(opt);
    close();
  };

  // Open the inline new-contact panel with the typed name pre-filled.
  const startCreate = (name) => {
    setCreateError('');
    setCreating(name);
    requestAnimationFrame(() => createRef.current && createRef.current.focus());
  };
  const cancelCreate = () => {
    setCreating(null);
    setCreateError('');
    inputRef.current && inputRef.current.focus();
  };
  const submitCreate = async () => {
    const name = (creating || '').trim();
    if (!name || createBusy) return;
    setCreateError('');
    setCreateBusy(true);
    const result = await onCreate(name);
    setCreateBusy(false);
    if (!result?.ok) {
      setCreateError(result?.error || `Failed to create ${createNoun}. Please try again.`);
      return;
    }
    // Select the freshly created option (label) and close everything.
    onChange(result.option ? result.option.label : name);
    close();
  };

  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) close();
    };
    const onKey = (e) => {
      // While the inline new-contact panel is open, its own input owns the keys.
      if (creating !== null) return;
      if (e.key === 'Escape') {
        close();
        return;
      }
      // The "+ Add '<name>'" row, when shown, is a virtual item at filtered.length.
      const maxIdx = filtered.length - 1 + (canCreate ? 1 : 0);
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActiveIdx((i) => Math.min(maxIdx, i + 1));
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActiveIdx((i) => Math.max(0, i - 1));
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        if (canCreate && activeIdx === filtered.length) startCreate(typed);
        else if (activeIdx >= 0 && filtered[activeIdx] !== undefined) choose(filtered[activeIdx]);
      }
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, activeIdx, filtered, canCreate, creating, typed]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (open) setActiveIdx(Math.max(0, filtered.indexOf(value)));
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const display = value || placeholder;
  const hasValue = !!value;

  return (
    <div className={'mselect' + (open ? ' open' : '') + (disabled ? ' disabled' : '')} ref={rootRef}>
      {searchable ? (
        <div
          className="mselect-trigger"
          onClick={() => {
            if (disabled) return;
            setOpen(true);
            inputRef.current && inputRef.current.focus();
          }}
        >
          <input
            ref={inputRef}
            type="text"
            className={'mselect-input' + (hasValue || query !== null ? '' : ' placeholder')}
            value={query === null ? (value || '') : query}
            placeholder={placeholder}
            disabled={disabled}
            autoComplete="off"
            aria-haspopup="listbox"
            aria-expanded={open}
            onFocus={() => !disabled && setOpen(true)}
            onChange={(e) => {
              setQuery(e.target.value);
              setOpen(true);
              setActiveIdx(0);
            }}
          />
          <span className="mselect-caret" aria-hidden>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </span>
        </div>
      ) : (
        <button
          type="button"
          className="mselect-trigger"
          disabled={disabled}
          onClick={() => !disabled && setOpen((o) => !o)}
          aria-haspopup="listbox"
          aria-expanded={open}
        >
          <span className={'mselect-value' + (hasValue ? '' : ' placeholder')}>{display}</span>
          <span className="mselect-caret" aria-hidden>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </span>
        </button>
      )}
      {open && creating === null && (
        <div className="mselect-menu" role="listbox" ref={menuRef}>
          {filtered.length === 0 && (
            <div className="mselect-empty">{onCreate ? 'No Xero contact found' : 'No matches'}</div>
          )}
          {filtered.map((opt, i) => {
            const selected = opt === value;
            const active = i === activeIdx;
            return (
              <div
                key={`${opt}-${i}`}
                role="option"
                aria-selected={selected}
                className={'mselect-opt' + (selected ? ' selected' : '') + (active ? ' active' : '')}
                onMouseEnter={() => setActiveIdx(i)}
                onClick={() => choose(opt)}
              >
                <span className="mselect-opt-label">{opt}</span>
                {selected && (
                  <span className="mselect-opt-check" aria-hidden>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M5 12l5 5L20 7" />
                    </svg>
                  </span>
                )}
              </div>
            );
          })}
          {canCreate && (
            <div
              role="option"
              aria-selected={false}
              className={'mselect-opt mselect-create' + (activeIdx === filtered.length ? ' active' : '')}
              onMouseEnter={() => setActiveIdx(filtered.length)}
              onClick={() => startCreate(typed)}
            >
              <span className="mselect-opt-label">+ Add &lsquo;{typed}&rsquo; as a new {createNoun}</span>
            </div>
          )}
        </div>
      )}
      {open && creating !== null && (
        <div className="mselect-menu mselect-create-panel">
          <label className="mselect-create-label">New {createNoun}</label>
          <input
            ref={createRef}
            type="text"
            className="mselect-create-input"
            value={creating}
            disabled={createBusy}
            placeholder={`Enter a new ${createNoun}`}
            onChange={(e) => setCreating(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.preventDefault(); submitCreate(); }
              if (e.key === 'Escape') { e.preventDefault(); cancelCreate(); }
            }}
          />
          {createError && <div className="mselect-create-error">{createError}</div>}
          <div className="mselect-create-actions">
            <button type="button" className="mselect-create-btn ghost" onClick={cancelCreate} disabled={createBusy}>
              Cancel
            </button>
            <button type="button" className="mselect-create-btn primary" onClick={submitCreate} disabled={createBusy || !(creating || '').trim()}>
              {createBusy ? 'Creating…' : 'Create'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
