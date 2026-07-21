"""业务异常定义。

类比 Java 项目里的 BusinessException，带业务错误码和提示信息。
全局处理器会捕获这些异常并转成统一返回结构 Result.fail()。

约定：
    - 所有业务异常继承 BizException
    - code != 1 视为失败（1 是 Result.ok 的成功码）
    - HTTP 状态码统一返回 200，由 code 区分业务结果
"""
from __future__ import annotations


class BizException(Exception):
    """业务异常基类。

    Attributes:
        code: 业务错误码（非 1）。0 为通用失败，其它为具体业务错误码。
        message: 错误提示信息。
    """

    def __init__(self, code: int, message: str):
        self.code: int = code
        self.message: str = message
        super().__init__(f"[{code}] {message}")


class ParamException(BizException):
    """参数校验异常（如必填字段缺失、格式不合法）。"""

    def __init__(self, message: str = "参数错误"):
        super().__init__(code=400, message=message)


class TaskAlreadyExistsException(BizException):
    """任务已存在异常（重复下发同一 task_id）。"""

    def __init__(self, task_id: str):
        super().__init__(code=40901, message=f"任务已存在: {task_id}")


class UpstreamException(BizException):
    """上游系统调用异常（出站 HTTP 调用失败时抛）。

    HTTP 4xx/5xx 或重试用尽后抛出。
    """

    def __init__(self, message: str = "上游系统调用失败"):
        super().__init__(code=50001, message=message)
