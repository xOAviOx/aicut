import { useState } from "react";
import { useStore, headEdl } from "../store";

function OneClickButtons() {
  const oneClick = useStore((s) => s.oneClick);
  const busy = useStore((s) => s.busy);
  const project = useStore((s) => s.project);
  const edl = headEdl(project);
  const captionsOn = edl?.captions.enabled ?? false;
  const aspect = edl?.aspect ?? "source";

  const Btn = ({
    onClick,
    active,
    children,
    title,
  }: {
    onClick: () => void;
    active?: boolean;
    children: React.ReactNode;
    title?: string;
  }) => (
    <button
      onClick={onClick}
      disabled={busy}
      title={title}
      className={`rounded-full border px-3 py-1 text-xs transition disabled:opacity-50 ${
        active
          ? "border-accent/60 bg-accent/15 text-accent"
          : "border-ink-600 text-parchment-300 hover:border-accent/60 hover:text-parchment-100"
      }`}
    >
      {children}
    </button>
  );

  return (
    <div className="flex flex-wrap gap-1.5">
      <Btn onClick={() => oneClick("remove_silences")} title="Deterministic — no AI">
        Remove silences
      </Btn>
      <Btn onClick={() => oneClick("remove_fillers")} title="Deterministic — no AI">
        Remove fillers
      </Btn>
      <Btn
        onClick={() => oneClick("tighten")}
        title="Cap every pause — punchier than removing silences (no AI)"
      >
        Tighten
      </Btn>
      <Btn
        onClick={() => oneClick("remove_retakes")}
        title="Drop repeated attempts, keep the last take (no AI)"
      >
        Remove retakes
      </Btn>
      <Btn
        onClick={() => oneClick("highlights")}
        title="Auto-short: keep only the strongest moments (no AI)"
      >
        Highlights
      </Btn>
      <Btn
        onClick={() => oneClick(captionsOn ? "captions_off" : "captions_on")}
        active={captionsOn}
      >
        Captions {captionsOn ? "on" : "off"}
      </Btn>
      <Btn
        onClick={() => oneClick(aspect === "9:16" ? "aspect_source" : "aspect_916")}
        active={aspect === "9:16"}
      >
        9:16
      </Btn>
    </div>
  );
}

export default function CommandBar() {
  const command = useStore((s) => s.command);
  const pending = useStore((s) => s.commandPending);
  const error = useStore((s) => s.commandError);
  const dismiss = useStore((s) => s.dismissCommandError);
  const last = useStore((s) => s.lastCommand);
  const [text, setText] = useState("");

  const submit = () => {
    if (!text.trim() || pending) return;
    command(text);
    setText("");
  };

  return (
    <div className="border-t border-ink-700/60 bg-ink-850/70 p-3">
      <OneClickButtons />

      {last && !error && (
        <div className="mt-2 rounded-md border border-ink-700/60 bg-ink-800 px-3 py-1.5">
          <div className="font-ui text-xs text-parchment-200">{last.summary}</div>
          {last.notes && (
            <div className="mt-0.5 font-reading text-[11px] italic text-parchment-500">
              {last.notes}
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="mt-2 flex items-start justify-between gap-2 rounded-md border border-redact/50 bg-redact/10 px-3 py-1.5">
          <span className="text-xs text-parchment-200">{error}</span>
          <button onClick={dismiss} className="text-parchment-500 hover:text-parchment-100">
            ✕
          </button>
        </div>
      )}

      <div className="mt-2 flex items-center gap-2">
        <div className={`relative flex-1 ${pending ? "animate-shimmer bg-[linear-gradient(90deg,transparent,rgba(217,164,65,0.10),transparent)] bg-[length:200%_100%]" : ""} rounded-md`}>
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            disabled={pending}
            placeholder={
              pending ? "Thinking…" : "Tell the editor what to do — e.g. “cut silences and filler words”"
            }
            className="w-full rounded-md border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-parchment-100 outline-none transition placeholder:text-parchment-600 focus:border-accent disabled:opacity-70"
          />
        </div>
        <button
          onClick={submit}
          disabled={pending || !text.trim()}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-ink-900 transition hover:bg-accent-glow disabled:opacity-40"
        >
          {pending ? "…" : "Run"}
        </button>
      </div>
    </div>
  );
}
