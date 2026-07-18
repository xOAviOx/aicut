// A tiny playback clock that lives OUTSIDE React state.
//
// The <video> drives an rAF loop that pushes currentTime here; interested views
// (active-word highlight, timeline playhead, the numeric readout) subscribe
// imperatively and update the DOM directly. This is the mechanism that keeps a
// 5k-word transcript from re-rendering on every frame (spec §6.2).

type Listener = (t: number) => void;

class PlaybackClock {
  time = 0;
  duration = 0;
  private listeners = new Set<Listener>();

  set(t: number) {
    this.time = t;
    for (const l of this.listeners) l(t);
  }

  subscribe(l: Listener): () => void {
    this.listeners.add(l);
    l(this.time);
    return () => this.listeners.delete(l);
  }
}

export const clock = new PlaybackClock();
