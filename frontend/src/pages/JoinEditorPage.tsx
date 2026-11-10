import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { recruitmentApi } from "../api/recruitment";
import SurveyCreatorPage from "./SurveyCreatorPage";

export default function JoinEditorPage() {
  const navigate = useNavigate();

  const load = useCallback(async () => {
    const me: any = await api.me();
    if (!me.user?.permissions?.can_edit_about) {
      throw new Error("没有编辑权限。");
    }
    const d = await recruitmentApi.getSchema();
    return d.schema;
  }, []);

  const save = useCallback(async (schema: Record<string, unknown>) => {
    await recruitmentApi.updateSchema(schema);
  }, []);

  return (
    <SurveyCreatorPage title="编辑自我介绍问卷" load={load} save={save} canSave>
      <nav className="breadcrumb">
        <a href="#" onClick={(e) => { e.preventDefault(); navigate("/join"); }}>加入社团</a>
        <span className="sep">/</span>
        <span>编辑问卷</span>
      </nav>
    </SurveyCreatorPage>
  );
}
