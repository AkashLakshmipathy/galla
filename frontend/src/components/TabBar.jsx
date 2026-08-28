import { NavLink } from "react-router-dom";

const TABS = [
  { to: "/", label: "Counter", icon: "▤" },
  { to: "/approvals", label: "Approvals", icon: "✓" },
  { to: "/shop", label: "Shop", icon: "◉" },
];

export function TabBar({ badge = 0 }) {
  return (
    <nav className="fixed bottom-0 left-0 right-0 z-40 bg-card/95 backdrop-blur
                    border-t border-separator">
      <div className="mx-auto max-w-[430px] flex safe-bottom pt-2">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.to === "/"}
            className={({ isActive }) =>
              `flex-1 flex flex-col items-center gap-1 pb-1 min-h-[48px]
               ${isActive ? "text-ink" : "text-text-3"}`}
          >
            <span className="relative text-[17px] leading-none">
              {tab.icon}
              {tab.label === "Approvals" && badge > 0 && (
                <span className="absolute -top-1.5 -right-3 min-w-[16px] h-[16px] px-1
                                 rounded-full bg-red text-white text-micro font-semibold
                                 flex items-center justify-center tnum">
                  {badge}
                </span>
              )}
            </span>
            <span className="text-micro font-medium">{tab.label}</span>
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
