import type { ReactNode } from "react";
import AppShell from "./AppShell";
import { useEmbedMode } from "../embed";

/** Skip site chrome in Django admin iframes (`?embed=1`). */
export default function PageChrome({ children }: { children: ReactNode }) {
  const urlEmbed = useEmbedMode();
  if (urlEmbed) return <div className="cs embed-root">{children}</div>;
  return <AppShell>{children}</AppShell>;
}
