import type { ActivityDetail } from "../../types/activities";

export interface ActivityViewer {
  id: number;
  can_review_collections?: boolean;
  can_change_activity?: boolean;
}

export interface ActivityPanelProps {
  a: ActivityDetail;
  setActivity: (next: ActivityDetail) => void;
  user: ActivityViewer | null | undefined;
  busy: boolean;
  setBusy: (busy: boolean) => void;
  setError: (error: string) => void;
}
