import { useEffect, useRef } from "react";

/**
 * Keep a page's data fresh: calls `refresh({ background: true })` every `intervalMs` while the tab is
 * visible, and immediately when the user comes back to the tab. Background refreshes should be silent
 * (no spinners or error toasts) so the page doesn't flicker.
 */
export function useLiveRefresh(refresh, intervalMs = 60000) {
  const ref = useRef(refresh);
  ref.current = refresh;

  useEffect(() => {
    let last = Date.now();
    const run = () => {
      if (document.visibilityState !== "visible") return;
      last = Date.now();
      ref.current({ background: true });
    };
    const id = setInterval(run, intervalMs);
    // Returning to the tab refreshes at once, unless we just did.
    const onVisible = () => { if (document.visibilityState === "visible" && Date.now() - last > 5000) run(); };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
    };
  }, [intervalMs]);
}

export default useLiveRefresh;
