from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """邮箱认证令牌：绑 **email 通道 identifier + status**（ADR-0006）。

    复用 PasswordResetTokenGenerator 模式（带时间戳、SECRET_KEY 签名、默认 7 天过期）。
    待认证邮箱住 ``Verification.identifier``（非 User.email）。_make_hash_value 绑 identifier + status：
      - 改待认证邮箱（identifier 变）→ 旧令牌失效，须认证新邮箱；
      - 认证通过（status → approved）→ 令牌随即失效，不可重放。
    """

    def _make_hash_value(self, user, timestamp):
        v = user.verifications.filter(channel="email").first()
        identifier = getattr(v, "identifier", "") or ""
        status = getattr(v, "status", "") or ""
        return f"{user.pk}{identifier}{status}{timestamp}"


email_verification_token = EmailVerificationTokenGenerator()
