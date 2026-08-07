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

    barcode: str | None = Field(default="", description="条码，默认空字符串")
    podCategory: str | None = Field(default="", description="货架类别，默认空字符串")
    workstation: str | None = Field(default="", description="工位号，默认空字符串，不传则从配置读取")


class AgvReturnDTO(BaseModel):
    """AGV 返库入参。

    不传任何字段时，用缓存和配置的默认值。
    传了对应字段就用传入的值覆盖默认值。
    container 不传时用到位回调缓存的值。
    """

    podCategory: str | None = Field(default="", description="货架类别，默认空字符串")
    podNo: str | None = Field(default="", description="容器/货架编号，默认用到位回调缓存的 container")
    type: str | None = Field(default="", description="类型，默认 'FK'")
    workstationNo: str | None = Field(default="", description="工位号，默认空字符串，不传则从配置读取")


class EpcCallbackDTO(BaseModel):
    """EPC 扫描回调入参（对应 RFID 服务的 ScanCallbackVO）。

    当 RFID 读写器扫描到 EPC 条码，或超时失败时，RFID 服务会回调本系统。
    成功时：error 为 null，epc 为条码值。
    失败时：error 不为 null，epc 为 null（如超时 35s 未读到 EPC）。
    """

    requestId: str = Field(default="", description="发起扫描时返回的唯一请求 ID")
    epc: str | None = Field(default=None, description="扫描到的 EPC 条码，失败时为 null")
    error: str | None = Field(default=None, description="错误信息，成功时为 null")
