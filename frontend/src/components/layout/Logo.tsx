export function Logo({ size = 36 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden className="shrink-0">
      <defs>
        <linearGradient id="claimai-logo" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#2885aa" />
          <stop offset="1" stopColor="#123c52" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="14" fill="url(#claimai-logo)" />
      <path
        d="M32 12 16 18v12c0 10.5 6.8 19.3 16 22 9.2-2.7 16-11.5 16-22V18z"
        fill="none"
        stroke="#fff"
        strokeWidth="4"
        strokeLinejoin="round"
      />
      <path
        d="m24.5 31.5 5.5 5.5 10-11"
        fill="none"
        stroke="#8fe3c6"
        strokeWidth="4.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
