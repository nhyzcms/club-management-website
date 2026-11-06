"""新闻封面缩略图：上传时生成小图（列表 / 卡片用，省流量）。

- 宽 ≤ 800px（列表最大显示约 600px，留 @2x 余量），保持原比例不裁剪
- EXIF 方向转正（手机拍照）；透明底合成白底；统一输出 JPEG
- 解码失败返回 None：调用方回退原图，不阻断上传
"""
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

THUMB_MAX_WIDTH = 800
_THUMB_QUALITY = 82

#: 封面解码的像素上限（审计 #279）。
#:
#: 原先这里没有任何守卫，唯一的限制是 ``panorama/tiling.py`` 里那句
#: ``Image.MAX_IMAGE_PIXELS = 200_000_000`` ——那是**全局副作用**，靠 import
#: 顺序生效。新 worker 的第一个请求恰好是新闻封面上传（或部署裁掉 panorama）
#: 时，阈值就是 Pillow 默认的 89MP；即便 200MP 生效，200MP × 3 通道 = 600MB
#: 起步，``exif_transpose`` 可能再复制一份，LANCZOS 缩放峰值更高，而生产是
#: 单 worker ——一次 OOM 整站 502。
#:
#: 40MP 足够覆盖 8000×5000 的手机 / 相机原图；超限直接不生成缩略图
#: （调用方回退原图，上传本身不受影响）。
MAX_COVER_PIXELS = 40_000_000


def make_cover_thumbnail(uploaded_file) -> ContentFile | None:
    """从封面文件生成缩略图；任何解码 / 处理失败都返回 None。

    像素数在 ``Image.open`` 之后、``exif_transpose`` 之前判断：``open()`` 只读
    文件头、不解码像素，而 ``exif_transpose`` 会强制解码全部像素——守卫必须
    落在两者之间，否则内存已经吃掉了。
    """
    try:
        uploaded_file.seek(0)
        img = Image.open(uploaded_file)
        if img.width * img.height > MAX_COVER_PIXELS:
            return None
        img = ImageOps.exif_transpose(img)
        if img.width > THUMB_MAX_WIDTH:
            height = round(img.height * THUMB_MAX_WIDTH / img.width)
            img = img.resize((THUMB_MAX_WIDTH, height), Image.Resampling.LANCZOS)
        # 透明底 → 白底（JPEG 不支持透明）
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=_THUMB_QUALITY, optimize=True)
        return ContentFile(buf.getvalue())
    except Exception:
        return None
