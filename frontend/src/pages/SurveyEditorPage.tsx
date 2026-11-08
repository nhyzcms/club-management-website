import { useCallback, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { activityApi } from "../api/activities";
import SurveyCreatorPage from "./SurveyCreatorPage";

export default function SurveyEditorPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const activityId = Number(id);
  const [canSave, setCanSave] = useState(false);
  const [crumbTitle, setCrumbTitle] = useState("");

  const load = useCallback(async () => {
    const [me, a]: [any, Awaited<ReturnType<typeof activityApi.get>>] = await Promise.all([
      api.me(),
      activityApi.get(activityId),
    ]);
    if (a.type !== "survey") {
      throw new Error("仅调研可编辑问卷。");
    }
    const uid = me.user?.id;
    const can = a.creator?.id === uid || !!me.user?.permissions?.can_change_activity;
    if (!can) {
      throw new Error("没有编辑权限。");
    }
    setCanSave(!!a.schema_editable);
    setCrumbTitle(a.title);
    return a.schema || { title: "", pages: [{ name: "page1", elements: [] }] };
  }, [activityId]);

  const save = useCallback(async (schema: Record<string, unknown>) => {
    await activityApi.update(activityId, { schema });
  }, [activityId]);

  return (
    <SurveyCreatorPage key={activityId} title="编辑问卷" load={load} save={save} canSave={canSave}>
      <nav className="breadcrumb">
        <a href="#" onClick={(e) => { e.preventDefault(); navigate("/activity"); }}>活动</a>
        <span className="sep">/</span>
        <a href="#" onClick={(e) => { e.preventDefault(); navigate(`/activity/${activityId}`); }}>{crumbTitle || "调研"}</a>
        <span className="sep">/</span>
        <span>编辑问卷</span>
      </nav>
    </SurveyCreatorPage>
  );
}
