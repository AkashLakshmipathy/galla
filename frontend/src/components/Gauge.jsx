import { inr } from "../lib/format.js";

/* Credit exposure — the owner's "is my money safe?" glance.
 * A 180° arc, coloured by zone, with the amount seated in the arc's cavity.
 *
 * The amount is the widest thing on the screen once a shop is carrying lakhs,
 * so its size is derived from the string length rather than fixed: a gauge that
 * reads fine at ₹32,000 and collides with its own stroke at ₹12,72,800 is not a
 * gauge you can trust on camera. */

export function Gauge({ outstanding, limit, size = 208 }) {
  const percent = limit ? Math.min(100, Math.round((outstanding / limit) * 100)) : 0;
  const zone = percent > 75 ? "#D23B2E" : percent > 40 ? "#C97F0E" : "#28934E";
  const stroke = 9;
  const radius = (size - stroke) / 2;
  const length = Math.PI * radius;
  const height = size / 2 + stroke;

  const amount = inr(outstanding);
  // The cavity is ~72% of the gauge across its middle; keep the text inside it.
  const fontSize = Math.min(30, Math.max(18, (size * 0.72) / (amount.length * 0.58)));

  return (
    <div className="flex flex-col items-center">
      <div className="relative" style={{ width: size, height }}>
        <svg width={size} height={height} viewBox={`0 0 ${size} ${height}`}
             role="img" aria-label={`Credit exposure ${percent} percent`}>
          <path
            d={`M ${stroke / 2} ${height - stroke / 2}
                a ${radius} ${radius} 0 0 1 ${size - stroke} 0`}
            fill="none" stroke="#F0F0F2" strokeWidth={stroke} strokeLinecap="round"
          />
          <path
            d={`M ${stroke / 2} ${height - stroke / 2}
                a ${radius} ${radius} 0 0 1 ${size - stroke} 0`}
            fill="none" stroke={zone} strokeWidth={stroke} strokeLinecap="round"
            strokeDasharray={length}
            strokeDashoffset={length - (length * percent) / 100}
            style={{ transition: "stroke-dashoffset .6s cubic-bezier(.2,.7,.3,1)" }}
          />
        </svg>
        <div className="absolute inset-x-0 bottom-[6px] text-center">
          <div className="font-bold tnum leading-none"
               style={{ fontSize: `${fontSize}px`, letterSpacing: "-1px" }}>
            {amount}
          </div>
        </div>
      </div>
      <div className="text-meta text-text-2 mt-2 tnum">
        of {inr(limit)} · {percent}%
      </div>
    </div>
  );
}
