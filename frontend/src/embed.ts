import { useLocation } from "react-router-dom";

/** HashRouter query (`#/news/5?embed=1`) — used by Django admin iframes. */
export function useEmbedMode(): boolean {
  const { search } = useLocation();
  return new URLSearchParams(search).get("embed") === "1";
}
