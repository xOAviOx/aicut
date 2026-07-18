// Imperative handle to the single <video> element, so transcript clicks and
// keyboard shortcuts can seek/play without prop-drilling or re-renders.

import { clock } from "./clock";

class PlayerController {
  el: HTMLVideoElement | null = null;

  attach(el: HTMLVideoElement | null) {
    this.el = el;
  }

  seek(t: number) {
    if (!this.el) return;
    const dur = this.el.duration || clock.duration || 0;
    this.el.currentTime = Math.max(0, Math.min(t, dur > 0 ? dur : t));
    clock.set(this.el.currentTime);
  }

  play() {
    this.el?.play().catch(() => {});
  }

  pause() {
    this.el?.pause();
  }

  toggle() {
    if (!this.el) return;
    if (this.el.paused) this.play();
    else this.pause();
  }

  nudge(delta: number) {
    if (!this.el) return;
    this.seek(this.el.currentTime + delta);
  }

  get paused() {
    return this.el?.paused ?? true;
  }
}

export const player = new PlayerController();
