"""IP → 城市级位置（可插拔，缺库时静默降级）。

**精度声明**：城市级。移动网络常落到运营商出口城市（可能显示成省会），IPv6 精度更差；
不提供街道级位置。页面需标注「根据 IP 推算，仅供参考」。

**当前状态（P0）**：接口与城市坐标表已固化；ip2region 离线库（xdb）的接入留待下一步——
库里没有 xdb 文件时 ``geolocate()`` 返回空值，登录事件仍记录 IP 原文，不影响其它功能。
接入时只需实现 ``_search_ip2region``，上层不用改。
"""
from __future__ import annotations

import ipaddress
import os

from django.conf import settings

_EMPTY = {"city": "", "region": "", "country": "", "latitude": None, "longitude": None}

# ip2region 返回的行政区名带后缀（江苏省 / 南京市 / 内蒙古自治区），坐标表用简称。
_REGION_SUFFIXES = ("维吾尔自治区", "壮族自治区", "回族自治区", "特别行政区", "自治区", "省")
_CITY_SUFFIXES = ("自治州", "地区", "盟", "市")

_searcher = None

# 常用城市 → 城市中心点（纬度, 经度）。IP 定位只到城市，打点用中心点即可。
# 只收录常用城市；未收录的城市仍显示文字，只是没有坐标（地图不画点）。
_CITY_COORDS = {
    ("上海", "上海"): (31.2304, 121.4737),
    ("北京", "北京"): (39.9042, 116.4074),
    ("天津", "天津"): (39.0842, 117.2009),
    ("重庆", "重庆"): (29.5630, 106.5516),
    ("江苏", "南京"): (32.0603, 118.7969),
    ("江苏", "苏州"): (31.2989, 120.5853),
    ("江苏", "无锡"): (31.4912, 120.3119),
    ("江苏", "南通"): (31.9802, 120.8943),
    ("浙江", "杭州"): (30.2741, 120.1551),
    ("浙江", "宁波"): (29.8683, 121.5440),
    ("浙江", "温州"): (27.9938, 120.6994),
    ("浙江", "嘉兴"): (30.7460, 120.7555),
    ("广东", "广州"): (23.1291, 113.2644),
    ("广东", "深圳"): (22.5431, 114.0579),
    ("广东", "东莞"): (23.0207, 113.7518),
    ("广东", "佛山"): (23.0219, 113.1214),
    ("广东", "珠海"): (22.2707, 113.5767),
    ("福建", "福州"): (26.0745, 119.2965),
    ("福建", "厦门"): (24.4798, 118.0894),
    ("山东", "济南"): (36.6512, 117.1201),
    ("山东", "青岛"): (36.0671, 120.3826),
    ("河南", "郑州"): (34.7466, 113.6254),
    ("湖北", "武汉"): (30.5928, 114.3055),
    ("湖南", "长沙"): (28.2282, 112.9388),
    ("四川", "成都"): (30.5728, 104.0668),
    ("陕西", "西安"): (34.3416, 108.9398),
    ("辽宁", "沈阳"): (41.8057, 123.4315),
    ("辽宁", "大连"): (38.9140, 121.6147),
    ("安徽", "合肥"): (31.8206, 117.2272),
    ("江西", "南昌"): (28.6820, 115.8579),
    ("广西", "南宁"): (22.8170, 108.3665),
    ("云南", "昆明"): (25.0389, 102.7183),
    ("贵州", "贵阳"): (26.6477, 106.6302),
    ("河北", "石家庄"): (38.0428, 114.5149),
    ("山西", "太原"): (37.8706, 112.5489),
    ("吉林", "长春"): (43.8171, 125.3235),
    ("黑龙江", "哈尔滨"): (45.8038, 126.5349),
    ("内蒙古", "呼和浩特"): (40.8426, 111.7492),
    ("甘肃", "兰州"): (36.0611, 103.8343),
    ("新疆", "乌鲁木齐"): (43.8256, 87.6168),
    ("海南", "海口"): (20.0440, 110.1999),
    ("香港", "香港"): (22.3193, 114.1694),
    ("澳门", "澳门"): (22.1987, 113.5439),
    ("台湾", "台北"): (25.0330, 121.5654),
    ("新加坡", "新加坡"): (1.3521, 103.8198),
    ("日本", "东京"): (35.6762, 139.6503),
    ("美国", "洛杉矶"): (34.0522, -118.2437),
    ("美国", "旧金山"): (37.7749, -122.4194),
    ("英国", "伦敦"): (51.5074, -0.1278),
}


def _is_private(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved


def _get_searcher():
    """懒加载 ip2region Searcher（整库读进内存，约 11MB）；缺库/缺依赖返回 None。"""
    global _searcher
    if _searcher is not None:
        return _searcher
    path = getattr(settings, "IP2REGION_DB", "")
    if not path or not os.path.exists(path):
        return None
    try:
        from ip2region import util
        from ip2region.searcher import Searcher

        with open(path, "rb") as fh:
            buffer = fh.read()
        _searcher = Searcher(util.IPv4, None, None, buffer)
    except Exception:
        # 库文件损坏 / 依赖缺失 → 静默降级，不影响登录流程
        return None
    return _searcher


def _strip(name: str, suffixes: tuple[str, ...]) -> str:
    for suffix in suffixes:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return name


def _search_ip2region(ip: str) -> tuple[str, str, str] | None:
    """ip2region xdb 查询，返回归一化后的 (国家, 省, 市)。

    数据格式：``国家|省|市|ISP|ISO``，如 ``中国|江苏省|南京市|0|CN``。
    库文件缺失 / 查询失败 / 保留地址 → None（上层只记录 IP）。
    """
    searcher = _get_searcher()
    if searcher is None:
        return None
    try:
        region = searcher.search(ip)
    except Exception:
        return None
    if not region:
        return None

    parts = region.split("|")
    if len(parts) < 3:
        return None
    country, province, city = (p.strip() for p in parts[:3])
    if country in {"", "0", "Reserved"}:
        return None

    province = "" if province in {"", "0"} else _strip(province, _REGION_SUFFIXES)
    city = "" if city in {"", "0"} else _strip(city, _CITY_SUFFIXES)
    return country, province, city


def geolocate(ip: str | None) -> dict:
    """IP → {city, region, country, latitude, longitude}；无法定位时返回空值。"""
    result = dict(_EMPTY)
    if not ip or _is_private(ip):
        return result

    found = _search_ip2region(ip)
    if not found:
        return result

    country, region, city = found
    result["country"] = country or ""
    result["region"] = region or ""
    result["city"] = city or ""
    coords = _CITY_COORDS.get((region, city)) or _CITY_COORDS.get((city, city))
    if coords:
        result["latitude"], result["longitude"] = coords
    return result
