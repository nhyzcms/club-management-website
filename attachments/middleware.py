"""在 drf-tus 解析请求头之前拦掉畸形的 tus 数字头（审计 #273）。

``rest_framework_tus`` 2.0.3 的 ``TusMiddleware.parse_upload_length`` 直接
``int(upload_length)``，没有 try/except；而它挂在 ``MIDDLEWARE`` 里、
早于 DRF 视图与 ``permission_classes``。于是匿名请求带
``Upload-Length: abc`` 会稳定打出 500——不是权限问题，是「异常发生在
鉴权之前」，``TusUploadViewSet.create`` 里那几行 ``None / < 0`` 校验根本
跑不到。

第三方包不改（升级不解决：PyPI 最新仍是 2.0.3；vendor 一份补丁要维护
fork），改在这层薄中间件里拦：tus 规范里畸形头本来就是客户端错误，
回 400 比 500 正确，而且它比 ``TusMiddleware`` 更早执行，天然覆盖
「未认证也能触发」这条路径。

**只校验格式，不校验业务**：大小上限、必填、权限仍在视图里判——
这层出现第二个职责就会变成第二个真源。
"""
from django.http import JsonResponse

#: drf-tus 会直接 ``int()`` 的头。Upload-Length 决定总长度，
#: Upload-Offset 决定续写位置，两个都是「必须非负整数」。
_NUMERIC_HEADERS = ("Upload-Length", "Upload-Offset")


def _meta_key(header: str) -> str:
    return "HTTP_" + header.upper().replace("-", "_")


class TusHeaderValidationMiddleware:
    """tus 数字头格式闸门：非数字 → 400（早于 TusMiddleware）。

    **不判路径**。第三方的 ``TusMiddleware.process_request`` 对所有请求都调
    ``parse_upload_length`` / ``parse_upload_offset``（不看 URL 是否 tus 端点），
    所以 ``Upload-Length: abc`` 打在 ``/site-policy/`` 上同样是 500——按路径
    只放行 ``/uploads/`` 会留下这个更宽的触发面。只带 tus 头的请求才会被检查，
    正常浏览器请求不受影响。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        for header in _NUMERIC_HEADERS:
            raw = request.META.get(_meta_key(header))
            if raw is None:
                continue
            value = raw.strip()
            # ``str.isdigit()`` 拒绝空串、负数、小数、科学计数法、
            # 十六进制与任何字母；HTTP 头本身不该带前后空白，strip 只是
            # 容忍某些客户端的序列化习惯。
            #
            # 长度上限同样必需：Python 3.11+ 的 ``int()`` 对超过 4300 位的
            # 十进制串抛 ``ValueError``，而 TusMiddleware 没有 try/except——
            # 只判 isdigit 的话，一个 5000 位的数字串仍然会打出 500。
            # 20 位已远超 2^63 字节，任何真实上传都用不到。
            if not value.isdigit() or len(value) > 20:
                response = JsonResponse(
                    {"detail": f"{header} 必须是非负整数。"}, status=400,
                )
                # tus 客户端按协议版本判定响应是否属于 tus 端点。
                response["Tus-Resumable"] = "1.0.0"
                return response
        return self.get_response(request)
