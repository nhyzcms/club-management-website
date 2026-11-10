export type DraftSubject = {
  key: string;
  name: string;
  exam_date: string;
  start_time: string;
  end_time: string;
};

export type DraftBatch = { key: string; name: string; subjects: DraftSubject[] };

/** Same-day overlap or start≥end is invalid. Adjacent (end === next start) is allowed. */
export function validateExamDraft(title: string, batches: DraftBatch[]): string | null {
  if (!title.trim()) return "请填写考试标题";
  if (!batches.length) return "请至少添加一个批次";
  const names = batches.map((b) => b.name.trim());
  if (names.some((n) => !n)) return "请填写批次名称";
  if (new Set(names).size !== names.length) return "同一考试下批次名称不能重复";

  for (const batch of batches) {
    const byDate = new Map<string, DraftSubject[]>();
    for (const subject of batch.subjects) {
      const incomplete = !subject.name.trim() && !subject.exam_date && !subject.start_time && !subject.end_time;
      if (incomplete) continue;
      if (!subject.name.trim() || !subject.exam_date || !subject.start_time || !subject.end_time) {
        return `「${batch.name}」有科目日期或时间不完整`;
      }
      if (subject.end_time <= subject.start_time) {
        return `「${batch.name}」${subject.name} 的开始时间不能晚于或等于结束时间`;
      }
      const rows = byDate.get(subject.exam_date) ?? [];
      for (const other of rows) {
        if (subject.start_time < other.end_time && subject.end_time > other.start_time) {
          return `「${batch.name}」${subject.exam_date}「${subject.name}」与「${other.name}」时间重叠`;
        }
      }
      rows.push(subject);
      byDate.set(subject.exam_date, rows);
    }
  }
  return null;
}

export function subjectRowInvalid(batch: DraftBatch, subject: DraftSubject): boolean {
  if (!subject.name.trim() || !subject.exam_date || !subject.start_time || !subject.end_time) return false;
  if (subject.end_time <= subject.start_time) return true;
  return batch.subjects.some((other) => {
    if (other.key === subject.key) return false;
    if (other.exam_date !== subject.exam_date) return false;
    if (!other.start_time || !other.end_time) return false;
    return subject.start_time < other.end_time && subject.end_time > other.start_time;
  });
}
