"""AGV 调度入参 DTO。

所有字段可选，不传时用代码里的默认值。
传了就用传入的，方便在 Swagger 或前端临时调整参数。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class AgvCallDTO(BaseModel):
    """呼叫 AGV 入参。

    不传任何字段时，用配置和写死的默认值。
    传了对应字段就用传入的值覆盖默认值。
    """

    barcode: str | None = Field(None, description="条码，默认空字符串")
    podCategory: str | None = Field(None, description="货架类别，默认 '1'")
    workstation: str | None = Field(None, description="工位号，默认从配置读取")


class AgvReturnDTO(BaseModel):
    """AGV 返库入参。

    不传任何字段时，用缓存和配置的默认值。
    传了对应字段就用传入的值覆盖默认值。
    container 不传时用到位回调缓存的值。
    """

    podCategory: str | None = Field(None, description="货架类别，默认空字符串")
    podNo: str | None = Field(None, description="容器/货架编号，默认用到位回调缓存的 container")
    type: str | None = Field(None, description="类型，默认 'FK'")
    workstationNo: str | None = Field(None, description="工位号，默认从配置读取")
