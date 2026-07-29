from setuptools import setup, find_packages

package_name = "bsd_unitree_controller"

setup(
    name=package_name,
    version="0.2.0",
    # 自动发现所有子包（bsd_unitree_controller/api/v1 等）
    packages=find_packages(exclude=["tests", "tests.*"]),
    # pip 依赖（ROS 依赖在 package.xml 声明）
    install_requires=[
        "setuptools",
        "fastapi",
        "uvicorn[standard]",
        "httpx",
        "tenacity",
        "pydantic",
        "pyyaml",
        "loguru",
    ],
    zip_safe=True,
    maintainer="cyu",
    maintainer_email="cyu@bsdits.com",
    description="宇树 G1 机器人控制流程系统",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            # ros2 run bsd_unitree_controller controller 启动节点
            "controller = bsd_unitree_controller.main:main",
        ],
    },
)
