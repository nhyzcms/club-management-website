import { useEffect, useMemo, useState } from "react";
import type { PostcardSchool } from "../../api/postcard";
import { filterSchools, schoolLabel } from "./pure";

interface Props {
  /** 活动寄达校全量清单（portal.schools）。 */
  schools: PostcardSchool[];
  /** 当前选择的寄达区（空 = 未选，学校不可选）。 */
  region: string;
  /** 当前寄达校（校名，后端按「区 + 校名」校验）。 */
  value: string;
  onChange: (name: string) => void;
  id?: string;
  disabled?: boolean;
}

/**
 * 寄达校选择器：区内按编号排序（`1 · 某某中学`）+ 关键词检索。
 *
 * 登记表单与「历史记录 → 修改」共用。检索框只做即时筛选，不产生请求——清单
 * 已经随 portal 一次性下发（一区几十到几百所，本地过滤最省）。
 */
export default function SchoolPicker({ schools, region, value, onChange, id, disabled }: Props) {
  const [query, setQuery] = useState("");
  const empty = !region || Boolean(disabled);

  // 换区清空关键词：上一区的词对新区无意义，留着只会让人以为清单是空的。
  useEffect(() => {
    setQuery("");
  }, [region]);

  const options = useMemo(() => {
    const list = filterSchools(schools, region, query);
    if (value && !list.some((s) => s.name === value)) {
      // 搜索把当前选中项筛掉了也要保留它，否则下拉会显示成「未选择」。
      const selected = (schools || []).find((s) => s.region === region && s.name === value);
      if (selected) return [selected, ...list];
    }
    return list;
  }, [schools, region, query, value]);

  return (
    <div className="pc-school-picker">
      <input
        className="input"
        type="search"
        autoComplete="off"
        value={query}
        disabled={empty}
        aria-label="搜索寄达校（校名或编号）"
        placeholder={empty ? "请先选择寄达区" : "搜索校名 / 编号（如：12、浦东新区12）"}
        onChange={(e) => setQuery(e.target.value)}
      />
      <select
        id={id}
        className="input"
        value={value}
        disabled={empty}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">
          {empty ? "请先选择寄达区" : options.length ? "请选择" : "没有匹配的学校"}
        </option>
        {options.map((s) => (
          <option key={`${s.region}-${s.name}`} value={s.name}>
            {schoolLabel(s)}
          </option>
        ))}
      </select>
    </div>
  );
}
