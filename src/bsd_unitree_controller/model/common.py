"""通用数据模型（VO / DTO）。

放置跨模块复用的出参入参结构，如健康检查 VO。
具体业务模块的 DTO/VO 放到各自业务子包下。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HealthVO(BaseModel):
    """健康检查返回数据。"""

    model_config = ConfigDict(from_attributes=True)

    status: str   # 服务状态，"up" 表示正常
