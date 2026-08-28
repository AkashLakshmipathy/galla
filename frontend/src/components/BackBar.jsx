import { useNavigate } from "react-router-dom";

export function BackBar({ title, sub, action }) {
  const navigate = useNavigate();
  return (
    <div className="sticky top-[52px] z-20 bg-bg/95 backdrop-blur">
      <div className="flex items-center gap-2 px-gutter h-[46px]">
        <button onClick={() => navigate(-1)}
                className="text-accent text-action font-semibold -ml-1 pr-2 min-h-[44px]
                           flex items-center gap-1">
          <span className="text-[18px] leading-none">‹</span> Back
        </button>
        <div className="flex-1 text-center min-w-0">
          <div className="text-body font-semibold truncate">{title}</div>
          {sub && <div className="text-micro text-text-3 truncate -mt-0.5">{sub}</div>}
        </div>
        <div className="min-w-[52px] flex justify-end">{action}</div>
      </div>
    </div>
  );
}
