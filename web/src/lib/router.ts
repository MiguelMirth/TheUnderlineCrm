import { useEffect, useState } from "react";

// Three routes: "/" (Gather), "/preset", and "/runs/:id" (Review). Hand-rolled on purpose.
export type Route = { name: "gather" } | { name: "preset" } | { name: "run"; runId: string } | { name: "notfound" };

export function parseRoute(pathname: string): Route {
  const clean = pathname.replace(/\/+$/, "") || "/";
  if (clean === "/") return { name: "gather" };
  if (clean === "/preset") return { name: "preset" };
  const match = /^\/runs\/([A-Za-z0-9_-]{1,40})$/.exec(clean);
  if (match) return { name: "run", runId: match[1] };
  return { name: "notfound" };
}

export function navigate(to: string): void {
  if (window.location.pathname === to) return;
  window.history.pushState({}, "", to);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function useRoute(): Route {
  const [path, setPath] = useState(() => window.location.pathname);
  useEffect(() => {
    const onChange = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onChange);
    return () => window.removeEventListener("popstate", onChange);
  }, []);
  return parseRoute(path);
}
