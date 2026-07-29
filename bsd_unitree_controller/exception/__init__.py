"""异常定义与全局异常处理。

类比 Spring Boot 的自定义业务异常 + @ControllerAdvice 全局异常处理器。
所有业务异常统一抛 BizException（或其子类），全局处理器统一转成 Result.fail()。
"""
