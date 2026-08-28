import { useRef, useState } from "react";

/* An incoming order, as it arrived: who sent it, the waveform, the Tamil the
 * contractor actually spoke, and an English gloss underneath. The audio is real
 * when there is a recording; the capsule stays as a still waveform when the
 * order came in as text. */

function initials(name = "") {
  return name.split(/\s+/).map((part) => part[0]).slice(0, 2).join("").toUpperCase();
}

export function VoiceBubble({ name, tier, source, mediaPath, transcript, gloss }) {
  const audioRef = useRef(null);
  const [playing, setPlaying] = useState(false);

  const toggle = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) {
      audio.pause();
    } else {
      audio.play().catch(() => setPlaying(false));
    }
  };

  const channel = { voice: "via WhatsApp voice note", photo: "via WhatsApp photo",
                    text: "via WhatsApp" }[source] ?? "via WhatsApp";

  return (
    <div className="p-cardpad">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-full bg-fill-2 flex items-center justify-center
                        text-row font-semibold text-text-2 shrink-0">
          {initials(name) || "?"}
        </div>
        <div className="min-w-0">
          <div className="text-body font-semibold truncate">{name}</div>
          <div className="text-meta text-text-3 truncate capitalize">
            {tier ? `${tier} · ` : ""}{channel}
          </div>
        </div>
      </div>

      <div className="mt-3.5 flex items-center gap-3 bg-bg rounded-full px-2.5 py-2">
        <button
          onClick={toggle}
          disabled={!mediaPath}
          aria-label={playing ? "Pause voice note" : "Play voice note"}
          className="w-[34px] h-[34px] rounded-full bg-accent text-white shrink-0
                     flex items-center justify-center disabled:bg-chevron"
        >
          <span className="text-[13px] leading-none">{playing ? "❚❚" : "▶"}</span>
        </button>
        <div className="flex-1 flex items-center gap-[3px] h-[26px]">
          {Array.from({ length: 34 }).map((_, index) => (
            <span
              key={index}
              className="flex-1 bg-chevron rounded-full"
              style={{
                height: `${28 + Math.abs(Math.sin(index * 1.7)) * 60}%`,
                animation: playing ? `wv .9s ease-in-out ${index * 0.04}s infinite` : "none",
              }}
            />
          ))}
        </div>
      </div>
      {mediaPath && (
        <audio ref={audioRef} src={mediaPath} preload="none"
               onPlay={() => setPlaying(true)}
               onPause={() => setPlaying(false)}
               onEnded={() => setPlaying(false)} />
      )}

      {transcript && (
        <p className="mt-3.5 text-body leading-[1.6]">{transcript}</p>
      )}
      {gloss && gloss !== transcript && (
        <p className="mt-1.5 text-meta text-text-2">{gloss}</p>
      )}
    </div>
  );
}
