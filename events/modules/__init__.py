"""活动形态模块（预留，框架阶段只落约定与空目录）。

每个具体活动形态一个子包，如 ``postcard/``::

    events/modules/postcard/
        __init__.py
        models.py      # Meta.app_label = "events"
        service.py     # 配对 / 状态流转等纯领域逻辑
        views.py       # 该形态的参与接口

约定：

- 模型定义在模块内、``app_label`` 指向 ``events``，迁移集中在 ``events/migrations/``。
  Django 允许模型类定义在任意模块，只要 ``app_label`` 指向已安装的 app——这样
  新增一种形态不需要改 ``INSTALLED_APPS``，也就不会把「加一个活动」变成「加一个
  Django app」。
- ``Event.module_key`` 指向模块包名；留空 = 纯展示型活动，不加载任何模块。
- 模块的**所有写入口**必须先调 ``events.lifecycle.touch()``，再判
  ``can_participate()``——否则「到点后还能写」会从新模块漏出去，而这正是活动
  与互动最重要的差异。
- 模块之间不互相 import；共享逻辑上移到本包的 service 层或独立小模块，等第二个
  形态出现时再抽（避免为一次实现造通用引擎）。
"""
