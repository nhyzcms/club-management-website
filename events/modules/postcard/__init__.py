"""明信片互寄（events 形态模块）。

方案与交接文档：``docs/plans/postcard-exchange.md``。子模块：

- ``models``   数据模型（app_label="events"）
- ``state``    活动 5 阶段状态机（时间惰性推导）
- ``barcode``  条码生成 + A4 整版 PDF
- ``photos``   照片安全管线（魔数/重编码/私有存储）
- ``exports``  Excel / PDF 导出（公式注入防护 / 中文字体）
- ``views``    公开与管理端点
- ``serializers`` / ``permissions`` / ``throttles`` / ``urls``

PR2（AI 与复核）将新增 ``ai``（OpenAI 兼容客户端）与复核台端点。
"""
