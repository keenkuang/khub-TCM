"""适配器工厂：按 type 名懒加载适配器实例。"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import SourceAdapter

_ADAPTER_REGISTRY: dict[str, str] = {
    # type_name → 模块路径（惰性导入用）
    "feishu": "khub.adapters.feishu",
    # "yuque": "khub.adapters.yuque",          # future
    # "confluence": "khub.adapters.confluence",  # future
}


def list_adapters() -> list[str]:
    """返回所有注册的适配器名称。"""
    return list(_ADAPTER_REGISTRY.keys())


def create_adapter(source_type: str, **kwargs) -> "SourceAdapter":
    """按 type 名创建适配器实例。

    惰性导入：只在首次使用时加载对应模块。

    Args:
        source_type: 适配器名称，如 "feishu"。
        **kwargs: 透传给适配器构造函数的参数。

    Returns:
        SourceAdapter 实例。

    Raises:
        ValueError: 未知的 source_type 或模块中未找到适配器类。
    """
    if source_type not in _ADAPTER_REGISTRY:
        raise ValueError(
            f"未知数据源类型：{source_type}。"
            f"已注册：{', '.join(list_adapters())}"
        )

    mod_path = _ADAPTER_REGISTRY[source_type]
    mod = importlib.import_module(mod_path)

    # 约定：适配器类名为 {Type}Adapter，如 FeishuAdapter
    cls_name = f"{source_type.capitalize()}Adapter"
    cls = getattr(mod, cls_name, None)
    if cls is None:
        # 兜底尝试最后一个单词大写 + Adapter
        parts = source_type.split("_")
        cls_name = "".join(p.capitalize() for p in parts) + "Adapter"
        cls = getattr(mod, cls_name, None)

    if cls is None:
        raise ValueError(f"模块 {mod_path} 中未找到适配器类")

    return cls(**kwargs)
