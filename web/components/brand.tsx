export function BrandMark({ size = 32 }: { size?: number }) {
  return (
    <svg
      className="brand-symbol"
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
    >
      <rect width="32" height="32" rx="9" fill="currentColor" />
      <circle
        cx="16"
        cy="16"
        r="8.5"
        stroke="var(--brand-line)"
        strokeWidth="2.4"
      />
      <circle cx="23.4" cy="8.6" r="3.2" fill="var(--brand-accent)" />
    </svg>
  );
}

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <span className="brand-lockup">
      <BrandMark size={compact ? 28 : 34} />
      <span className="brand-word">
        orin<span>.</span>
      </span>
    </span>
  );
}
