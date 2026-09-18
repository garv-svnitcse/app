import { useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";

const SESSION_TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes
const LAST_ACTIVITY_KEY = "wavygo_last_activity";

/**
 * Tracks user activity and automatically logs out after 30 minutes
 * of complete inactivity. The timer resets on any user interaction
 * (click, keypress, scroll, mouse move, touch, navigation).
 *
 * Must be used inside <AuthProvider> and <BrowserRouter>.
 */
export function useSessionTimeout() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const timerRef = useRef(null);
  const isLoggingOut = useRef(false);

  const performLogout = useCallback(async () => {
    if (isLoggingOut.current) return;
    isLoggingOut.current = true;
    localStorage.removeItem(LAST_ACTIVITY_KEY);
    await logout();
    nav("/login", {
      replace: true,
      state: { sessionExpired: true },
    });
    isLoggingOut.current = false;
  }, [logout, nav]);

  const resetTimer = useCallback(() => {
    // Only track activity for authenticated users
    if (!user || user === false) return;

    // Persist the timestamp so the timeout survives a page refresh
    localStorage.setItem(LAST_ACTIVITY_KEY, Date.now().toString());

    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(performLogout, SESSION_TIMEOUT_MS);
  }, [user, performLogout]);

  useEffect(() => {
    if (!user || user === false) return;

    // On mount, check if the stored last-activity has already expired
    const stored = parseInt(localStorage.getItem(LAST_ACTIVITY_KEY), 10);
    if (stored && Date.now() - stored >= SESSION_TIMEOUT_MS) {
      performLogout();
      return;
    }

    // Calculate remaining time from the stored timestamp
    const elapsed = stored ? Date.now() - stored : 0;
    const remaining = stored
      ? Math.max(0, SESSION_TIMEOUT_MS - elapsed)
      : SESSION_TIMEOUT_MS;

    // Persist activity timestamp if none exists yet
    if (!stored) {
      localStorage.setItem(LAST_ACTIVITY_KEY, Date.now().toString());
    }

    timerRef.current = setTimeout(performLogout, remaining);

    // Events that indicate genuine user activity
    const activityEvents = [
      "mousedown",
      "keydown",
      "scroll",
      "mousemove",
      "touchstart",
      "click",
      "wheel",
    ];

    // Throttle resetTimer so we don't spam localStorage on every mousemove
    let throttled = false;
    const throttledReset = () => {
      if (throttled) return;
      throttled = true;
      resetTimer();
      setTimeout(() => {
        throttled = false;
      }, 1000); // At most once per second
    };

    activityEvents.forEach((evt) =>
      window.addEventListener(evt, throttledReset, { passive: true })
    );

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      activityEvents.forEach((evt) =>
        window.removeEventListener(evt, throttledReset)
      );
    };
  }, [user, resetTimer, performLogout]);
}

export default useSessionTimeout;
