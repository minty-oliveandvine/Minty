'use client';

// Slide-in navigation drawer mirroring Module 2 (payment-request) NavMenu —
// same design, Material Symbols icons, and Inter font. Items are visual
// placeholders for the onboarding flow (they close the drawer, no navigation).
import { useEffect, useId, useState } from 'react';
import { createPortal } from 'react-dom';

// Inter to match Module 2's typeface (the app default is Plus Jakarta Sans).
const INTER_STACK =
  "Inter, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";

const SECTIONS = [
  {
    title: 'Petty Cash',
    items: [
      { label: 'Dashboard', icon: 'space_dashboard' },
      { label: 'Reports', icon: 'bar_chart' },
    ],
  },
  {
    title: 'Payment Request',
    items: [{ label: 'Bills', icon: 'local_atm' }],
  },
];

export default function NavMenu({ companyName = 'Minty', companyAbbreviation, showFullMenu = false }) {
  const [open, setOpen] = useState(false);
  const [portalReady, setPortalReady] = useState(false);
  const panelId = useId();

  const handleLogout = () => {
    setOpen(false);
    const base = (process.env.NEXT_PUBLIC_MODULE1_API_URL || 'http://localhost:5001').replace(/\/$/, '');
    window.location.href = `${base}/logout`;
  };

  const abbr = !showFullMenu
    ? '---'
    : companyAbbreviation ||
      (companyName || 'Minty')
        .trim()
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 3)
        .map((w) => w[0])
        .join('')
        .toUpperCase() ||
      '---';

  useEffect(() => setPortalReady(true), []);

  useEffect(() => {
    if (!open) return;
    // Keep the page scrollable (scrollbar stays visible) while the menu is open.
    const onKey = (e) => {
      if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  const itemClass =
    'flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-base font-medium text-primary transition-colors hover:bg-primary/10';

  const drawer = (
    <div
      className={`fixed inset-0 z-[200] overflow-x-hidden ${open ? 'pointer-events-auto' : 'pointer-events-none'}`}
      style={{ fontFamily: INTER_STACK }}
      aria-hidden={!open}
    >
      <button
        type="button"
        className={`absolute inset-0 cursor-pointer bg-black/40 transition-opacity duration-300 ease-out ${open ? 'opacity-100' : 'opacity-0'}`}
        onClick={() => setOpen(false)}
        tabIndex={open ? 0 : -1}
        aria-label="Close menu"
      />
      <nav
        id={panelId}
        className={`absolute right-0 top-0 flex h-full w-[min(100%,14rem)] max-w-[calc(100%-env(safe-area-inset-left)-env(safe-area-inset-right))] flex-col bg-white pt-[env(safe-area-inset-top,0px)] shadow-xl transition-transform duration-300 ease-out ${open ? 'translate-x-0' : 'translate-x-full'}`}
        aria-label="Main navigation"
      >
        <div className="flex flex-col gap-3 border-b border-primary/20 px-4 py-3 sm:px-6 sm:py-4">
          <div className="flex min-w-0 items-center justify-between gap-3">
            <span className="min-w-0 truncate text-sm font-semibold tracking-wide text-primary sm:text-base" title={abbr}>
              {abbr}
            </span>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="inline-flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-md text-primary transition-colors hover:bg-primary/10"
              aria-label="Close menu"
            >
              <span className="material-symbols-outlined text-[26px] leading-none">close</span>
            </button>
          </div>
          {showFullMenu && (
            <button type="button" onClick={() => setOpen(false)} className={itemClass}>
              <span className="material-symbols-outlined shrink-0 text-[22px] leading-none text-primary" aria-hidden>
                corporate_fare
              </span>
              Select entity
            </button>
          )}
        </div>

        <div className="flex min-h-0 flex-1 flex-col px-4 py-3 sm:px-6 sm:py-4">
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            {showFullMenu && (
            <div className="w-full flex-none overflow-y-auto overscroll-contain">
              <div className="flex flex-col gap-3">
                {SECTIONS.map((section) => (
                  <div
                    key={section.title}
                    className={`flex flex-col ${section.title === 'Payment Request' ? 'mt-6 gap-3' : 'gap-1'}`}
                    role="group"
                    aria-label={section.title}
                  >
                    <p className="px-3 text-[11px] font-semibold uppercase tracking-wider text-primary/70">{section.title}</p>
                    <ul className="flex flex-col gap-1">
                      {section.items.map((item) => (
                        <li key={item.label} className="w-full">
                          <button type="button" onClick={() => setOpen(false)} className={itemClass}>
                            <span className="material-symbols-outlined shrink-0 text-[22px] leading-none text-primary" aria-hidden>
                              {item.icon}
                            </span>
                            {item.label}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
            )}

            <div className={`-mx-4 shrink-0 sm:-mx-6 ${showFullMenu ? 'mt-4 border-t border-primary/15' : ''}`} role="presentation">
              <div className="flex flex-col gap-1 px-4 pt-4 sm:px-6">
                {showFullMenu && (
                  <button type="button" onClick={() => setOpen(false)} className={itemClass}>
                    <span className="material-symbols-outlined shrink-0 text-[22px] leading-none text-primary" aria-hidden>
                      settings
                    </span>
                    Settings
                  </button>
                )}
                <button type="button" onClick={handleLogout} className={itemClass}>
                  <span className="material-symbols-outlined shrink-0 text-[22px] leading-none text-primary" aria-hidden>
                    logout
                  </span>
                  Logout
                </button>
              </div>
            </div>

            <div className="min-h-0 min-w-0 flex-1" aria-hidden />
            <div className="flex shrink-0 justify-center px-2 pb-[max(0.75rem,env(safe-area-inset-bottom,0px))] pt-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="/sidepanel_cat.webp"
                alt=""
                className="h-auto w-[min(100%,10rem)] select-none object-contain"
                draggable={false}
              />
            </div>
          </div>
        </div>
      </nav>
    </div>
  );

  return (
    <div className="flex shrink-0 items-center">
      <button
        type="button"
        className="icon-btn"
        onClick={() => setOpen(true)}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label="Open navigation menu"
      >
        <span className="material-symbols-outlined text-[26px] leading-none">menu</span>
      </button>
      {portalReady ? createPortal(drawer, document.body) : null}
    </div>
  );
}
