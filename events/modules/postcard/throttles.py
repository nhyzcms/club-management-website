"""明信片互寄限流（复用 ``common.throttles.IPLimitThrottle`` 基座）。

公开写端点（登记 / 建议）是全站暴露面最大的入口——活动期间任何访客可写，
双轨限流：**IP 轨**（学校 NAT 出口整层楼共用，阈值放宽）+ **设备轨**
（``ncdid`` Cookie，同一设备刷量绕不过 NAT 轨）。两轨任一触发即 429。

速率取值偏保守：登记是低频动作（一人一天最多几张），10/h 足够真人、
足够卡脚本；建议箱 5/h。管理端不限流（低频 + 已鉴权）。
"""
from common.throttles import IPLimitThrottle

from accounts.utils import device_id_from_request


class _DeviceOrIPThrottle(IPLimitThrottle):
    """设备优先、IP 兜底的限流键：有 ncdid 按设备计，没有按 IP 计。"""

    def get_cache_key(self, request, view):
        device = device_id_from_request(request)
        ident = f"d:{device}" if device else None
        if ident is None:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class RegisterIPThrottle(IPLimitThrottle):
    """登记 IP 轨：学校 NAT 整层楼共用出口，必须比单设备宽松（2026-11-08 修正）。

    原来 IP 与设备同为 10/h，一个班 30 人同时登记第 11 个就全 429。
    设备轨仍 10/h（一人一天几张足够），IP 轨放宽到 60/h。
    """
    scope = "postcard_register_ip"
    RATE = "60/hour"

    def get_rate(self):
        return self.RATE


class RegisterDeviceThrottle(_DeviceOrIPThrottle):
    scope = "postcard_register_dev"
    RATE = "10/hour"

    def get_rate(self):
        return self.RATE


class SuggestionIPThrottle(IPLimitThrottle):
    scope = "postcard_suggest_ip"
    RATE = "5/hour"

    def get_rate(self):
        return self.RATE


class SuggestionDeviceThrottle(_DeviceOrIPThrottle):
    scope = "postcard_suggest_dev"
    RATE = "5/hour"

    def get_rate(self):
        return self.RATE


# —— 用户侧查询（按登记码 / 寄出人姓名，2026-11-08 用户要求）——
# 读端点，防的是「枚举」而不是「刷量」：设备轨卡脚本频率，IP 轨放宽给
# 学校 NAT（整层楼共用一个出口）。真人查询频率远低于阈值。


class LookupIPThrottle(IPLimitThrottle):
    scope = "postcard_lookup_ip"
    RATE = "300/hour"

    def get_rate(self):
        return self.RATE


class LookupDeviceThrottle(_DeviceOrIPThrottle):
    scope = "postcard_lookup_dev"
    RATE = "20/min"

    def get_rate(self):
        return self.RATE


# 「登记码即能力凭证」端点（详情 / 改 / 取消 / 复核申请 / 关页清理）：
# 凭证只有 6 位数字，必须卡枚举。真人低频，阈值可收得很紧。
class CodeAccessIPThrottle(IPLimitThrottle):
    scope = "postcard_code_ip"
    RATE = "120/hour"

    def get_rate(self):
        return self.RATE


class CodeAccessDeviceThrottle(_DeviceOrIPThrottle):
    scope = "postcard_code_dev"
    RATE = "30/min"

    def get_rate(self):
        return self.RATE


class SchoolsImportThrottle(IPLimitThrottle):
    """导入海报：一次请求 = 一张大图 + 一次长输出，管理员连点也会真花钱。

    低频管理动作，10/h 对真人不构成限制，对「按钮卡住狂点」足够。
    """

    scope = "postcard_schools_import"
    RATE = "10/hour"

    def get_rate(self):
        return self.RATE


class AITestThrottle(IPLimitThrottle):
    """测试连接：一次请求 = 一次真实模型调用。

    管理端一般不限流（低频 + 已鉴权），但「会真花钱」的按钮必须限——
    与导入海报同一个理由：按钮卡住被连点 / 脚本重放，账单和 worker 都受不了。
    配参数时管理员确实会反复测，所以比导入海报宽松。
    """

    scope = "postcard_ai_test"
    RATE = "60/hour"

    def get_rate(self):
        return self.RATE


class AIModelsThrottle(IPLimitThrottle):
    """拉取模型列表：只读、不花钱，但会打到服务商并占 worker。

    比测试连接宽松（管理员配参数时会反复刷新列表），仍要限住脚本重放。
    """

    scope = "postcard_ai_models"
    RATE = "120/hour"

    def get_rate(self):
        return self.RATE


class AIExplainThrottle(IPLimitThrottle):
    """让 AI 读样例：一张图 + 一次长输出（成本与导入海报同档）。"""

    scope = "postcard_ai_explain"
    RATE = "10/hour"

    def get_rate(self):
        return self.RATE


class AIReviewPreviewThrottle(IPLimitThrottle):
    """模拟环境的「真调 AI 判定」：一次请求 = 一张明信片的两面照片 + 模型调用。

    模拟登记本身就按张数计（一次最多 5 张），阈值放宽到 120/h，够演练一场
    小型活动；同时避免被连点 / 重放当成免费额度刷。
    """

    scope = "postcard_ai_preview"
    RATE = "120/hour"

    def get_rate(self):
        return self.RATE
