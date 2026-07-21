"""ROS 通信层。

类比 Spring Boot 里负责与外部系统通信的 @Component：本层只做 ROS 消息
<-> DTO 翻译，调 service 层处理业务逻辑，不依赖 FastAPI。

rclpy 作为软依赖：Windows 开发机不装 rclpy 时本模块仍可 import，
运行时通过 is_ros_available() 判断是否启用 ROS 功能。
"""
