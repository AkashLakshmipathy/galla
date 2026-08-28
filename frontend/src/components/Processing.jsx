/* The ~1.7s beat before any extraction review. A mock page, three blinking
 * dots, and a line saying what is being read — in both languages, because the
 * owner reads Tamil first. */

export function Processing({ title = "Reading your bill…", titleTa = "உங்கள் பில்லைப் படிக்கிறேன்…" }) {
  return (
    <div className="flex flex-col items-center py-12 animate-rise">
      <div className="w-[110px] h-[150px] rounded-panel bg-khata-paper
                      shadow-[inset_0_0_0_1px_rgba(0,0,0,.05)] p-3.5 flex flex-col gap-2">
        {[80, 100, 65, 92, 45, 88, 70].map((width, index) => (
          <span key={index} className="h-[5px] rounded-full bg-khata-rule"
                style={{ width: `${width}%` }} />
        ))}
      </div>
      <div className="flex gap-1.5 mt-6">
        {[0, 1, 2].map((index) => (
          <span key={index} className="w-[7px] h-[7px] rounded-full bg-accent animate-blink"
                style={{ animationDelay: `${index * 0.2}s` }} />
        ))}
      </div>
      <div className="text-action font-semibold mt-4">{title}</div>
      <div className="text-meta text-text-3 mt-1">{titleTa}</div>
    </div>
  );
}
