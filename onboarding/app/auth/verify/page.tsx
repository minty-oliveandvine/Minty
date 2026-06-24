"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";

const INITIAL_CODE = ["4", "8", "2", "9", "1", "0"];

export default function VerifyPage() {
  const router = useRouter();
  const [digits, setDigits] = useState<string[]>(INITIAL_CODE);
  const [activeIdx, setActiveIdx] = useState(0);
  const inputsRef = useRef<Array<HTMLInputElement | null>>([]);

  const setDigit = (i: number, raw: string) => {
    const v = raw.replace(/\D/g, "").slice(-1);
    setDigits((cur) => {
      const next = [...cur];
      next[i] = v;
      return next;
    });
    if (v && i < 5) {
      inputsRef.current[i + 1]?.focus();
    }
  };

  const onKeyDown = (i: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Backspace" && !digits[i] && i > 0) {
      inputsRef.current[i - 1]?.focus();
    }
  };

  return (
    <>
      <div className="topbar" data-screen-label="Top bar">
        <div className="topbar-inner">
          <div className="brand">
            <img className="brand-mark-img" src="/assets/minty-logo.png" alt="Minty" />
            <span>Minty</span>
          </div>
          <h1></h1>
          <div className="right" />
        </div>
      </div>

      <main className="auth-page">
        <div className="auth-card">
          <div className="page-head">
            <h2>Your Verification Code</h2>
            <p>
              To complete your secure sign-in process, please use the following
              unique authentication code.
            </p>
          </div>

          <div className="otp-card">
            <div className="otp-label">ONE - TIME PASSCODE</div>
            <div className="otp-row">
              {digits.map((d, i) => (
                <input
                  key={i}
                  ref={(el) => {
                    inputsRef.current[i] = el;
                  }}
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={1}
                  className={"otp-cell" + (i === activeIdx ? " is-active" : "")}
                  value={d}
                  onChange={(e) => setDigit(i, e.target.value)}
                  onFocus={() => setActiveIdx(i)}
                  onKeyDown={(e) => onKeyDown(i, e)}
                  aria-label={`Digit ${i + 1} of 6`}
                />
              ))}
            </div>
            <div className="otp-expires">Expires 10 minutes</div>
          </div>

          <button
            type="button"
            className="btn btn-primary btn-block"
            onClick={() => router.push("/auth/confirm")}
          >
            Verify Now
          </button>

          <div className="auth-notice security-alert">
            <span className="auth-notice-icon" aria-hidden="true">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="4" y="11" width="16" height="10" rx="2" />
                <path d="M8 11V8a4 4 0 0 1 7.5-2" />
              </svg>
            </span>
            <div className="auth-notice-body">
              <div className="auth-notice-title">Security Alert</div>
              <p>
                This code was requested from a new device in Hongkong. If this
                wasn&apos;t you, please secure your account immediately.
              </p>
            </div>
          </div>
        </div>
      </main>

      <style>{`
        .auth-page {
          min-height: calc(100vh - 60px);
          padding: 24px 16px 48px;
          display: flex;
          justify-content: center;
        }
        .auth-card {
          width: 100%;
          max-width: 380px;
          display: flex;
          flex-direction: column;
          gap: 24px;
          padding-top: 24px;
        }
        .auth-card .page-head { margin-bottom: 0; }

        /* OTP card — #46D8CC at 10% opacity, monospace label + expiry */
        .otp-card {
          background: rgba(70, 216, 204, 0.1);
          border: 1px solid color-mix(in oklab, var(--accent) 18%, var(--line));
          border-radius: var(--radius);
          padding: 18px 16px;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 12px;
        }
        .otp-label {
          font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
          font-size: 13px;
          letter-spacing: 0.08em;
          color: var(--muted);
        }
        .otp-row {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        /* Extra gap between the 3rd and 4th cell — matches the
           "482  910" split in the screenshot without needing a spacer node. */
        .otp-cell:nth-child(4) { margin-left: 12px; }
        .otp-cell {
          width: 40px;
          height: 48px;
          border-radius: 8px;
          border: 1px solid var(--line-strong);
          background: var(--bg);
          color: var(--ink);
          font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
          font-size: 22px;
          font-weight: 500;
          text-align: center;
          padding: 0;
          outline: none;
          transition: border-color .15s ease, color .15s ease, box-shadow .15s ease;
        }
        .otp-cell:focus,
        .otp-cell.is-active {
          border-color: var(--accent);
          color: var(--accent);
          box-shadow: 0 0 0 3px color-mix(in oklab, var(--accent) 16%, transparent);
        }
        .otp-expires {
          font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
          font-size: 12px;
          color: var(--muted);
          margin-top: 2px;
        }

        /* Notice card — neutral by default, .security-alert variant uses
           the accent-soft tint to match the screenshot. */
        .auth-notice {
          display: flex;
          gap: 12px;
          padding: 14px 16px;
          border: 1px solid var(--line);
          border-radius: var(--radius);
          background: var(--bg);
        }
        .auth-notice.security-alert {
          background: rgba(70, 216, 204, 0.1);
          border: 0;
        }
        .auth-notice-icon {
          color: var(--accent);
          flex-shrink: 0;
          padding-top: 2px;
        }
        .auth-notice-body {
          font-size: 13px;
          line-height: 1.55;
          color: var(--ink-2);
        }
        .auth-notice-title {
          font-weight: 700;
          color: var(--ink);
          margin-bottom: 2px;
          font-size: 14px;
        }
        .auth-notice-body p {
          margin: 0;
          color: var(--muted);
        }
      `}</style>
    </>
  );
}
