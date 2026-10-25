# 验证因子注册表：stepup 与设备挑战共用一套验证方式

日期：2026-10-25
状态：已实施（PR #197）
相关：ADR-0026（安全验证 Step-up）、ADR-0028（多端登录）、ADR-0029（账号安全中心）

## 背景

系统里有两处需要「证明是本人」：

1. **安全验证（stepup）**：改密码、换绑邮箱、注销、管理安全问题、撤销设备、解绑动态口令等敏感操作前的二次确认；
2. **陌生设备挑战**（ADR-0028）：密码正确但设备未经二次验证时，不建会话，先要求第二因素。

两者本来各自实现，且能力不一致：

| 验证方式 | stepup（改造前） | 设备挑战（改造前） |
|---|---|---|
| 邮箱验证码 | 有 | 有 |
| 安全问题 | 有 | 有 |
| 动态口令 TOTP | **无** | 有 |
| 恢复代码 | **无** | 有 |

代码层面是两段平行的 `if method == ... elif ...`（`views.stepup_verify_view` 与
`login_challenge.challenge_verify_view`），前端也各自硬编码了选项（`StepUpPage` 只认两种，
`LoginModal` 认四种）。

这带来了三个问题：

1. **真实的死锁**：手机丢失 → 要解绑 TOTP → 需要 `manage_totp` 的 stepup → stepup 只有邮箱码和安全问题 → 邮箱也不可用时无路可走。恢复代码明明已经存在，却没有接进 stepup。
2. **同一把钥匙锁自己的抽屉**：`manage_totp` 允许用 TOTP 自己验证。丢手机时它救不了你，反而给「拿到设备且知道密码」的人解绑其余验证方式的机会。
3. **扩展成本**：新增一种验证方式（例如短信码、Passkey）需要改 4 处——后端两段 if/elif、前端两个组件、以及两处状态接口。

## 决策

### 1. 单一注册表

新增 `accounts/factors.py`，把「验证方式」抽象为 `Factor`：

```python
@dataclass(frozen=True)
class Factor:
    key: str                                    # 对外的稳定标识
    label: str                                  # 前端展示文案（后端下发）
    available: Callable[[User], bool]           # 该用户此刻是否具备
    verify: Callable[[User, dict], None]        # 失败抛 FactorError / StepUpError
    excluded_scopes: frozenset = frozenset()    # 哪些操作禁止用本因子
    sends_code: bool = False                    # 需要先「发送验证码」
    hint: str = ""                              # 输入提示
```

注册顺序即展示顺序，按强度排列：`totp → email → question → recovery`。

`stepup`（`views.stepup_verify_view`）与设备挑战（`login_challenge.challenge_verify_view`）
**共用同一张表**，后者原有的第二套分支删除。

### 2. scope × factor 由 `excluded_scopes` 表达

不用另一张矩阵表，直接在因子上声明禁止场景：

```python
register(Factor("totp", "动态口令", ..., excluded_scopes=frozenset({"manage_totp"})))
```

**为什么 TOTP 不能用于 `manage_totp`**：该 scope 保护的动作是「解绑 / 重绑动态口令」。

- 正常场景：用户还有手机，用邮箱码或安全问题验证即可；
- 丢手机场景：TOTP 本身不可用，正是需要其他方式的时候；
- 设备失窃场景：若允许，攻击者只需密码 + 设备上的动态码就能解绑受害者的其余因素，降低其找回能力。

允许 `recovery`（一次性、离线保存）与 `email` / `question` 已覆盖全部合理路径。

### 3. 前后端契约

- `GET /auth/stepup/?scope=<scope>` 返回 `factors: [{key, label, hint, sends_code}]`（已按 scope 过滤）；
  `email` / `questions` 字段保留，供邮箱地址与题目状态展示，旧页面不受影响。
- 前端选项按钮由 `factors` 驱动；输入区按 `key` 渲染（email 发码+6 位 / question 选题+答案 /
  totp 6 位 / recovery 10 位），**未识别的 key 回退成通用验证码输入框**。
- `POST /auth/stepup/verify/` 的错误语义分三种，便于前端提示：
  - 未知方式 → 400「未知的验证方式。」
  - scope 内被排除 → 400「「X」不能用于当前操作，请换一种方式。」
  - 用户不具备 → 400「「X」当前不可用。」

### 4. 命名统一与兼容

设备挑战早期把邮箱因子叫 `email_code`，stepup 叫 `email`。本次统一为 `email`，
并在 `ALIASES = {"email_code": "email"}` 保留兼容——上线窗口内已签发的挑战记录
（`LoginChallenge.methods` 存的是 JSON 数组）不会因为改名失效。

## 新增一种验证方式的做法

1. 在 `accounts/factors.py` 写实现：

```python
def _sms_available(user) -> bool:
    return Profile.objects.filter(user=user, phone_verified=True).exists()

def _verify_sms(user, payload: dict) -> None:
    # 校验失败抛 FactorError("...")
    ...

register(Factor("sms", "短信验证码", _sms_available, _verify_sms,
                sends_code=True, hint="6 位短信码"))
```

2. 需要发码的，在 `views` 增加一个发送端点（参照 `stepup_email_send_view` 的冷却与节流策略）。
3. 前端不需要改选项列表；如果输入形态与通用验证码不同，再补一个输入区分支。

视图、`login_challenge`、接口契约、前端选项列表**都不需要改**——这是本 ADR 的核心收益。

## 兼容与迁移

- 无数据库迁移：`Factor` 是纯代码注册表。
- `LoginChallenge.methods` 的存量值 `email_code` 通过 `ALIASES` 兼容；新签发的挑战存 `email`。
- 回滚方式：`git revert` 该次合并即可；期间新增的挑战记录若存 `email`，
  旧代码会因 `method not in challenge.methods` 拒绝，用户重新登录即可（挑战 TTL 10 分钟）。

## 参考文件

- `accounts/factors.py`（注册表与四个因子的实现）
- `accounts/views.py`：`stepup_status_view`、`stepup_verify_view`
- `accounts/login_challenge.py`：`available_factors`、`challenge_verify_view`
- `frontend/src/pages/StepUpPage.tsx`、`frontend/src/api/stepup.ts`
- 测试：`accounts/tests_stepup.py::FactorRegistryTest`（scope 过滤、TOTP 签发 grant、
  TOTP 在 manage_totp 被拒而恢复码可用、恢复码一次性、未知因子、不可用因子）
