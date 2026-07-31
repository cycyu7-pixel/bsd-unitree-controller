# bsd-unitree-controller

宇树 G1 机器人控制流程系统。对外提供 HTTP 接口（FastAPI），对内通过 ROS 2 节点与机器人其他节点通信。采用分层架构，HTTP 入口和 ROS 入口共享 service 层业务逻辑，零冗余。

已部署到宇树 G1 机器人（unitree-g1-nx）并验证通过。

## 1. 这个项目做什么

**一句话定位**：跑在宇树 G1 机器人本体上的控制流程系统，对外提供 HTTP 接口，对内通过 ROS 2 与急停等节点通信。

**当前已实现**：
- 规范的 FastAPI 分层骨架（启动、配置、异常、统一返回）
- 带重试的 HTTP 客户端封装（httpx + tenacity）
- ROS 2 节点封装（rclpy 软依赖，单进程双线程）
- 存活检查：HTTP `/api/v1/alive` + ROS service `/controller/is_alive` 共享 HealthService
- 急停控制：HTTP `/api/v1/estop/trigger` -> ROS service `/g1/estop/trigger`（service call 模式）
- systemd 部署：开机自启 + 崩溃自动重启

**不包含**：
- 数据库、消息队列
- 运动控制、具体业务接口（后续按需添加）

## 2. 工作原理

单进程双线程架构：FastAPI/uvicorn 跑主线程，rclpy.spin 跑后台 daemon 线程。HTTP 接口和 ROS 通信共享 `app.state`，互不阻塞。

```text
              外部调用方（App / 上位机 / 运维）
                  │ HTTP
                  ▼
┌─────────────────────────────────────────────────┐
│ 单进程（systemd 管理）                            │
│  ┌──────────────────────────────┐                │
│  │ uvicorn（主线程）             │                │
│  │  FastAPI app                  │                │
│  │   /api/v1/test    健康检查    │                │
│  │   /api/v1/alive   存活检查    │ ← HTTP 接口    │
│  │   /api/v1/estop/trigger 急停  │                │
│  └──────┬────────────┬───────────┘                │
│         │ Depends    │ Depends                    │
│   (get_http_client)  (get_ros_node)               │
│         ▼            ▼                            │
│  ┌────────────┐  ┌──────────────────────┐        │
│  │ HttpClient │  │ rclpy.spin           │        │
│  │ 出站 HTTP   │  │ (daemon 线程)        │        │
│  └────────────┘  │ ControllerNode       │        │
│                  │  /g1/estop client    │        │
│                  │  ~/is_alive server   │        │
│                  └──────────┬───────────┘        │
└─────────────────────────────┼────────────────────┘
                              │ ROS topic/service
                              ▼
                    [机器人其他 ROS 节点]
                    运动控制 / 急停 / 状态
```

### 分层架构（核心设计）

业务逻辑放 `service/` 层，HTTP 和 ROS 只是两个不同的入口，都调同一个 service。逻辑只写一遍，零冗余。

```text
        ┌─────────────┐         ┌─────────────┐
HTTP  -> │ HTTP 入口   │         │ ROS 入口    │  ← 入口层薄如纸
        │ api/v1/...  │         │ ros/node.py │     只做翻译
        └──────┬──────┘         └──────┬──────┘
               │                       │
               └───────────┬───────────┘
                           ▼
                   ┌───────────────┐
                   │  service/ 层  │  ← 业务层厚如山
                   │  纯 Python    │     业务逻辑唯一真相源
                   └───────┬───────┘
                           │ 依赖注入（Protocol）
                           ▼
                   ┌───────────────┐
                   │  ControllerNode│ ← ROS 通信层
                   └───────────────┘
```

启动到运行的步骤：

1. `main.py` 加载 `config/config.yaml`，应用环境变量覆盖
2. 初始化 loguru 日志（控制台 + 文件）
3. `api/server.py` 的 `create_app` 装配 FastAPI app，`lifespan` 启动段执行：
   - 创建 HttpClient 挂到 `app.state.http_client`
   - 若 `config.ros.enabled=true` 且 rclpy 可用：`rclpy.init()` + 创建 ControllerNode + 起 daemon 线程跑 `rclpy.spin`，挂到 `app.state.ros_node`
   - 否则跳过 ROS，纯 HTTP 模式
4. uvicorn 监听端口，开始接收 HTTP 请求
5. 接口层通过 `Depends(get_http_client)` 或 `Depends(get_ros_node)` 取依赖，调 service 层
6. 返回 `Result.ok()` 给调用方（`code=1` 表示成功）

## 3. 快速开始

### 环境要求

| 项 | 版本 | 说明 |
| --- | --- | --- |
| Python | >= 3.10 | 兼容 ROS Humble（3.10）和开发机（3.11+） |
| uv | 任意版本 | 开发机依赖管理 |
| ROS Humble | 可选 | 部署到机器人需要，开发机不需要 |

### 开发机（无 ROS）

```bash
# 安装依赖
uv sync

# 启动（开发机无 rclpy，自动降级为纯 HTTP 模式）
uv run python -m bsd_unitree_controller.main

# 或用 uvicorn 热重载
uv run uvicorn bsd_unitree_controller.main:app --reload --host 0.0.0.0 --port 18800
```

### 机器人（ROS package 方式）

```bash
# 1. 把包放到 ROS 工作空间
cp -r ~/bsd-unitree-controller ~/unitree_ros2_ws/src/bsd_unitree_controller

# 2. colcon 编译
cd ~/unitree_ros2_ws
colcon build --packages-select bsd_unitree_controller

# 3. source 后启动
source ~/unitree_ros2_ws/install/setup.bash
ros2 run bsd_unitree_controller controller
```

启动后可见日志：`ControllerNode 已启动` + `Uvicorn running on http://0.0.0.0:18800`

### 运行测试

```bash
uv sync --extra dev
uv run pytest tests/ -v   # 16 个测试用例
```

启动后访问接口文档：http://127.0.0.1:18800/docs

### 机器人部署

见 [第 10 节 部署与运维](#10-部署与运维)。

## 4. 工程结构

标准 ROS package（ament_python 布局），包目录直接在项目根下。

```text
bsd-unitree-controller/
├── package.xml                 # ROS 包描述（声明 ROS 依赖）
├── setup.py                    # Python 包安装配置（pip 依赖 + entry_points）
├── setup.cfg                   # 脚本安装路径
├── pyproject.toml              # 依赖声明（uv 管理，开发用）
├── deploy.sh                   # 部署管理脚本（install/start/stop/logs）
├── scripts/                    # 部署相关脚本
│   ├── ros_env.sh              #   ROS 环境变量配置（source 用）
│   ├── start.sh                #   启动脚本（systemd 调用）
│   └── bsd-controller.service  #   systemd 服务配置（开机自启）
├── config/
│   └── config.yaml             # 配置文件（类比 application.yml）
├── bsd_unitree_controller/     # ROS package 包目录（ament_python 布局）
│   ├── __init__.py
│   ├── main.py                 #   启动入口（ros2 run 调用）
│   ├── core/                   #   核心基础设施
│   │   ├── config.py           #     配置加载 + 环境变量覆盖 + 多路径查找
│   │   └── deps.py             #     公共依赖（get_http_client / get_ros_node）
│   ├── api/                    #   对外 HTTP 入口（@RestController）
│   │   ├── __init__.py         #     api_router 汇总（加 /api/v1 前缀）
│   │   ├── server.py           #     FastAPI app 装配 + lifespan（含 ROS 生命周期）
│   │   └── v1/                 #     v1 版本路由
│   │       ├── __init__.py     #       v1_router 汇总
│   │       ├── controller.py   #       机器人本体控制（健康检查/存活/急停）
│   │       └── agv.py          #       AGV 调度（呼叫/到位回调）
│   ├── service/                #   业务逻辑层（@Service，不依赖框架）
│   │   ├── controller_service.py #    存活检查 + 急停业务逻辑
│   │   └── agv_service.py      #     AGV 呼叫 + 到位回调业务逻辑
│   ├── client/                 #   出站 HTTP（@FeignClient）
│   │   └── http_client.py      #     httpx + tenacity 封装
│   ├── ros/                    #   对内 ROS 通信（软依赖 rclpy）
│   │   └── node.py             #     ControllerNode + 生命周期函数
│   ├── model/                  #   数据模型
│   │   ├── response.py         #     Result<T> / PageResult<T>
│   │   └── common.py           #     HealthVO 等通用 VO
│   ├── exception/              #   业务异常 + 全局处理器
│   │   ├── exceptions.py       #     BizException 等
│   │   └── handlers.py         #     @ControllerAdvice
│   └── utils/
│       └── logging.py          #     loguru 日志初始化
└── tests/                      # 测试（pytest + TestClient）
    ├── test_controller.py
    └── test_agv.py
```

| 路径 | 职责 |
| --- | --- |
| `main.py` | 启动入口，业务逻辑永远不写在这 |
| `deploy.sh` | 部署管理（install/start/stop/restart/status/logs/uninstall） |
| `scripts/ros_env.sh` | ROS 环境变量配置，source 后 rclpy/unitree_api 可用 |
| `scripts/start.sh` | 启动脚本，systemd 调用它 |
| `scripts/bsd-controller.service` | systemd 配置，开机自启 + 崩溃重启 |
| `core/config.py` | 配置加载，yaml + 环境变量覆盖 |
| `core/deps.py` | 公共依赖项，路由通过 `Depends` 取 |
| `api/server.py` | 装配 app、lifespan 管理 HttpClient + ROS 生命周期 |
| `api/v1/controller.py` | 机器人本体控制：健康检查、存活检查、ROS 状态、急停 |
| `service/controller_service.py` | 存活检查 + 急停业务逻辑（HTTP + ROS 共享） |
| `client/http_client.py` | 出站 HTTP 调用，通用 get/post |
| `ros/node.py` | ControllerNode，含 service server/service client |
| `model/response.py` | `Result<T>` / `PageResult<T>` 统一返回 |
| `model/common.py` | HealthVO 等通用 VO |
| `exception/exceptions.py` | 业务异常定义 |
| `exception/handlers.py` | 全局异常处理器 |
| `config/config.yaml` | 配置文件 |

### 分层调用规则（铁律）

1. `service/` **不 import** `fastapi` / `httpx` / `rclpy`，业务逻辑要能脱离框架单测
2. `api/` 不直接调 `client/`，必须经过 `service/`
3. `api/` 和 `ros/` 不写业务，只做翻译（HTTP <-> DTO / ROS 消息 <-> DTO）
4. 入口层薄如纸（只做参数接收、依赖注入、调 service、包装返回），业务层厚如山

## 5. 配置说明

配置文件位置：`config/config.yaml`

```yaml
# 服务（FastAPI）配置
server:
  host: "0.0.0.0"
  port: 18800

# 出站 HTTP 调用通用配置
upstream:
  timeout: 10
  retry: 2

# 日志配置
log:
  level: "INFO"
  dir: "logs"

# ROS 节点配置
ros:
  enabled: true
  node_name: "controller"
```

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `server.host` | `0.0.0.0` | 监听地址 |
| `server.port` | `18800` | 监听端口 |
| `upstream.timeout` | `10` | 出站 HTTP 超时（秒） |
| `upstream.retry` | `2` | 重试次数（不含首次） |
| `log.level` | `INFO` | 日志级别 |
| `log.dir` | `logs` | 日志文件目录，为空只输出控制台 |
| `ros.enabled` | `true` | 是否启用 ROS 节点，false 则纯 HTTP 模式 |
| `ros.node_name` | `controller` | ROS 节点名 |

### 环境变量覆盖

yaml 里的任何字段都能被环境变量覆盖，**优先级高于配置文件**。规则：前缀 `BSD_`，嵌套用 `__` 分隔，字段名转小写。

| 环境变量 | 覆盖字段 | 示例值 |
| --- | --- | --- |
| `BSD_SERVER__HOST` | `server.host` | `127.0.0.1` |
| `BSD_SERVER__PORT` | `server.port` | `9000` |
| `BSD_UPSTREAM__TIMEOUT` | `upstream.timeout` | `5` |
| `BSD_ROS__ENABLED` | `ros.enabled` | `false` |
| `BSD_ROS__NODE_NAME` | `ros.node_name` | `my_controller` |

```bash
# 开发机关闭 ROS
BSD_ROS__ENABLED=false uv run python main.py
```

## 6. REST 接口

所有接口统一返回 `Result`：`{"code":1成功/非1失败, "message":"...", "data":...}`。HTTP 状态码统一 200，看 `code` 字段区分业务结果。

### `GET /api/v1/test` - 健康检查

```bash
curl http://127.0.0.1:18800/api/v1/test
```
```json
{"code": 1, "message": "success", "data": {"status": "up"}}
```

### `GET /api/v1/alive` - 节点存活检查

走 service 层，HTTP 和 ROS service `/controller/is_alive` 共享 `HealthService`。

```bash
curl http://127.0.0.1:18800/api/v1/alive
```
```json
{"code": 1, "data": {"status": "alive", "node_name": "controller", "timestamp": "..."}}
```

### `GET /api/v1/ros/status` - ROS 节点状态

```bash
curl http://127.0.0.1:18800/api/v1/ros/status
```
```json
{"code": 1, "data": {"status": "alive", "node_name": "controller"}}
```

### `POST /api/v1/estop/trigger` - 急停控制（service call 模式）

触发机器人急停，经 service 层调用 ROS service `/g1/estop/trigger`。

```bash
curl -X POST http://127.0.0.1:18800/api/v1/estop/trigger
```
```json
{"code": 1, "data": {"success": true, "message": "..."}}
```

### 错误码

| code | 含义 |
| --- | --- |
| `1` | 成功 |
| `0` | 通用失败 |
| `400` | 参数校验失败 |
| `50001` | HTTP 调用失败（重试用尽或返回非 2xx） |
| `50002` | ROS 未启用（rclpy 未装或配置禁用） |
| `50003` | ROS service 调用失败 |
| `500` | 服务器内部错误 |

## 7. ROS 接口

机器人内部其他节点与本服务通信的 ROS 接口。

### ControllerNode 注册的 ROS 接口

| 类型 | 名称 | 消息类型 | 方向 | 用途 |
| --- | --- | --- | --- | --- |
| service | `/controller/is_alive` | `std_srvs/Trigger` | server | 存活检查 |
| service | `/g1/estop/trigger` | `std_srvs/Trigger` | client | 急停控制 |

### 调用方式

```bash
# source ROS 环境
source ~/bsd-unitree-controller/scripts/ros_env.sh

# 1. 查看节点
ros2 node list | grep controller
# -> /controller

# 2. 调用存活检查 service
ros2 service call /controller/is_alive std_srvs/srv/Trigger
# -> success=True, message='alive|node=controller|ts=...'

# 3. 查看节点注册的所有接口
ros2 node info /controller
```

### 其他 ROS 节点调用本服务（Python 示例）

```python
import rclpy
from rclpy.node import Node
from std_srvs.srv import Trigger

class CallerNode(Node):
    def __init__(self):
        super().__init__("caller")
        # 创建 client，指向本服务的 is_alive service
        self._client = self.create_client(Trigger, "/controller/is_alive")
        self._client.wait_for_service()

    def check_alive(self):
        future = self._client.call_async(Trigger.Request())
        rclpy.spin_until_future_complete(self, future)
        return future.result().success  # True=活的
```

### ROS service 调用模式

本项目的急停控制采用 ROS service call 模式（请求-响应）：

| 项 | 说明 |
| --- | --- |
| ROS 通信方式 | service call（请求-响应） |
| node 方法 | `trigger_estop()` async |
| service 方法 | `execute_estop()` async |
| 路由 | `async def` 异步 |
| 等待方式 | `asyncio.to_thread` + `spin_until_future_complete`，不阻塞 event loop |

后续若接入 topic publish 模式（如运动控制），node 方法用同步 `publish()`，路由用 `def`。

## 8. HTTP 客户端封装

`client/http_client.py` 是通用 HTTP 工具类，只提供 `get()` / `post()`，不写业务逻辑。

```python
@router.get("/users")
def list_users(client: HttpClient = Depends(get_http_client)) -> Result[dict]:
    resp = client.get("http://user-service:9000/users", params={"page": 1})
    return Result.ok(data=resp.json())

@router.post("/users")
def create_user(client: HttpClient = Depends(get_http_client)) -> Result[dict]:
    resp = client.post("http://user-service:9000/users", json={"name": "张三"})
    return Result.ok(data=resp.json())
```

| 方法 | 参数 | 说明 |
| --- | --- | --- |
| `client.get(url, *, params, headers)` | 完整 URL + query + 请求头 | 返回 `httpx.Response` |
| `client.post(url, *, json, data, params, headers)` | 完整 URL + body + query + 请求头 | 返回 `httpx.Response` |

URL 必须传完整地址（带 `http(s)://`），业务代码自行硬编码各上游地址。

### 重试行为

| 错误类型 | 是否重试 | 说明 |
| --- | --- | --- |
| 连接失败 / 超时 | ✅ | 重试 `upstream.retry` 次，指数退避 |
| HTTP 4xx / 5xx | ❌ | 业务错误，不重试直接抛 `UpstreamException` |

## 9. 日志查看

### 实时日志

```bash
# systemd 日志（实时跟踪）
./deploy.sh logs

# 或直接用 journalctl
journalctl -u bsd-controller -f
```

### 日志文件

按天轮转，保留 30 天，位置 `logs/app_YYYY-MM-DD.log`。

```bash
# 查看今天的日志
cat ~/bsd-unitree-controller/logs/app_$(date +%Y-%m-%d).log

# 查看错误
grep "ERROR\|WARNING" ~/bsd-unitree-controller/logs/app_$(date +%Y-%m-%d).log
```

### 关键日志含义

| 日志关键词 | 含义 |
| --- | --- |
| `配置加载完成` | 启动成功读到配置 |
| `ControllerNode 已启动` | ROS 节点初始化成功 |
| `ROS 节点已启动，spin 在后台线程运行` | rclpy.spin daemon 线程已起 |
| `急停 service client 已创建` | `/g1/estop/trigger` client 就绪 |
| `已发送急停请求` | 急停 service 请求已发出 |
| `rclpy 未安装，跳过 ROS 节点初始化` | 软依赖降级，纯 HTTP 模式 |
| `业务异常` | 抛出 BizException |
| `未捕获异常` | 出现未预期错误，查堆栈 |

## 10. 部署与运维

### 部署架构

采用**ROS package + colcon 构建** 方案。项目是标准 ROS package（ament_python），放到机器人 ROS 工作空间编译运行。

| 特性 | 实现方式 |
| --- | --- |
| 包管理 | `package.xml` 声明 ROS 依赖，`setup.py` 声明 pip 依赖 |
| 构建 | `colcon build`（ROS 标准） |
| 启动 | `ros2 run bsd_unitree_controller controller` |
| 环境隔离 | `pip3 install --user`，依赖装到 `~/.local/`，不碰系统目录 |
| 开机自启 | systemd `enable`，机器人重启自动恢复 |
| 崩溃重启 | systemd `Restart=always`，5 秒后自动重启 |
| 日志管理 | systemd journal + 文件日志双写 |

### 首次部署

```bash
# 1. 拉代码
cd ~
git clone https://github.com/cycyu7-pixel/bsd-unitree-controller.git

# 2. 把包放到 ROS 工作空间
cp -r ~/bsd-unitree-controller ~/unitree_ros2_ws/src/bsd_unitree_controller

# 3. 装 Python 依赖（清代理避免报错）
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY
cd ~/unitree_ros2_ws/src/bsd_unitree_controller
pip3 install --user fastapi "uvicorn[standard]" httpx tenacity pydantic pyyaml loguru socksio

# 4. colcon 编译
cd ~/unitree_ros2_ws
colcon build --packages-select bsd_unitree_controller

# 5. source 后启动
source ~/unitree_ros2_ws/install/setup.bash
ros2 run bsd_unitree_controller controller
```

### 部署后验证

```bash
# 1. ROS package 识别
source ~/unitree_ros2_ws/install/setup.bash
ros2 pkg list | grep bsd                    # -> bsd_unitree_controller

# 2. ROS 节点注册
ros2 node list | grep controller            # -> /controller

# 3. ROS service 调用
ros2 service call /controller/is_alive std_srvs/srv/Trigger  # -> success=True

# 4. HTTP 接口
curl http://127.0.0.1:18800/api/v1/test     # -> {"code":1,...}
curl http://127.0.0.1:18800/api/v1/alive    # -> status=alive
```

### 更新代码

```bash
# 1. 拉新代码
cd ~/bsd-unitree-controller
git pull

# 2. 同步到工作空间
cp -r ~/bsd-unitree-controller ~/unitree_ros2_ws/src/bsd_unitree_controller

# 3. 重新编译
cd ~/unitree_ros2_ws
colcon build --packages-select bsd_unitree_controller

# 4. 重启服务（如果用 systemd）
sudo systemctl restart bsd-controller
# 或手动重启
source ~/unitree_ros2_ws/install/setup.bash
ros2 run bsd_unitree_controller controller
```

### 开机自启（systemd）

`scripts/bsd-controller.service` 配置开机自启，`ExecStart` 调用 `ros2 run`：

```bash
# 注册 systemd 服务（首次）
sudo cp ~/bsd-unitree-controller/scripts/bsd-controller.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bsd-controller
sudo systemctl start bsd-controller

# 日常管理
sudo systemctl status bsd-controller       # 看状态
sudo systemctl restart bsd-controller      # 重启
journalctl -u bsd-controller -f            # 看日志
```

### 卸载（恢复机器人原样）

```bash
sudo systemctl stop bsd-controller
sudo systemctl disable bsd-controller
sudo rm /etc/systemd/system/bsd-controller.service
rm -rf ~/unitree_ros2_ws/src/bsd_unitree_controller
rm -rf ~/unitree_ros2_ws/install/bsd_unitree_controller
rm -rf ~/unitree_ros2_ws/build/bsd_unitree_controller
pip3 uninstall bsd-unitree-controller fastapi uvicorn httpx tenacity loguru pydantic pyyaml socksio
```

卸载后机器人恢复原样，不影响 ROS 环境和其他节点。

### 开发机部署（无 ROS）

开发机无 rclpy，自动降级为纯 HTTP 模式，ROS 相关接口返回 `code=50002`。

```bash
uv sync
uv run python -m bsd_unitree_controller.main
```

## 11. 改代码后怎么上线

| 改动类型 | 是否需要重装依赖 | 是否需要重启 |
| --- | --- | --- |
| Python 代码 | ❌ | ✅（`./deploy.sh restart`） |
| `pyproject.toml` 加依赖 | ✅（`./deploy.sh install`） | ✅ |
| `config.yaml` 配置 | ❌ | ✅ |
| README 文档 | ❌ | ❌ |

## 12. 二次开发

### 想改什么该往哪写

| 想做的事 | 推荐位置 | 注意事项 |
| --- | --- | --- |
| 加新 HTTP 接口 | `api/v1/controller.py` 加路由，或新建模块在 `api/v1/__init__.py` 汇总 | 只调 service，不写业务 |
| 写业务逻辑 | `service/controller_service.py` 加类，或新建 service 文件 | 不 import fastapi/httpx/rclpy |
| 加 ROS publisher/subscriber | `ros/node.py` 的 `ControllerNode.__init__` | topic 模式，同步 publish |
| 加 ROS service client | `ros/node.py` 的 `ControllerNode` | service call 模式，参考 `trigger_estop` |
| 加 ROS service server | `ros/node.py` 的 `ControllerNode.__init__` | 参考 `~/is_alive` |
| 调外部 HTTP | `client/http_client.py` 已提供 `get`/`post` | 传完整 URL |
| 加新数据结构 | `model/` 下：入参新建 `dto.py`，出参 `common.py` 或新文件 | 用 Pydantic |
| 加新业务异常 | `exception/exceptions.py` 加类 | 继承 `BizException` |
| 改端口/ROS 开关 | `config/config.yaml` 或环境变量 | 改完重启 |

### 加新功能的完整步骤（以"控制头部姿态"为例）

1. **定义 DTO**（`model/dto.py`）：入参结构
2. **写 service**（`service/head_service.py`）：业务逻辑 + 调 node 方法
3. **加 node 方法**（`ros/node.py`）：建 publisher/service，构造 ROS 消息
4. **加 HTTP 路由**（`api/v1/head.py`）：调 service，包装 Result
5. **汇总 router**（`api/v1/__init__.py`）：`v1_router.include_router(...)`

业务逻辑只写一遍（service 层），HTTP 和 ROS 入口零冗余。

## 13. 常见问题排查

### 服务起不来

```bash
./deploy.sh status
./deploy.sh logs
```

常见原因：

| 报错 | 原因 | 解决 |
| --- | --- | --- |
| `PermissionError: logs/` | logs 目录权限不对 | `sudo chown -R unitree:unitree ~/bsd-unitree-controller/logs` |
| `No module named 'fastapi'` | 没装依赖 | `./deploy.sh install` |
| `port is already allocated` | 18800 被占 | `ss -tlnp | grep 18800` 查并 kill |
| pip 报 SOCKS 错误 | 代理干扰 | `unset HTTP_PROXY HTTPS_PROXY ALL_PROXY` |

### ROS 节点看不到 /controller

```bash
ros2 node list | grep controller
```

如果看不到，检查：

1. 启动日志是否有 `ControllerNode 已启动`：`./deploy.sh logs`
2. 是否 source 了 ROS 环境：`source ~/bsd-unitree-controller/scripts/ros_env.sh`
3. DDS 是否一致：`echo $RMW_IMPLEMENTATION`（应为 `rmw_cyclonedds_cpp`）
4. `ROS_DOMAIN_ID` 是否跟其他节点一致（默认 0）

### ROS service 调用超时

```bash
# service 是否注册
ros2 service list | grep is_alive
# service 类型
ros2 service type /controller/is_alive
```

### 开发机 ROS 接口返回 50002

正常现象。开发机无 rclpy，软依赖降级为纯 HTTP 模式。

## 14. 第三方库速查表

| 库 | 用途 | 类比 Java | 关键类/方法 |
| --- | --- | --- | --- |
| `fastapi` | Web 框架 | Spring Boot | `FastAPI`, `APIRouter`, `Depends` |
| `uvicorn` | ASGI 服务器 | 内嵌 Tomcat | `uvicorn.run(app, host, port)` |
| `httpx` | HTTP 客户端 | OkHttp | `httpx.Client`, `.request()` |
| `tenacity` | 重试机制 | Spring Retry | `Retrying`, `stop_after_attempt` |
| `pydantic` | 数据模型与校验 | Bean Validation | `BaseModel`, `Field` |
| `pyyaml` | YAML 解析 | SnakeYAML | `yaml.safe_load` |
| `loguru` | 日志 | Logback / `@Slf4j` | `logger.info()`, `logger.add()` |
| `rclpy` | ROS 2 Python 客户端 | （无 Java 对应） | `Node`, `create_publisher`, `create_service` |

## 15. 命名对照（给 Java 程序员）

| 本项目文件 | Java 圈对应 | 说明 |
| --- | --- | --- |
| `main.py` | `@SpringBootApplication` 启动类 | main 方法 + 模块级 app |
| `api/server.py` | `@Configuration` + 启动装配 | 创建 app、注册路由、lifespan |
| `api/v1/*.py` | `@RestController` | 路由处理 |
| `core/config.py` | `application.yml` + Config 类 | 配置加载 + 环境变量覆盖 |
| `core/deps.py` | 公共 `@Bean` | 公共依赖项 |
| `service/*.py` | `@Service` | 业务编排（纯逻辑，不依赖框架） |
| `client/http_client.py` | `@FeignClient` | 出站 HTTP |
| `ros/node.py` | ROS 通信层 + `@Component` | 对内 ROS 通信（rclpy 软依赖） |
| `model/response.py` | `Result<T>` | 统一返回 |
| `model/dto.py` | DTO | 入参结构 |
| `exception/exceptions.py` | `BusinessException` | 业务异常 |
| `exception/handlers.py` | `@ControllerAdvice` | 全局异常处理 |
| `deploy.sh` | 部署脚本 | systemd 服务管理 |
| `scripts/bsd-controller.service` | systemd service | 开机自启 + 崩溃重启 |

---

| 项 | 内容 |
| --- | --- |
| 项目名 | `bsd-unitree-controller` |
| 仓库地址 | https://github.com/cycyu7-pixel/bsd-unitree-controller |
| 业务方/所属团队 | bsd-wl 开发团队 |
| 技术栈 | Python 3.10 + FastAPI + httpx + tenacity + Pydantic + loguru + rclpy（软依赖） |
| 部署环境 | 宇树 G1 机器人（Ubuntu 22.04 + ROS Humble + Cyclone DDS） |
| 部署方式 | ROS package（colcon build + ros2 run + systemd 开机自启） |
| README 维护建议 | 代码、配置、接口或部署方式变化时同步更新 |
