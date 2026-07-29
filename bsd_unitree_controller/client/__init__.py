"""出站 HTTP 客户端层。

类比 Spring Boot 的 FeignClient / RestTemplate：
封装对上游系统的 HTTP 调用，统一处理超时、重试、日志、异常包装。
业务层（service/）只调本层方法，不直接碰 httpx。
"""
