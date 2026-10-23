"""姓名排序（ADR-0025）：拼音首字母判定 + 排序键。

识别码的「姓名排序序号」要求按**姓名首字母**排；判定不能靠第三方拼音库
（服务器只有 2 GB 内存），靠 GB2312 一级字区的音序分段反推 + 姓氏读音覆盖表。
"""
from django.test import SimpleTestCase

from accounts.name_order import (
    COMPOUND_SURNAME_INITIALS,
    SURNAME_INITIALS,
    name_order_bytes,
    name_sort_key,
    surname_initial,
)


class SurnameInitialTest(SimpleTestCase):
    # 常见姓氏（一级字区，按音序分段反推）
    COMMON = {
        "赵": "Z", "钱": "Q", "孙": "S", "李": "L", "周": "Z", "吴": "W", "郑": "Z",
        "王": "W", "冯": "F", "陈": "C", "蒋": "J", "沈": "S", "韩": "H", "杨": "Y",
        "朱": "Z", "秦": "Q", "许": "X", "何": "H", "吕": "L", "施": "S", "张": "Z",
        "孔": "K", "曹": "C", "严": "Y", "华": "H", "金": "J", "魏": "W", "陶": "T",
        "姜": "J", "谢": "X", "邹": "Z", "章": "Z", "苏": "S", "潘": "P", "葛": "G",
        "范": "F", "彭": "P", "鲁": "L", "韦": "W", "马": "M", "方": "F", "任": "R",
        "袁": "Y", "柳": "L", "鲍": "B", "史": "S", "唐": "T", "薛": "X", "雷": "L",
        "贺": "H", "汤": "T", "罗": "L", "毕": "B", "郝": "H", "安": "A", "常": "C",
        "于": "Y", "傅": "F", "康": "K", "伍": "W", "余": "Y", "顾": "G", "孟": "M",
        "黄": "H", "穆": "M", "萧": "X", "尹": "Y", "姚": "Y", "邵": "S", "汪": "W",
        "祁": "Q", "毛": "M", "米": "M", "明": "M", "戴": "D", "宋": "S", "熊": "X",
        "纪": "J", "舒": "S", "屈": "Q", "项": "X", "董": "D", "梁": "L", "杜": "D",
        "蓝": "L", "季": "J", "贾": "J", "路": "L", "江": "J", "童": "T", "颜": "Y",
        "郭": "G", "梅": "M", "盛": "S", "林": "L", "钟": "Z", "徐": "X", "邱": "Q",
        "高": "G", "夏": "X", "蔡": "C", "田": "T", "樊": "F", "胡": "H", "凌": "L",
        "霍": "H", "万": "W", "柯": "K", "卢": "L", "莫": "M", "丁": "D", "邓": "D",
        "郁": "Y", "杭": "H", "洪": "H", "包": "B", "诸": "Z", "左": "Z", "石": "S",
        "崔": "C", "吉": "J", "龚": "G", "程": "C", "邢": "X", "裴": "P", "陆": "L",
        "荣": "R", "翁": "W", "羊": "Y", "惠": "H", "甄": "Z", "曲": "Q", "封": "F",
        "储": "C", "靳": "J", "段": "D", "富": "F", "巫": "W", "焦": "J", "巴": "B",
        "山": "S", "谷": "G", "车": "C", "侯": "H", "全": "Q", "班": "B", "秋": "Q",
        "仲": "Z", "伊": "Y", "宫": "G", "宁": "N", "曾": "Z",
    }

    def test_common_surnames_follow_pinyin_initial(self):
        for surname, letter in self.COMMON.items():
            with self.subTest(surname=surname):
                self.assertEqual(surname_initial(surname), letter)
                self.assertEqual(surname_initial(f"{surname}伟"), letter)

    def test_gb2312_section_boundaries(self):
        """段首字 / 段末字（边界由「相邻字」交叉验证：段前一字符是上一段末字）。"""
        self.assertEqual(surname_initial("啊"), "A")   # A 段首
        self.assertEqual(surname_initial("澳"), "A")   # A 段末
        self.assertEqual(surname_initial("孕"), "Y")   # Y 段末
        self.assertEqual(surname_initial("匝"), "Z")   # Z 段首
        self.assertEqual(surname_initial("座"), "Z")   # 一级字区末字
        self.assertEqual(surname_initial("做"), "Z")

    def test_polyphone_surnames_use_surname_reading(self):
        """GB2312 按常用读音排字，姓氏读音不同时要改判（否则 单/解/查 会混进 D/J/C）。"""
        for surname, letter in {
            "单": "S", "解": "X", "查": "Z", "仇": "Q", "区": "O", "乐": "Y",
            "尉": "Y", "种": "C", "句": "G", "秘": "B", "繁": "P", "折": "S", "召": "S",
        }.items():
            with self.subTest(surname=surname):
                self.assertEqual(surname_initial(surname), letter)

    def test_level2_surnames_use_override(self):
        """二级字区按部首排序、位置无读音——只能走覆盖表。"""
        for surname, letter in {
            "覃": "Q", "缪": "M", "隗": "W", "佘": "S", "冼": "X", "邝": "K",
            "逯": "L", "郗": "X", "璩": "Q", "濮": "P", "扈": "H", "钭": "T",
            "訾": "Z", "阚": "K", "蒯": "K", "缑": "G", "禤": "X", "仉": "Z",
            "呙": "G", "芈": "M", "郤": "X", "厍": "S", "郜": "G", "亓": "Q",
            "仝": "T", "弋": "Y", "郏": "J",
        }.items():
            with self.subTest(surname=surname):
                self.assertEqual(surname_initial(surname), letter)

    def test_compound_surnames(self):
        self.assertEqual(surname_initial("欧阳娜娜"), "O")   # 按首字读音
        self.assertEqual(surname_initial("尉迟敬德"), "Y")
        self.assertEqual(surname_initial("长孙无忌"), "Z")
        self.assertEqual(surname_initial("单于某"), "C")     # Chányú
        self.assertEqual(surname_initial("万俟某"), "M")     # Mòqí
        self.assertEqual(surname_initial("澹台某"), "T")     # Tántái

    def test_unknown_and_ascii(self):
        self.assertEqual(surname_initial(""), "")
        self.assertEqual(surname_initial("   "), "")
        self.assertEqual(surname_initial("Alice"), "A")      # 英文名按字母归位
        self.assertEqual(surname_initial("3班某人"), "")      # 数字判不出
        self.assertEqual(surname_initial("\U00020000某"), "")  # 扩展 B 区生僻字

    def test_override_tables_are_sane(self):
        """覆盖表的值必须是单个 A-Z 字母（防止手抄错字，如写成 'SH'）。"""
        for table in (SURNAME_INITIALS, COMPOUND_SURNAME_INITIALS):
            for key, letter in table.items():
                with self.subTest(key=key):
                    self.assertEqual(len(letter), 1)
                    self.assertIn(letter, "ABCDEFGHIJKLMNOPQRSTUVWXYZ")


class NameSortKeyTest(SimpleTestCase):
    def test_sorts_by_initial_not_by_gbk_of_char(self):
        """关键回归：单（shàn）在 GBK 里排在「dan」区，若直接按字节序会跑到 李 前面。"""
        names = ["张伟", "单田芳", "李四"]
        self.assertEqual(sorted(names, key=name_sort_key), ["李四", "单田芳", "张伟"])

    def test_sorts_mixed_initials(self):
        names = ["周八", "艾七", "欧阳娜娜", "陈一", "冼星海", "邝某", "欧阳锋"]
        self.assertEqual(
            sorted(names, key=name_sort_key),
            # 同首字母内按 GBK 序细排（锋 fēng < 娜 nà）
            ["艾七", "陈一", "邝某", "欧阳锋", "欧阳娜娜", "冼星海", "周八"],
        )

    def test_unknown_initial_sorts_last_but_stable(self):
        key = name_sort_key("3班某人")
        self.assertEqual(key[0], 1)
        for name in ("张三", "李四", "冼星海", "Alice"):
            self.assertLess(name_sort_key(name), key)

    def test_whitespace_ignored_and_deterministic(self):
        self.assertEqual(name_sort_key("张 三"), name_sort_key("张三"))
        self.assertEqual(name_sort_key("张三　"), name_sort_key("张三"))
        self.assertEqual(name_order_bytes("张 三"), name_order_bytes("张三"))
        self.assertEqual(name_sort_key(""), (1, "", b""))
