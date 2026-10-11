"""邮箱后缀白名单（ADR-0023）：只接受认可的服务商域名 + 中国大陆 / 港澳台院校域。

为什么有白名单：站点用第三方邮箱发验证信（``settings.EMAIL_HOST_*``），成员普遍
在用的服务商到达率稳定、出问题也好排查；放开任意后缀只会增加「收不到验证信」的
支持成本。名单是**代码级策略**（不接受用户输入），改名单 = 改这里 + 走 PR。

判定只发生在**接收新地址**的两处：
  - ``accounts.views.register_view``（注册带邮箱）；
  - ``accounts.views.verification_email_bind_view``（验证面板绑定 / 换绑）。
不回溯：已绑定地址、重发验证信（``/auth/resend-verification/``）、Django admin
里管理员手填的邮箱不受影响（见 ADR-0023 决策 4）。

两类判定（见 ADR-0023 决策 2）：
  - 服务商域（``ALLOWED_EMAIL_DOMAINS``）：**精确匹配**（``evil163.com`` 不放行）；
  - 院校域（``EDU_DOMAIN_SUFFIXES``）：**域自身或子域**均放行 —— 高校邮箱无法穷举
    （每校一个域，学生信箱还常在 ``stu.`` / ``mails.`` / ``connect.`` 等更深子域）。
"""

from __future__ import annotations

#: 商业邮箱服务商：按服务商分组（便于人工核对与增设）；判定只看拍平后的域名集合。
PROVIDER_DOMAINS: dict[str, tuple[str, ...]] = {
    "网易": (
        "163.com", "126.com", "yeah.net", "188.com", "vip.163.com", "vip.126.com",
    ),
    "QQ": ("qq.com", "foxmail.com", "vip.qq.com"),
    "微软 Outlook": ("outlook.com", "hotmail.com", "live.com", "live.cn", "msn.com"),
    # Apple：「隐藏我的邮件」转发地址（@privaterelay.appleid.com）也属 Apple 邮箱，
    # 否则用 Apple 账号登录 / 转发的成员永远绑不上。
    "Apple iCloud": ("icloud.com", "me.com", "mac.com", "privaterelay.appleid.com"),
    "中国移动": ("139.com",),
    "中国联通": ("wo.cn",),
    "中国电信": ("189.cn", "21cn.com"),
    "新浪": ("sina.com", "sina.cn", "sina.com.cn", "vip.sina.com"),
}

#: 拍平后的允许服务商域名集合（精确匹配）。
ALLOWED_EMAIL_DOMAINS: frozenset[str] = frozenset(
    domain for domains in PROVIDER_DOMAINS.values() for domain in domains
)

#: 中国大陆 / 港澳台院校域：**域自身或其子域**均放行（高校邮箱无法穷举）——
#: ``pku.edu.cn`` 与学生信箱 ``stu.pku.edu.cn``、``mails.tsinghua.edu.cn`` 同属一校；
#: 学生信箱不在 ``edu.*`` 域下的院校逐校列出（域名归属该校，整域放行）。
#: 非「包含」匹配：``notedu.cn`` / ``edu.cn.evil.com`` / ``hku.hk.evil.com`` 均不放行。
EDU_DOMAIN_SUFFIXES: tuple[str, ...] = (
    # ── 大陆 / 港澳台院校统一域：各校自成一个子域 ──
    "edu.cn",   # 中国大陆：pku.edu.cn、stu.fudan.edu.cn、mails.tsinghua.edu.cn、中小学 xxx.edu.cn
    "edu.hk",   # 香港：cuhk.edu.hk、link.cuhk.edu.hk、my.cityu.edu.hk …
    "edu.mo",   # 澳门：um.edu.mo、must.edu.mo、ipm.edu.mo、usj.edu.mo …
    "edu.tw",   # 台湾：ntu.edu.tw、gm.ntu.edu.tw、mail.ncku.edu.tw …
    # ── 学生信箱不在 edu.* 域下的院校（逐校列出）──
    "hku.hk",      # 香港大学（学生 @connect.hku.hk）
    "ust.hk",      # 香港科技大学（学生 @connect.ust.hk）
    "polyu.hk",    # 香港理工大学（学生 @connect.polyu.hk）
    "eduhk.hk",    # 香港教育大学（学生 @s.eduhk.hk）
    "hksyu.edu",   # 香港树仁大学（域为 .edu，非 .edu.hk）
    "umac.mo",     # 澳门大学（旧域 umac.mo）
    "cityu.mo",    # 澳门城市大学（域为 .mo，非 .edu.mo）
    "ucas.ac.cn",  # 中国科学院大学（学生 @mails.ucas.ac.cn）
)

#: 被拦时的固定文案：前端 NoticeModal 弹窗逐字展示，契约测试钉死（勿改字）。
EMAIL_DOMAIN_BLOCKED_MESSAGE = "该邮箱后缀暂不可用，请换用其他邮箱。详询社长或服务器管理员"


#: 后端 reason 串：前端按它映射成类型化 `email_domain_not_allowed`（见 shared.ts）。
EMAIL_DOMAIN_BLOCKED_REASON = "email_domain_not_allowed"


def email_domain(email: str) -> str:
    """取邮箱域名（小写、去空白）；无 ``@`` 或 ``@`` 在首尾 → 空串。"""
    _, sep, domain = (email or "").strip().lower().rpartition("@")
    return domain if sep else ""


def is_edu_domain(domain: str) -> bool:
    """院校域：等于后缀（``hku.hk``）或为其子域（``connect.hku.hk``）。"""
    return any(
        domain == suffix or domain.endswith("." + suffix)
        for suffix in EDU_DOMAIN_SUFFIXES
    )


def is_allowed_email_domain(email: str) -> bool:
    """邮箱后缀是否放行：服务商域精确匹配，或命中院校后缀规则。"""
    domain = email_domain(email)
    if not domain:
        return False
    return domain in ALLOWED_EMAIL_DOMAINS or is_edu_domain(domain)
