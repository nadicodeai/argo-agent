declare global {
  interface Window {
    /** Set true by the server only for `argo dashboard --tui` (or ARGO_DASHBOARD_TUI=1). */
    __ARGO_DASHBOARD_EMBEDDED_CHAT__?: boolean;
    /** @deprecated Older injected name; treated as on when true. */
    __ARGO_DASHBOARD_TUI__?: boolean;
  }
}

/** True only when the dashboard was started with embedded TUI Chat (`argo dashboard --tui`). */
export function isDashboardEmbeddedChatEnabled(): boolean {
  if (typeof window === "undefined") return false;
  if (window.__ARGO_DASHBOARD_EMBEDDED_CHAT__ === true) return true;
  return window.__ARGO_DASHBOARD_TUI__ === true;
}
