import { useEffect, useMemo, useRef, useState } from "react";
import { Survey } from "survey-react-ui";
import "survey-core/survey-core.css";
import { createSurveyModel } from "../utils/survey";
import "../styles/survey.css";

/** SurveyJS fill widget shared by 调研 detail and 自我介绍问卷. */
export default function SurveyFill({
  schema,
  onComplete,
}: {
  schema: Record<string, unknown>;
  onComplete: (answers: Record<string, unknown>) => Promise<void>;
}) {
  const [error, setError] = useState("");
  const onCompleteRef = useRef(onComplete);
  useEffect(() => {
    onCompleteRef.current = onComplete;
  }, [onComplete]);

  const model = useMemo(
    () =>
      createSurveyModel(schema, async (answers) => {
        setError("");
        try {
          await onCompleteRef.current(answers);
        } catch (e: any) {
          setError(e?.message || "提交失败");
        }
      }),
    [schema],
  );

  return (
    <div className="survey-card">
      {error && (
        <div className="alert alert-danger" style={{ marginBottom: 12 }}>
          <span>{error}</span>
        </div>
      )}
      <Survey model={model} />
    </div>
  );
}
