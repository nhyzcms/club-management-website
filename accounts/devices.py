"""设备识别、设备记录与登录事件（账号安全中心 P0）。

**设备身份 = 服务端签发的随机 ID**（cookie ``ncdid``，由 ``DeviceIDMiddleware`` 下发），
与硬件标识无关——浏览器没有任何 API 能读 MAC；品牌 / 型号只能从 UA 与 User-Agent
Client Hints 尽力推断：

- Android Chromium：UA 里带机型（如 ``SM-S918B``）；若服务端下发 ``Accept-CH``，
  后续请求还会带 ``Sec-CH-UA-Model``（更准）；
- iOS Safari：UA 只有 ``iPhone`` / ``iPad``，拿不到具体型号；
- Windows / macOS 桌面：只有系统名与浏览器版本，**没有品牌型号**（笔记本不会自报家门）。

因此 ``brand`` / ``model`` 允许为空，界面退化显示「Chrome · Windows」。

**这里的实现不参与信任判定**：设备是否「已知」由二次验证决定（用户 2026-10-24 定的原则），
指纹 / UA / IP 都不构成信任。
"""
from __future__ import annotations

import re
import secrets

from django.utils import timezone

from .geolocate import geolocate
from .models import AccountDevice, LoginEvent
from .utils import device_id_from_request, get_client_ip

_DEVICE_ID_RE = re.compile(r"^[0-9a-f]{32}$")

_WECHAT_RE = re.compile(r"MicroMessenger", re.I)
_QQ_RE = re.compile(r"\sQQ/", re.I)
_EDGE_RE = re.compile(r"Edg(?:e|A|iOS)?/([\d.]+)")
_OPERA_RE = re.compile(r"(?:OPR|Opera)/([\d.]+)")
_CHROME_RE = re.compile(r"(?:Chrome|CriOS)/([\d.]+)")
_FIREFOX_RE = re.compile(r"(?:Firefox|FxiOS)/([\d.]+)")
_SAFARI_RE = re.compile(r"Version/([\d.]+).*Safari/")

_WINDOWS_RE = re.compile(r"Windows NT ([\d.]+)")
_ANDROID_RE = re.compile(r"Android ([\d.]+)")
_IOS_RE = re.compile(r"(?:iPhone|iPad|iPod).*OS ([\d_]+)")
_MAC_RE = re.compile(r"Mac OS X ([\d_]+)")

# Android UA 的机型段：``Android 14; SM-S918B Build/…`` 或 ``Android 13; 22081212C)``
_ANDROID_MODEL_RE = re.compile(r"Android[^;)]*;\s*([^;)]+?)(?:\s+Build[/;]|\)|$)")

# 品牌启发式：只覆盖常见机型前缀，认不出就留空（宁可空，不乱猜）。
_BRAND_HINTS = (
    ("Samsung", ("SM-", "Samsung")),
    ("Google", ("Pixel",)),
    ("Xiaomi", ("Redmi", "POCO", "Mi ", "MI ", "M2", "22")),
    ("Huawei", ("HUAWEI", "HONOR", "ELS-", "NOH-", "ALN-")),
    ("vivo", ("vivo", "V2")),
    ("OPPO", ("OPPO", "CPH", "PJZ", "PHK")),
    ("OnePlus", ("ONEPLUS", "LE2", "NE2")),
    ("Apple", ("iPhone", "iPad", "iPod")),
)



def is_valid_device_id(value: str) -> bool:
    return bool(_DEVICE_ID_RE.fullmatch(value or ""))


def _browser(ua: str) -> str:
    if _WECHAT_RE.search(ua):
        return "微信"
    if _QQ_RE.search(ua):
        return "QQ"
    for regex, name in (
        (_EDGE_RE, "Edge"),
        (_OPERA_RE, "Opera"),
        (_CHROME_RE, "Chrome"),
        (_FIREFOX_RE, "Firefox"),
        (_SAFARI_RE, "Safari"),
    ):
        if regex.search(ua):
            return name
    return "浏览器"


def _platform(ua: str, sec_ch_platform: str = "") -> tuple[str, str]:
    """返回 (平台名, 版本号)。版本号只保留主版本，够展示用。"""
    if m := _ANDROID_RE.search(ua):
        return "Android", m.group(1).split(".")[0]
    if m := _IOS_RE.search(ua):
        return "iOS", m.group(1).replace("_", ".").split(".")[0]
    if _WINDOWS_RE.search(ua):
        # Windows NT 10.0 既可能是 Win10 也可能是 Win11，UA 区分不了 → 不写版本。
        return "Windows", ""
    if m := _MAC_RE.search(ua):
        return "macOS", m.group(1).split(".")[0]
    if "Linux" in ua:
        return "Linux", ""
    hinted = (sec_ch_platform or "").strip().strip('"')
    return (hinted, "") if hinted else ("未知", "")


def _brand_model(ua: str, sec_ch_model: str, platform: str) -> tuple[str, str]:
    model = (sec_ch_model or "").strip().strip('"')
    if not model:
        if m := _ANDROID_MODEL_RE.search(ua):
            model = m.group(1).strip()
        elif platform == "iOS":
            model = "iPhone" if "iPhone" in ua else ("iPad" if "iPad" in ua else "")
    brand = ""
    # 先用型号本身判断（UA-CH 的 Model 比 UA 更可靠），认不出再看整条 UA。
    for name, hints in _BRAND_HINTS:
        if model and any(h in model for h in hints):
            brand = name
            break
    if not brand:
        for name, hints in _BRAND_HINTS:
            if any(h in ua for h in hints):
                brand = name
                break
    return brand, model


def parse_device(ua: str, sec_ch_model: str = "", sec_ch_platform: str = "") -> dict:
    """UA → 可展示的设备信息（brand/model 允许为空）。"""
    ua = ua or ""
    browser = _browser(ua)
    platform, version = _platform(ua, sec_ch_platform)
    brand, model = _brand_model(ua, sec_ch_model, platform)
    os_label = f"{platform} {version}".strip() if version else platform
    label = " · ".join(p for p in (browser, os_label, model if model and model not in os_label else "") if p)
    return {
        "label": label[:128],
        "browser": browser[:64],
        "platform": platform[:32],
        "brand": brand[:64],
        "model": model[:96],
    }


def get_or_create_device(user, request):
    """按 (user, device_id) 认设备；返回 (device | None, created)。

    没有合法 ``club_device``（如脚本直连 API）时不建设备记录——设备 ID 只能由浏览器 cookie 提供。
    """
    device_id = device_id_from_request(request)
    if not is_valid_device_id(device_id):
        return None, False

    info = parse_device(
        request.META.get("HTTP_USER_AGENT", ""),
        request.META.get("HTTP_SEC_CH_UA_MODEL", ""),
        request.META.get("HTTP_SEC_CH_UA_PLATFORM", ""),
    )
    ip = get_client_ip(request)
    geo = geolocate(ip)

    device, created = AccountDevice.objects.get_or_create(
        user=user,
        device_id=device_id,
        defaults={
            **info,
            "last_ip": ip,
            "last_city": geo["city"],
            "last_country": geo["country"],
        },
    )
    if not created:
        device.last_seen = timezone.now()
        device.last_ip = ip
        changed = ["last_seen", "last_ip", *info.keys()]
        for field, value in info.items():
            setattr(device, field, value)
        if geo["city"]:
            device.last_city = geo["city"]
            changed.append("last_city")
        if geo["country"]:
            device.last_country = geo["country"]
            changed.append("last_country")
        device.save(update_fields=changed)
    return device, created


def record_login_event(
    request,
    *,
    user=None,
    device=None,
    status: str = "success",
    method: str = "password",
    second_factor: str = "none",
    is_new_device: bool = False,
    session_key: str = "",
) -> LoginEvent:
    """写一条登录事件（成功 / 失败 / 被限流都会记）。"""
    ip = get_client_ip(request)
    geo = geolocate(ip)
    return LoginEvent.objects.create(
        user=user,
        device=device,
        session_key=(session_key or "")[:40],
        method=method[:16],
        status=status[:16],
        second_factor=(second_factor or "")[:16],
        is_new_device=is_new_device,
        ip=ip,
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:2000],
        city=geo["city"],
        region=geo["region"],
        country=geo["country"],
        latitude=geo["latitude"],
        longitude=geo["longitude"],
    )


def accept_ch_header() -> str:
    """让 Chromium 在后续请求里带上高熵设备信息（型号/平台版本）。"""
    return "Sec-CH-UA-Model, Sec-CH-UA-Platform-Version"
