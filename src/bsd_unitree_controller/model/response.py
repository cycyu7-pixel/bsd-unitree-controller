"""统一返回结果 Result<T> 与分页结果 PageResult<T>。

类比 Java 项目里的 com.xxx.common.Result<T>：
所有接口统一返回 { code, message, data } 结构，
错误码集中在 code 字段，data 为业务数据。

约定：
    - code = 1  表示成功
    - code != 1 表示失败（0 为通用失败码，其它数字为具体业务错误码）
    - HTTP 状态码统一返回 200，由 code 区分业务结果
"""
from __future__ import annotations

from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class Result(BaseModel, Generic[T]):
    """统一返回结果。

    Attributes:
        code: 业务状态码，1 表示成功，非 1 表示失败。
        message: 提示信息，成功为 "success"，失败为错误描述。
        data: 业务数据，成功时携带，失败时一般为 None。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    code: int = 1                          # 业务状态码：1 成功，非 1 失败
    message: str = "success"               # 提示信息
    data: Optional[T] = None               # 业务数据

    # ── 成功构造方法 ────────────────────────────────────────────────

    @classmethod
    def ok(cls, data: Any = None, message: str = "success") -> "Result[T]":
        """成功返回。

        Args:
            data: 业务数据，无数据时省略。
            message: 提示信息，默认 "success"。

        Returns:
            code=1 的 Result 实例。
        """
        return cls(code=1, message=message, data=data)

    # ── 失败构造方法 ────────────────────────────────────────────────

    @classmethod
    def fail(cls, code: int = 0, message: str = "fail", data: Any = None) -> "Result[T]":
        """失败返回。

        Args:
            code: 业务错误码，0 为通用失败，其它为具体业务错误码。
            message: 错误提示信息。
            data: 附加数据，一般不传。

        Returns:
            失败的 Result 实例。
        """
        return cls(code=code, message=message, data=data)


class PageResult(BaseModel, Generic[T]):
    """分页查询结果。

    配合 `Result[PageResult[XxxVO]]` 使用，所有分页接口统一返回该结构。

    Attributes:
        total: 总记录数。
        page: 当前页码，从 1 开始。
        pageSize: 每页记录数。
        records: 当前页数据列表。
    """

    total: int              # 总记录数
    page: int               # 当前页码
    pageSize: int           # 每页记录数
    records: List[T]        # 当前页数据
