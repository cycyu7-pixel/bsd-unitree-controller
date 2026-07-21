# bsd-unitree-controller

宇树机器人控制流程系统。对外提供 HTTP 接口（FastAPI），对内通过 ROS 2 节点与其他节点通信。当前阶段是骨架 + ROS 集成，不包含业务逻辑，业务功能在此骨架上扩展。

## 1. 这个项目做什么

**一句话定位**：跑在宇树机器人本体上的控制流程系统，对外提供 HTTP 接口，对内通过 ROS 2 与其他节点通信，对上游系统调 HTTP。

**当前阶段范围**：
- 规范的 FastAPI 分层骨架（启动、配置、异常、统一返回）
- 带重试的 HTTP 客户端封装（httpx + tenacity）
- ROS 2 节点封装（rclpy 软依赖，单进程双线程，骨架已就绪）
- 不包含业务逻辑

**不包含**：
- 具体 ROS publisher/subscriber/service（骨架阶段只验证集成，业务接入后再加）
- 业务接口（任务、上报等）
- 数据库、消息队列

## 2. 工作原理

单进程双线程架构：FastAPI/uvicorn 跑主线程，rclpy.spin 跑后台 daemon 线程。
HTTP 接口和 ROS 通信共享 `app.state`，互不阻塞。

```text
              外部调用方
                  │ HTTP
                  ▼
┌─────────────────────────────────────────────┐
│ 单进程                                        │
│  ┌────────────────────────────┐              │
│  │ uvicorn（主线程）           │              │
│  │  FastAPI app                │              │
│  │   /api/v1/health  /test     │ ← HTTP 接口  │
│  │   /api/v1/ros/status        │              │
│  └─────────┬──────────┬───────┘              │
│            │          │ app.state            │
│   Depends(get_http_ │  Depends(get_ros_node)│
│       client)       │                       │
│            ▼          ▼                      │
│  ┌──────────────┐  ┌──────────────────┐     │
│  │ HttpClient   │  │ rclpy.spin       │     │
│  │ (@FeignClient)│ │ (daemon 线程)    │     │
│  │ 出站 HTTP     │  │ ControllerNode   │     │
│  └──────────────┘  └────────┬─────────┘     │
│                             │ ROS topic/srv  │
└─────────────────────────────┼───────────────┘
                              ▼
                    [其他 ROS 节点]
```

启动到运行的步骤：

1. `main.py` 加载 `config/config.yaml`，应用环境变量覆盖
2. 初始化 loguru 日志（控制台 + 文件）
3. `api/server.py` 的 `create_app` 装配 FastAPI app，`lifespan` 启动段执行：
   - 创建 HttpClient 挂到 `app.state.http_client`
   - 若 `config.ros.enabled=true` 且 rclpy 可用：`rclpy.init()` + 创建 ControllerNode + 起 daemon 线程跑 `rclpy.spin`，挂到 `app.state.ros_node`
   - 否则跳过 ROS，纯 HTTP 模式
4. uvicorn 监听端口，开始接收 HTTP 请求
5. 接口层通过 `Depends(get_http_client)` 拿 HttpClient，或 `Depends(get_ros_node)` 拿 ROS 节点
6. 返回 `Result.ok()` 给调用方（`code=1` 表示成功）

## 3. 快速开始

### 环境要求

| 项 | 版本 |
| --- | --- |
| Python | >= 3.11 |
| uv | 任意版本 |

### 健康检查

```bash
curl http://127.0.0.1:8080/api/v1/health
# 预期返回
# {"code":1,"message":"success","data":{"status":"up"}}
```

### HTTP 封装验证

```bash
curl http://127.0.0.1:8080/api/v1/baidu
# 预期返回（通过 HttpClient 访问百度主页）
# {"code":1,"message":"success","data":"success"}
```

### 本地启动

```bash
# 安装依赖
uv sync

# 方式一：脚本启动（自动装配日志 + uvicorn）
uv run python main.py

# 方式二：uvicorn 直接引用模块级 app（支持 --reload 热重载）
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8080
```

启动成功后访问接口文档：http://127.0.0.1:8080/docs

### 运行测试

```bash
uv sync --extra dev       # 首次需装 dev 依赖（pytest + httpx）
uv run pytest tests/ -v
```

### 停止服务

`Ctrl+C` 终止 `uv run python main.py` 进程。

### 启动失败时第一条检查命令

```bash
# 检查端口是否被占用（Windows）
netstat -ano | findstr :8080

# 检查依赖是否装齐
uv run python -c "import fastapi, httpx, tenacity, loguru; print('OK')"
```

## 4. 工程结构

```text
bsd-unitree-controller/
├── pyproject.toml              # 依赖声明（uv 管理）
├── main.py                     # 启动入口 + 模块级 app
├── Dockerfile                  # 镜像构建（基于 osrf/ros:humble-ros-base）
├── docker-compose.yml          # 编排配置（host 网络 + volume 挂载）
├── .dockerignore               # 构建上下文排除
├── config/
│   └── config.yaml             # 配置文件（类比 application.yml）
├── src/bsd_unitree_controller/
│   ├── __init__.py
│   ├── core/                   # 核心基础设施（配置、依赖项）
│   │   ├── config.py           #   配置加载 + 环境变量覆盖
│   │   └── deps.py             #   公共依赖（get_http_client / get_ros_node）
│   ├── api/                    # 对外 HTTP 入口（@RestController）
│   │   ├── __init__.py         #   api_router 汇总（加 /api/v1 前缀）
│   │   ├── server.py           #   FastAPI app 装配 + lifespan（含 ROS 生命周期）
│   │   └── v1/                 #   v1 版本路由
│   │       ├── __init__.py     #     v1_router 汇总
│   │       └── health.py       #     健康检查 / 百度验证 / ROS 状态路由
│   ├── service/                # 业务层（占位，@Service）
│   ├── client/                 # 出站 HTTP（@FeignClient）
│   │   └── http_client.py      #   httpx + tenacity 封装
│   ├── ros/                    # 对内 ROS 通信（软依赖 rclpy）
│   │   └── node.py             #   ControllerNode + 生命周期函数
│   ├── model/                  # 统一返回与通用 VO
│   │   ├── response.py         #   Result<T> / PageResult<T>
│   │   └── common.py           #   HealthVO 等通用 VO
│   ├── exception/              # 业务异常 + 全局处理器
│   │   ├── exceptions.py       #   BizException 等
│   │   └── handlers.py         #   @ControllerAdvice
│   └── utils/
│       └── logging.py          # loguru 日志初始化
└── tests/                      # 测试（pytest + TestClient）
    └── test_health.py
```

| 路径 | 职责 |
| --- | --- |
| `main.py` | 启动入口，业务逻辑永远不写在这；同时暴露模块级 `app` 供 uvicorn 引用 |
| `core/config.py` | 配置加载，yaml + 环境变量覆盖（前缀 `BSD_`） |
| `core/deps.py` | 公共依赖项（`get_http_client` / `get_ros_node`），路由通过 `Depends` 取 |
| `api/__init__.py` | `api_router` 汇总，统一加 `/api/v1` 版本前缀 |
| `api/server.py` | 装配 app、注册路由和异常处理器、lifespan 管理 HttpClient + ROS 生命周期 |
| `api/v1/health.py` | 健康检查、HTTP 封装验证、ROS 状态路由，新增接口按模块拆分到这里 |
| `service/` | 业务编排（当前为空，后续业务逻辑加在这里） |
| `client/http_client.py` | 出站 HTTP 调用，新增外部调用加在这里 |
| `ros/node.py` | ROS 节点封装，rclpy 软依赖，未装时降级为纯 HTTP 模式 |
| `model/response.py` | `Result<T>` / `PageResult<T>` 统一返回，一般不动 |
| `model/common.py` | 跨模块复用的 VO（如 `HealthVO`） |
| `exception/exceptions.py` | 业务异常定义，新增异常加在这里 |
| `exception/handlers.py` | 全局异常处理器，一般不动 |
| `config/config.yaml` | 配置文件，改端口、超时、ROS 开关在这里 |

### 分层调用规则（铁律）

1. `service/` **不 import** `fastapi` / `httpx` / `rclpy`，业务逻辑要能脱离框架单测
2. `api/` 不直接调 `client/`，必须经过 `service/`（当前阶段 service 为空，暂由 api 直接调 client 验证骨架，接入业务后改回标准流程）
3. `api/` 和 `client/` 不写业务，只做翻译（HTTP <-> DTO / DTO <-> HTTP）

## 5. 配置说明

配置文件位置：`config/config.yaml`

```yaml
# 服务（FastAPI）配置
server:
  host: "0.0.0.0"   # 监听地址
  port: 18800        # 监听端口

# 出站 HTTP 调用通用配置（各上游 URL 在业务代码里硬编码）
upstream:
  timeout: 10   # 出站请求超时（秒）
  retry: 2      # 重试次数（不含首次，实际最多调 retry+1 次）

# 日志配置
log:
  level: "INFO"    # 日志级别：DEBUG / INFO / WARNING / ERROR
  dir: "logs"      # 日志文件目录，为空只输出控制台

# ROS 节点配置
ros:
  enabled: true                          # 是否启用 ROS 节点（false 走纯 HTTP 模式）
  node_name: "controller"    # ROS 节点名
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

> `upstream` 段只有 `timeout` 和 `retry`。各上游 URL 在业务代码里按需硬编码，因为通常会有多个目标地址，不适合统一配置。

### 环境变量覆盖

yaml 里的任何字段都能被环境变量覆盖，**优先级高于配置文件**。规则：

- 前缀 `BSD_`
- 嵌套用 `__` 分隔
- 字段名转小写

| 环境变量 | 覆盖字段 | 示例值 |
| --- | --- | --- |
| `BSD_SERVER__HOST` | `server.host` | `127.0.0.1` |
| `BSD_SERVER__PORT` | `server.port` | `9000` |
| `BSD_UPSTREAM__TIMEOUT` | `upstream.timeout` | `5` |
| `BSD_UPSTREAM__RETRY` | `upstream.retry` | `3` |
| `BSD_LOG__LEVEL` | `log.level` | `DEBUG` |
| `BSD_LOG__DIR` | `log.dir` | （空字符串只输出控制台） |
| `BSD_ROS__ENABLED` | `ros.enabled` | `false`（开发机关闭 ROS） |
| `BSD_ROS__NODE_NAME` | `ros.node_name` | `my_controller` |

示例：

```bash
# 临时改端口启动，不改配置文件
BSD_SERVER__PORT=9090 uv run python main.py

# 开发机关闭 ROS（即使装了 rclpy 也不初始化）
BSD_ROS__ENABLED=false uv run python main.py
```

修改配置文件后必须重启服务生效；环境变量覆盖同样只在启动时读取一次。

## 6. REST 接口

### `GET /api/v1/health` - 健康检查

```bash
curl http://127.0.0.1:8080/api/v1/health
```

```json
{"code": 1, "message": "success", "data": {"status": "up"}}
```

### `GET /api/v1/baidu` - HTTP 封装验证

调用本接口会通过 `HttpClient` 访问百度主页，验证出站 HTTP 封装（httpx + tenacity）可用。

```bash
curl http://127.0.0.1:8080/api/v1/baidu
```

```json
{"code": 1, "message": "success", "data": "success"}
```

### `GET /api/v1/ros/status` - ROS 节点状态

查询 ROS 节点状态，用于确认 ROS 集成是否生效。

```bash
curl http://127.0.0.1:18800/api/v1/ros/status
```

```json
// rclpy 未装/配置禁用
{"code": 1, "message": "success", "data": {"status": "disabled", "reason": "ROS 未启用..."}}

// 机器人环境，节点已启动
{"code": 1, "message": "success", "data": {"status": "alive", "node_name": "controller"}}
```

### 错误码

| code | 含义 |
| --- | --- |
| `1` | 成功 |
| `0` | 通用失败 |
| `400` | 参数校验失败 |
| `50001` | HTTP 调用失败（重试用尽或返回非 2xx） |
| `500` | 服务器内部错误 |

业务异常 HTTP 状态码统一返回 200，错误信息体现在 `code` 字段。

## 7. HTTP 客户端封装

`client/http_client.py` 是**通用 HTTP 工具类**，只提供 `get()` / `post()` 方法，不写任何业务逻辑：

- 底层用 `httpx.Client`（连接池复用），类比 Java 的 OkHttp
- 重试用 `tenacity`，类比 Spring Retry
- 业务异常（HTTP 4xx/5xx）不重试，网络层错误（超时、连接失败）重试
- 指数退避：1s, 2s, 4s...，上限 10s

### 使用方式

通过 `Depends(get_http_client)` 拿到 `HttpClient` 实例，调 `get()` / `post()` 传 URL + 参数即可。响应对象由调用方自行解析（`.json()` / `.text` / `.status_code`）。

```python
from fastapi import APIRouter, Depends
from bsd_unitree_controller.client.http_client import HttpClient
from bsd_unitree_controller.core.deps import get_http_client
from bsd_unitree_controller.model.response import Result

router = APIRouter()


# ── GET 请求示例 ──────────────────────────────────────────────
@router.get("/users")
def list_users(
    client: HttpClient = Depends(get_http_client),
) -> Result[dict]:
    """GET 请求：query 参数传 params。"""
    resp = client.get(
        "http://user-service:9000/users",  # 完整 URL，业务代码自行硬编码
        params={"page": 1, "size": 10},    # -> /users?page=1&size=10
    )
    return Result.ok(data=resp.json())


# ── POST 请求示例（JSON body）──────────────────────────────────
@router.post("/users")
def create_user(
    client: HttpClient = Depends(get_http_client),
) -> Result[dict]:
    """POST 请求：JSON body 传 json。"""
    resp = client.post(
        "http://user-service:9000/users",
        json={"name": "张三", "age": 18},  # 自动序列化 + Content-Type: application/json
    )
    return Result.ok(data=resp.json())


# ── POST 请求示例（表单 body）──────────────────────────────────
@router.post("/login")
def login(
    client: HttpClient = Depends(get_http_client),
) -> Result[dict]:
    """POST 请求：表单传 data。"""
    resp = client.post(
        "http://auth-service:9000/login",
        data={"username": "admin", "password": "xxx"},  # application/x-www-form-urlencoded
    )
    return Result.ok(data=resp.json())
```

> 多个上游地址时，建议在各业务模块顶部用常量集中管理 URL，例如：
> ```python
> USER_SERVICE = "http://user-service:9000"
> AUTH_SERVICE = "http://auth-service:9000"
> ```

### 方法签名

| 方法 | 参数 | 说明 |
| --- | --- | --- |
| `client.get(url, *, params, headers)` | 完整 URL + query 参数 + 请求头 | 返回 `httpx.Response` |
| `client.post(url, *, json, data, params, headers)` | 完整 URL + body（json/data 二选一）+ query + 请求头 | 返回 `httpx.Response` |

URL 规则：
- 必须传**完整 URL**（带 `http(s)://`），如 `http://user-service:9000/users`
- 不再支持相对路径，因为 `upstream` 配置已移除 `base_url`（会有多个目标地址，不适合统一配置）

### 重试行为

| 错误类型 | 是否重试 | 说明 |
| --- | --- | --- |
| 连接失败 / 超时 | ✅ | 重试 `upstream.retry` 次，指数退避 |
| HTTP 4xx / 5xx | ❌ | 业务错误，不重试直接抛 `UpstreamException` |

## 8. 日志查看

### 控制台日志

启动后直接在终端看到，带颜色高亮：

```text
2026-07-20 13:48:24.074 | INFO     | bsd_unitree_controller.client.http_client:fetch_baidu:92 - 访问百度主页: https://www.baidu.com
```

### 文件日志

按天轮转，保留 30 天，位置 `logs/app_YYYY-MM-DD.log`。

```bash
# 实时查看
tail -f logs/app_$(date +%Y-%m-%d).log

# 查看错误
grep "ERROR\|WARNING" logs/app_$(date +%Y-%m-%d).log
```

### 关键日志含义

| 日志关键词 | 含义 |
| --- | --- |
| `配置加载完成` | 启动成功读到配置 |
| `FastAPI 应用装配完成` | app 装配成功 |
| `启动 uvicorn` | 服务开始监听 |
| `ControllerNode 已启动` | ROS 节点初始化成功 |
| `ROS 节点已启动，spin 在后台线程运行` | rclpy.spin daemon 线程已起 |
| `rclpy 未安装，跳过 ROS 节点初始化` | 软依赖降级，纯 HTTP 模式（开发机常见） |
| `ROS 已在配置中禁用` | `ros.enabled=false`，纯 HTTP 模式 |
| `ROS 节点初始化失败` | rclpy 已装但 init 报错（查 DDS 环境） |
| `ROS 节点已关闭` | 关闭段清理完成 |
| `Retrying ... in N seconds` | tenacity 重试中 |
| `HTTP 调用返回非成功状态` | 上游返回 4xx/5xx |
| `业务异常` | 抛出 BizException |
| `未捕获异常` | 出现未预期错误，查堆栈 |

## 9. ROS 集成

本项目封装为 ROS 2 节点部署到机器人内部，对外提供 HTTP 接口，对内通过 ROS topic/service 与其他节点通信。

### 启动架构

单进程双线程：FastAPI/uvicorn 跑主线程，`rclpy.spin` 跑后台 daemon 线程，共享 `app.state`。

- HTTP 请求由 uvicorn 在主线程处理
- ROS 消息回调由 `rclpy.spin` 在 daemon 线程触发
- `rclpy.spin` 底层 C 库等待消息时释放 GIL，不阻塞主线程的 asyncio loop
- 主进程退出时 daemon 线程自动结束，`lifespan` 关闭段清理 ROS 资源

### 软依赖（rclpy）

`rclpy` 作为**软依赖**，Windows 开发机不装也能跑：

| 环境 | rclpy | 行为 |
| --- | --- | --- |
| Windows 开发机 | 未装 | `import rclpy` 失败，`is_ros_available()` 返回 False，lifespan 跳过 ROS 初始化，纯 HTTP 模式 |
| 机器人（Ubuntu + ROS Humble） | 已装 | `rclpy.init()` + 创建 ControllerNode + 起 spin 线程，ROS 自动启用 |
| 任意环境 | 已装但 `ros.enabled=false` | 配置禁用，跳过 ROS 初始化 |

`/api/v1/ros/status` 接口可查询当前模式：

```bash
curl http://127.0.0.1:18800/api/v1/ros/status
# 开发机（rclpy 未装）
# {"code":1,"data":{"status":"disabled","reason":"ROS 未启用..."}}
# 机器人（rclpy 已装且启用）
# {"code":1,"data":{"status":"alive","node_name":"controller"}}
```

### 安装 rclpy

**不能 `pip install rclpy`**，必须走 ROS 发行版安装：

```bash
# Ubuntu 22.04 + ROS Humble（机器人部署环境）
sudo apt install ros-humble-rclpy
source /opt/ros/humble/setup.bash

# 验证
python3 -c "import rclpy; print('rclpy OK')"
```

Windows 开发机**不需要装 rclpy**，本项目已做软依赖处理，HTTP 部分可独立开发测试。

> `pyproject.toml` 不声明 rclpy（它在 PyPI 上不可用），代码用 `try/except import rclpy` 软依赖处理。机器人上装好系统级 rclpy 后，本项目代码无需改动即可启用 ROS。

### 扩展 ROS 通信

后续接入真实业务时，在 `ros/node.py` 的 `ControllerNode` 类里扩展：

```python
class ControllerNode(Node):
    def __init__(self, node_name: str = "controller"):
        super().__init__(node_name)
        # 发布控制指令到运动控制节点
        self._cmd_pub = self.create_publisher(String, "/cmd", 10)
        # 订阅机器人状态
        self._state_sub = self.create_subscription(String, "/state", self._on_state, 10)
        # 提供本节点可被调用的服务
        self._srv = self.create_service(SetBool, "/enable", self._handle_enable)

    def _on_state(self, msg):
        ...

    def _handle_enable(self, req, resp):
        ...
        return resp
```

路由层通过 `Depends(get_ros_node)` 拿到节点实例，调 `node._cmd_pub.publish(...)` 等方法。**注意**：ROS service 同步 `call` 会阻塞，要用 `call_async` + `await future`，路由写成 `async def`。

### 部署到机器人

推荐用 Docker 部署，项目已提供 `Dockerfile` 和 `docker-compose.yml`。

**基础镜像**：`osrf/ros:humble-ros-base`（Ubuntu 22.04 + ROS Humble + Python 3.10，自带 rclpy）

不能用 `python:3.11` 起步，因为 rclpy 依赖 ROS 的 C 库（rcl/rmw/DDS），这些必须用 apt 装系统级包，pip 装不了。

#### 构建与运行

```bash
# 1. 构建镜像（在项目根目录）
docker compose build

# 2. 启动服务（后台运行）
docker compose up -d

# 3. 查看日志
docker compose logs -f

# 4. 停止服务
docker compose down
```

#### 关键配置点

| 配置 | 值 | 原因 |
| --- | --- | --- |
| `network_mode: host` | 必须用主机网络 | ROS 2 DDS 用多播自动发现节点，bridge 网络会导致容器内外节点互相看不见 |
| `ROS_DOMAIN_ID=0` | 跟机器人其他节点一致 | 同域才能通信，不一致互相看不见 |
| 配置外挂 | `./config/config.yaml` 挂到容器 | 改配置不用重打镜像 |
| 日志外挂 | `./logs` 挂到容器 | 宿主机可直接查看日志文件 |
| `restart: unless-stopped` | 机器人重启后自动恢复 | 断电重启场景必备 |

#### 部署后验证

```bash
# 1. 容器在跑
docker ps | grep bsd-controller

# 2. HTTP 接口正常
curl http://127.0.0.1:18800/api/v1/test
# 期望 {"code":1,"data":{"status":"up"}}

# 3. ROS 节点已注册（在机器人宿主机跑，不是容器内）
ros2 node list
# 期望看到 /controller

# 4. ROS 状态接口
curl http://127.0.0.1:18800/api/v1/ros/status
# 期望 {"code":1,"data":{"status":"alive","node_name":"controller"}}
```

#### 常见部署问题

| 问题 | 原因 | 解决 |
| --- | --- | --- |
| `ros2 node list` 看不到本节点 | `ROS_DOMAIN_ID` 跟其他节点不一致 | 改 `docker-compose.yml` 里的 `ROS_DOMAIN_ID` 对齐 |
| `ros2 node list` 看不到本节点 | 没用 `network_mode: host` | 检查 compose 文件，必须 host 网络 |
| 容器内 `import rclpy` 失败 | CMD 没 source ROS 环境 | 已在 Dockerfile 处理，CMD 里 `source /opt/ros/humble/setup.bash` |
| 跟其他节点通信不通 | DDS 中间件不兼容 | 默认 Fast DDS，一般不用改；特殊场景换 Cyclone DDS |

> Python 版本注意：ROS Humble 绑定 Python 3.10，`pyproject.toml` 已设 `requires-python = ">=3.10"`。开发机用 3.11 开发 FastAPI 部分，部署镜像跟随 ROS 用 3.10。

## 10. 部署与运维

### 方式一：Docker 部署（推荐，机器人内部用）

见上一节"ROS 集成 → 部署到机器人"。

### 方式二：进程直跑（开发调试用）

```bash
# 前台启动（开发用）
uv run python main.py

# 后台启动（Linux，临时生产用）
nohup uv run python main.py > /dev/null 2>&1 &

# 停止服务
kill <PID>
```

## 11. 改代码后怎么上线

| 改动类型 | 是否需要重装依赖 | 是否需要重启 |
| --- | --- | --- |
| Python 代码 | ❌ | ✅ |
| `pyproject.toml` 加依赖 | ✅ | ✅ |
| `config.yaml` 配置 | ❌ | ✅ |
| README 文档 | ❌ | ❌ |

## 12. 二次开发

### 想改什么该往哪写

| 想做的事 | 推荐位置 | 注意事项 |
| --- | --- | --- |
| 加新 HTTP 接口 | `api/v1/` 下新建模块（如 `tasks.py`），在 `api/v1/__init__.py` 汇总 | 只调 service/client，不写业务；返回用 `Result[T]` |
| 写业务逻辑 | `service/` 下新建文件 | 不要 import fastapi/httpx/rclpy |
| 调外部 HTTP | `client/http_client.py` 已提供 `get`/`post`，直接调 | 传完整 URL + 参数 |
| 加 ROS publisher/subscriber/service | `ros/node.py` 的 `ControllerNode.__init__` 里建 | 软依赖已处理，rclpy 未装时该类不被实例化 |
| 加新数据结构 | `model/` 下新建文件 | 用 Pydantic；入参用 `XxxDTO`，出参用 `XxxVO` |
| 加新业务异常 | `exception/exceptions.py` 加类 | 继承 `BizException` |
| 加公共依赖 | `core/deps.py` 加函数 | 路由通过 `Depends` 取用 |
| 改端口/ROS 开关 | `config/config.yaml` 或环境变量 | 改完重启 |

### ROS 通信扩展路径

骨架已就绪（`ros/node.py` 的 `ControllerNode` + lifespan 集成）。接入真实业务时：

1. `ros/node.py` 的 `ControllerNode.__init__` 里加 `create_publisher` / `create_subscription` / `create_service`
2. `service/` 层调 node 方法，把 ROS 消息转 DTO，业务逻辑放这里
3. 路由通过 `Depends(get_ros_node)` 拿节点实例，调 publisher.publish() 等
4. ROS service 同步调用要 `call_async` + `await future`，路由写 `async def`，避免阻塞 uvicorn
5. **`service/` 不 import rclpy**，业务逻辑要能脱离 ROS 单测（service 调 node 方法，node 由依赖注入）

## 13. 常见问题排查

### 服务起不来

**症状**

```text
Error: [Errno 10048] 正常情况下无法将套接字绑定到本地地址
```

**原因**：端口被占用。

**解决**

```bash
netstat -ano | findstr :8080
taskkill /PID <PID> /F
# 或改 config.yaml 里的 server.port
```

### 访问 /api/v1/baidu 失败

**症状**

```json
{"code": 50001, "message": "HTTP 调用返回非成功状态: ..."}
```

或日志出现 `Retrying ... in N seconds` 后报错。

**原因**：
- 网络不通，连不上百度
- 代理环境导致 httpx 走了不通的代理

**解决**

```bash
# 测试网络
curl -I https://www.baidu.com

# 如果走了代理，检查环境变量
echo $HTTP_PROXY $HTTPS_PROXY
```

## 14. 第三方库速查表

| 库 | 用途 | 类比 Java | 关键类/方法 |
| --- | --- | --- | --- |
| `fastapi` | Web 框架 | Spring Boot | `FastAPI`, `APIRouter`, `Depends` |
| `uvicorn` | ASGI 服务器 | 内嵌 Tomcat | `uvicorn.run(app, host, port)` |
| `httpx` | HTTP 客户端 | OkHttp | `httpx.Client`, `.request()` |
| `tenacity` | 重试机制 | Spring Retry | `@retry`, `stop_after_attempt`, `wait_exponential` |
| `pydantic` | 数据模型与校验 | Bean Validation | `BaseModel`, `Field` |
| `pyyaml` | YAML 解析 | SnakeYAML | `yaml.safe_load` |
| `loguru` | 日志 | Logback / `@Slf4j` | `logger.info()`, `logger.add()` |
| `rclpy` | ROS 2 Python 客户端 | （无 Java 对应） | `Node`, `create_publisher`, `create_subscription` |

## 15. 命名对照（给 Java 程序员）

| 本项目文件 | Java 圈对应 | 说明 |
| --- | --- | --- |
| `main.py` | `@SpringBootApplication` 启动类 | main 方法 + 模块级 app |
| `api/server.py` | `@Configuration` + 启动装配 | 创建 app、注册路由、lifespan |
| `api/__init__.py` | 路由扫描 | `api_router` 汇总，加版本前缀 |
| `api/v1/health.py` | `@RestController` | 路由处理 |
| `core/config.py` | `application.yml` + Config 类 | 配置加载 + 环境变量覆盖 |
| `core/deps.py` | 公共 `@Bean` | 公共依赖项 |
| `service/` | `@Service` | 业务编排（当前为空） |
| `client/http_client.py` | `@FeignClient` | 出站 HTTP |
| `ros/node.py` | ROS 节点 + `@Component` | 对内 ROS 通信（rclpy 软依赖） |
| `model/response.py` | `Result<T>` | 统一返回 |
| `exception/exceptions.py` | `BusinessException` | 业务异常 |
| `exception/handlers.py` | `@ControllerAdvice` | 全局异常处理 |

---

| 项 | 内容 |
| --- | --- |
| 项目名 | `bsd-unitree-controller` |
| 仓库地址 | 待补充 |
| 业务方/所属团队 | bsd-wl 开发团队 |
| 技术栈 | Python 3.10/3.11 + FastAPI + httpx + tenacity + Pydantic + loguru + rclpy（软依赖） |
| 部署环境 | 机器人内部 Ubuntu 22.04 + ROS Humble（Docker），开发机 Windows 纯 HTTP 模式 |
| README 维护建议 | 代码、配置、接口或部署方式变化时同步更新 |
