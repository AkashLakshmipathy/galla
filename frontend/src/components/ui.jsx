import { useEffect } from "react";

/* Primitives from DESIGN-TOKENS.md. Nothing here invents a colour or a radius. */

export function Card({ className = "", children, ...rest }) {
  return (
    <div className={`bg-card rounded-card ${className}`} {...rest}>
      {children}
    </div>
  );
}

/** Grouped list: one white container, rows split by a 1px separator. */
export function GroupedList({ className = "", children }) {
  return (
    <div className={`bg-card rounded-card overflow-hidden ${className}`}>
      {children}
    </div>
  );
}

export function Row({ onClick, chevron = false, className = "", children }) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag
      onClick={onClick}
      className={`w-full flex items-center gap-3 px-[18px] py-[13px] min-h-[52px]
        text-left border-b border-separator last:border-0
        ${onClick ? "active:bg-separator" : ""} ${className}`}
    >
      <div className="flex-1 min-w-0">{children}</div>
      {chevron && <Chevron />}
    </Tag>
  );
}

export function Chevron() {
  return (
    <svg width="8" height="13" viewBox="0 0 8 13" fill="none" className="shrink-0">
      <path d="M1.5 1.5 6.5 6.5 1.5 11.5" strokeWidth="2" strokeLinecap="round"
            strokeLinejoin="round" className="stroke-chevron" />
    </svg>
  );
}

/** Fat pill button. Primary is 54px black; there is one per screen. */
export function FatPill({ variant = "primary", className = "", children, ...rest }) {
  const styles = {
    primary: "h-[54px] bg-ink text-white text-action font-semibold",
    danger: "h-[54px] bg-red text-white text-action font-semibold",
    secondary: "h-[48px] bg-fill-2 text-ink text-action font-semibold",
    tertiary: "h-[44px] text-accent text-action font-semibold",
  }[variant];
  return (
    <button
      className={`w-full rounded-full flex items-center justify-center gap-2
        disabled:bg-chevron disabled:text-white active:opacity-80
        transition-opacity ${styles} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

/** Confidence chip. Quiet when the model was sure, amber and tappable when not. */
export function ConfidenceChip({ value, corrected, edited, onClick }) {
  if (corrected || edited) {
    return (
      <span className="px-[10px] py-[4px] rounded-full text-chip font-semibold
                       bg-green-tint text-green tnum">
        {corrected ? "Corrected ✓" : "Edited ✓"}
      </span>
    );
  }
  const percent = Math.round((Number(value) || 0) * 100);
  const low = (Number(value) || 0) < 0.85;
  const Tag = low && onClick ? "button" : "span";
  return (
    <Tag
      onClick={low ? onClick : undefined}
      className={`px-[10px] py-[4px] rounded-full text-chip font-semibold tnum
        ${low ? "bg-amber-tint text-amber-deep" : "bg-bg text-text-3"}`}
    >
      {percent}%{low ? " · fix" : ""}
    </Tag>
  );
}

/** Marks something the shop has never had on file — a product not in the
 *  catalogue, or a person with no account yet. Deliberately not amber: this is
 *  not a doubt to resolve, it is a fact to notice. */
export function NewBadge({ children = "New" }) {
  return (
    <span className="px-[10px] py-[4px] rounded-full text-chip font-semibold
                     bg-accent/10 text-accent whitespace-nowrap">
      {children}
    </span>
  );
}

/** Bottom sheet: scrim, 22px top radius, grab handle, centred title. */
export function Sheet({ open, onClose, title, children, maxHeight = "86%" }) {
  useEffect(() => {
    if (!open) return undefined;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (event) => event.key === "Escape" && onClose?.();
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center">
      <div className="absolute inset-0 bg-[rgba(17,17,19,.35)] animate-fade"
           onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        style={{ maxHeight }}
        className="relative w-full max-w-[430px] bg-sheet rounded-t-sheet
                   animate-sheetin flex flex-col overflow-hidden"
      >
        <div className="pt-[10px] pb-2 flex justify-center shrink-0">
          <div className="w-9 h-1 rounded-full bg-chevron" />
        </div>
        {title && (
          <div className="px-gutter pb-3 text-center text-action font-semibold shrink-0">
            {title}
          </div>
        )}
        <div className="overflow-y-auto no-scrollbar flex-1">{children}</div>
      </div>
    </div>
  );
}

export function Toast({ message }) {
  if (!message) return null;
  return (
    <div className="fixed left-0 right-0 bottom-[92px] z-[60] px-gutter animate-rise
                    pointer-events-none">
      <div className="mx-auto max-w-[430px] bg-green-tint text-green text-row
                      font-semibold text-center rounded-card py-3 px-4">
        {message}
      </div>
    </div>
  );
}

export function OfflineBanner() {
  return (
    <div className="flex items-center justify-center gap-2 bg-fill-2 text-text-2
                    text-meta font-semibold py-2 rounded-full mx-gutter">
      <span className="w-[6px] h-[6px] rounded-full bg-text-3" />
      Offline — saved locally, will sync
    </div>
  );
}

/** First-run empty state (S1). Invites the first action, in both languages. */
export function EmptyState({ icon, title, titleTa, body, action, actionLabel,
                             secondary, secondaryLabel }) {
  return (
    <Card className="p-11 text-center animate-rise">
      <div className="w-[52px] h-[52px] rounded-full bg-bg mx-auto mb-4
                      flex items-center justify-center text-[24px]">
        {icon}
      </div>
      <div className="text-supplier font-bold">{title}</div>
      {titleTa && <div className="text-body text-text-2 mt-1">{titleTa}</div>}
      <p className="text-row text-text-2 mt-2 mx-auto max-w-[240px]">{body}</p>
      {action && (
        <div className="mt-5 space-y-1.5">
          <FatPill onClick={action}>{actionLabel}</FatPill>
          {secondary && (
            <FatPill variant="tertiary" onClick={secondary}>{secondaryLabel}</FatPill>
          )}
        </div>
      )}
    </Card>
  );
}

export function SectionLabel({ children, className = "" }) {
  return (
    <div className={`text-meta font-semibold text-text-3 uppercase tracking-wide
                     px-1 mb-2 ${className}`}>
      {children}
    </div>
  );
}
