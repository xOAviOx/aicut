import { useEffect } from "react";
import { useStore } from "../store";
import { player } from "../lib/player";

// Global editor shortcuts (spec §6.7). Ignored while typing in a field.
export function useKeyboard() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) return;

      const s = useStore.getState();
      const mod = e.ctrlKey || e.metaKey;

      if (mod && (e.key === "z" || e.key === "Z")) {
        e.preventDefault();
        if (e.shiftKey) s.redo();
        else s.undo();
        return;
      }
      if (mod && (e.key === "y" || e.key === "Y")) {
        e.preventDefault();
        s.redo();
        return;
      }

      switch (e.key) {
        case " ":
          e.preventDefault();
          player.toggle();
          break;
        case "Delete":
        case "Backspace":
          if (s.selection.length) {
            e.preventDefault();
            s.cutSelection();
          }
          break;
        case "ArrowLeft":
          e.preventDefault();
          player.nudge(-1);
          break;
        case "ArrowRight":
          e.preventDefault();
          player.nudge(1);
          break;
        case "e":
        case "E":
          s.togglePreviewMode();
          break;
        case "?":
          window.dispatchEvent(new CustomEvent("aicut:help"));
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
