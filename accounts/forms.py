from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password

from .models import Profile


class LoginForm(forms.Form):
    password = forms.CharField(required=True)
    username = forms.CharField(required=False)
    email = forms.EmailField(required=False)
    # 「记住登录」：勾选 → 持久 cookie（30 天）；不勾 → 会话 cookie（关浏览器失效）。
    remember = forms.BooleanField(required=False)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("username") and not cleaned.get("email"):
            raise forms.ValidationError("Username or email is required")
        return cleaned

    def get_username(self):
        username = self.cleaned_data.get("username")
        if username:
            return username
        email = self.cleaned_data["email"]
        try:
            # 邮箱大小写不敏感（注册时归一化为小写存储）
            return User.objects.get(email__iexact=email).username
        except User.DoesNotExist:
            return None


class PasswordResetForm(forms.Form):
    email = forms.EmailField(required=True)


class PasswordResetConfirmForm(forms.Form):
    uid = forms.CharField(required=True)
    token = forms.CharField(required=True)
    new_password = forms.CharField(required=True)

    def clean_new_password(self):
        # 与注册 / 强制改密同一套校验器（审计 L-7）。
        value = self.cleaned_data["new_password"]
        validate_password(value)
        return value


class ProfileForm(forms.Form):
    nickname = forms.CharField(max_length=50, required=False)
    birthday = forms.DateField(required=False)
    gender = forms.ChoiceField(choices=[("", "")] + Profile.GENDER_CHOICES, required=False)
    bio = forms.CharField(max_length=500, required=False)


class ChangePasswordForm(forms.Form):
    old_password = forms.CharField(required=True)
    new_password = forms.CharField(required=True, min_length=8)

    def clean_new_password(self):
        value = self.cleaned_data["new_password"]
        validate_password(value)
        return value
