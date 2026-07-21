"""业务服务层（占位）。

类比 Spring Boot 的 @Service：业务编排逻辑集中在此层。
本层不依赖 FastAPI / httpx，入参出参用 model/ 里的 DTO，
保证后续接 ROS 时业务逻辑一行不用改。
"""
