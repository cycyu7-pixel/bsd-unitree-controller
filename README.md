# bsd-unitree-controller

宇树 G1 机器人控制流程系统。对外提供 HTTP 接口（FastAPI），对内通过 ROS 2 节点与机器人其他节点通信。采用分层架构，HTTP 入口和 ROS 入口共享 service 层业务逻辑，零冗余。

## 1. 这个项目做什么

**一句话定位**：跑在宇树 G1 机器人本体上的控制流程系统，对外提供 HTTP 接口，对内通过 ROS 2 与运动控制、急停等节点通信。

**当前已实现**：
- 规范的 FastAPI 分层骨架（启动、配置、异常、统一返回）
- 带重试的 HTTP 客户端封装（httpx + tenacity）
- ROS 2 节点封装（rclpy 软依赖，单进程双线程）
- 存活检查：HTTP `/api/v1/alive` + ROS service `/controller/is_alive` 共享 HealthService
- 运动控制：HTTP `/api/v1/motion/cmd` -> ROS topic `/cmd_vel`（topic publish 模式）
- 急停控制：HTTP `/api/v1/estop/trigger` -> ROS service `/g1/estop/trigger`（service call 模式）

**不包含**：
- 数据库、消息队列
- 具体业务接口（任务管理、状态上报等，后续按需添加）

## 2. 工作原理

单进程双线程架构：FastAPI/uvicorn 跑主线程，rclpy.spin 跑后台 daemon 线程。HTTP 接口和 ROS 通信共享 `app.state`，互不阻塞。

```text
              外部调用方（App / 上位机 / 运维）
                  │ HTTP
                  ▼
┌─────────────────────────────────────────────────┐
│ 单进程                                            │
│  ┌──────────────────────────────┐                │
│  │ uvicorn（主线程）             │                │
│  │  FastAPI app                  │                │
│  │   /api/v1/test    健康检查    │                │
│  │   /api/v1/alive   存活检查    │ ← HTTP 接口    │
│  │   /api/v1/motion/cmd 运动控制 │                │
│  │   /api/v1/estop/trigger 急停  │                │
│  └──────┬────────────┬───────────┘                │
│         │ Depends    │ Depends                    │
│   (get_http_client)  (get_ros_node)               │
│         ▼            ▼                            │
│  ┌────────────┐  ┌──────────────────────┐        │
│  │ HttpClient │  │ rclpy.spin           │        │
│  │ 出站 HTTP   │  │ (daemon 线程)        │        │
│  └────────────┘  │ ControllerNode       │        │
│                  │  /cmd_vel publisher  │        │
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
| uv | 任意版本 | 依赖管理 |
| ROS Humble | 可选 | 部署到机器人需要，开发机不需要 |

### 健康检查

```bash
curl http://127.0.0.1:18800/api/v1/test
# 预期返回
# {"code":1,"message":"success","data":{"status":"up"}}
```

### ROS 节点状态

```bash
curl http://127.0.0.1:18800/api/v1/ros/status
# 机器人环境（rclpy 已装）
# {"code":1,"data":{"status":"alive","node_name":"controller"}}
# 开发机（rclpy 未装）
# {"code":1,"data":{"status":"disabled","reason":"ROS 未启用..."}}
```

### 本地启动（开发机）

```bash
# 安装依赖
uv sync

# 方式一：脚本启动
uv run python main.py

# 方式二：uvicorn 直接引用模块级 app（支持 --reload 热重载）
uv run uvicorn main:app --reload --host 0.0.0.0 --port 18800
```

开发机无 rclpy，自动降级为纯 HTTP 模式，ROS 相关接口返回 `code=50002`。

### 运行测试

```bash
uv sync --extra dev       # 首次需装 dev 依赖
uv run pytest tests/ -v   # 16 个测试用例
```

启动成功后访问接口文档：http://127.0.0.1:18800/docs

### 停止服务

`Ctrl+C` 终止 `uv run python main.py` 进程。

## 4. 工程结构

```text
bsd-unitree-controller/
├── pyproject.toml              # 依赖声明（uv 管理）
├── main.py                     # 启动入口 + 模块级 app
├── deploy.sh                   # Docker 一键部署脚本（构建+启动+开机自启）
├── Dockerfile                  # 镜像构建（挂载机器人 ROS 环境）
├── docker-compose.yml          # 编排配置（host 网络 + volume 挂载）
├── .dockerignore
├── config/
│   └── config.yaml             # 配置文件（类比 application.yml）
├── src/bsd_unitree_controller/
│   ├── __init__.py
│   ├── core/                   # 核心基础设施
│   │   ├── config.py           #   配置加载 + 环境变量覆盖
│   │   └── deps.py             #   公共依赖（get_http_client / get_ros_node）
│   ├── api/                    # 对外 HTTP 入口（@RestController）
│   │   ├── __init__.py         #   api_router 汇总（加 /api/v1 前缀）
│   │   ├── server.py           #   FastAPI app 装配 + lifespan（含 ROS 生命周期）
│   │   └── v1/                 #   v1 版本路由
│   │       ├── __init__.py     #     v1_router 汇总
│   │       ├── health.py       #     健康检查 / 存活检查 / ROS 状态
│   │       ├── motion.py       #     运动控制（topic publish 模式）
│   │       └── estop.py        #     急停控制（service call 模式）
│   ├── service/                # 业务逻辑层（@Service，不依赖框架）
│   │   ├── health_service.py   #   存活检查业务逻辑
│   │   ├── motion_service.py   #   运动控制业务逻辑
│   │   └── estop_service.py    #   急停业务逻辑
│   ├── client/                 # 出站 HTTP（@FeignClient）
│   │   └── http_client.py      #   httpx + tenacity 封装
│   ├── ros/                    # 对内 ROS 通信（软依赖 rclpy）
│   │   └── node.py             #   ControllerNode + 生命周期函数
│   ├── model/                  # 数据模型
│   │   ├── response.py         #   Result<T> / PageResult<T>
│   │   ├── common.py           #   HealthVO 等通用 VO
│   │   └── dto.py              #   MotionCmdDTO 等入参 DTO
│   ├── exception/              # 业务异常 + 全局处理器
│   │   ├── exceptions.py       #   BizException 等
│   │   └── handlers.py         #   @ControllerAdvice
│   └── utils/
│       └── logging.py          # loguru 日志初始化
└── tests/                      # 测试（pytest + TestClient）
    ├── test_health.py
    ├── test_motion.py
    └── test_estop.py
```

| 路径 | 职责 |
| --- | --- |
| `main.py` | 启动入口，业务逻辑永远不写在这 |
| `core/config.py` | 配置加载，yaml + 环境变量覆盖 |
| `core/deps.py` | 公共依赖项，路由通过 `Depends` 取 |
| `api/server.py` | 装配 app、lifespan 管理 HttpClient + ROS 生命周期 |
| `api/v1/health.py` | 健康检查、存活检查、ROS 状态路由 |
| `api/v1/motion.py` | 运动控制路由（topic publish 模式示例） |
| `api/v1/estop.py` | 急停控制路由（service call 模式示例） |
| `service/health_service.py` | 存活检查业务逻辑（HTTP + ROS 共享） |
| `service/motion_service.py` | 运动控制业务逻辑（方向转速度 + 调 node） |
| `service/estop_service.py` | 急停业务逻辑（await node service call） |
| `client/http_client.py` | 出站 HTTP 调用，通用 get/post |
| `ros/node.py` | ControllerNode，含 publisher/service server/service client |
| `model/response.py` | `Result<T>` / `PageResult<T>` 统一返回 |
| `model/dto.py` | 入参 DTO（MotionCmdDTO 等） |
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

### `POST /api/v1/motion/cmd` - 运动控制（topic publish 模式）

下发运动指令，经 service 层转成 ROS Twist，通过 `/cmd_vel` 发布。

```bash
# 前进
curl -X POST http://127.0.0.1:18800/api/v1/motion/cmd \
  -H "Content-Type: application/json" \
  -d '{"direction":"forward","speed":0.5}'

# 停止
curl -X POST http://127.0.0.1:18800/api/v1/motion/cmd \
  -H "Content-Type: application/json" \
  -d '{"direction":"stop"}'
```

| direction | 说明 | speed 含义 |
| --- | --- | --- |
| `forward` | 前进 | 线速度 m/s |
| `backward` | 后退 | 线速度 m/s |
| `turn_left` | 左转 | 角速度 rad/s |
| `turn_right` | 右转 | 角速度 rad/s |
| `stop` | 停止 | 忽略 |

```json
{"code": 1, "data": {"direction": "forward", "speed": 0.5, "linear_x": 0.5, "angular_z": 0.0}}
```

### `POST /api/v1/estop/trigger` - 急停控制（service call 模式）

触发机器人急停，经 service 层调用 ROS service `/g1/estop/trigger`。

```bash
curl -X POST http://127.0.0.1:18800/api/v1/estop/trigger
```
```json
{"code": 1, "data": {"success": true, "message": "..."}}
```

### `GET /api/v1/baidu` - HTTP 封装验证

通过 HttpClient 访问百度主页，验证出站 HTTP 封装可用。生产环境上线前移除。

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

## 7. HTTP 客户端封装

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

## 8. 日志查看

### 控制台日志

启动后直接在终端看到，带颜色高亮。按天轮转，保留 30 天，位置 `logs/app_YYYY-MM-DD.log`。

### 关键日志含义

| 日志关键词 | 含义 |
| --- | --- |
| `配置加载完成` | 启动成功读到配置 |
| `ControllerNode 已启动` | ROS 节点初始化成功 |
| `ROS 节点已启动，spin 在后台线程运行` | rclpy.spin daemon 线程已起 |
| `运动控制 publisher 已注册` | `/cmd_vel` publisher 就绪 |
| `急停 service client 已创建` | `/g1/estop/trigger` client 就绪 |
| `已发布运动指令` | 运动指令已发到 `/cmd_vel` |
| `已发送急停请求` | 急停 service 请求已发出 |
| `rclpy 未安装，跳过 ROS 节点初始化` | 软依赖降级，纯 HTTP 模式 |
| `业务异常` | 抛出 BizException |
| `未捕获异常` | 出现未预期错误，查堆栈 |

## 9. ROS 集成

### 启动架构

单进程双线程：FastAPI/uvicorn 跑主线程，`rclpy.spin` 跑后台 daemon 线程。

- HTTP 请求由 uvicorn 在主线程处理
- ROS 消息回调由 `rclpy.spin` 在 daemon 线程触发
- `rclpy.spin` 底层 C 库等待消息时释放 GIL，不阻塞主线程
- 主进程退出时 daemon 线程自动结束，`lifespan` 关闭段清理 ROS 资源

### 软依赖（rclpy）

`rclpy` 作为软依赖，Windows 开发机不装也能跑：

| 环境 | rclpy | 行为 |
| --- | --- | --- |
| Windows 开发机 | 未装 | 纯 HTTP 模式，ROS 接口返回 `code=50002` |
| 机器人（Ubuntu + ROS Humble） | 已装 | ROS 自动启用，节点注册到 ROS 网络 |

### ControllerNode 注册的 ROS 接口

| 类型 | 名称 | 消息类型 | 方向 | 用途 |
| --- | --- | --- | --- | --- |
| topic | `/cmd_vel` | `geometry_msgs/Twist` | publisher | 运动控制指令 |
| service | `/controller/is_alive` | `std_srvs/Trigger` | server | 存活检查 |
| service | `/g1/estop/trigger` | `std_srvs/Trigger` | client | 急停控制 |

### 安装 rclpy

不能 `pip install rclpy`，必须走 ROS 发行版安装：

```bash
sudo apt install ros-humble-rclpy
source /opt/ros/humble/setup.bash
```

Windows 开发机不需要装 rclpy，代码已做软依赖处理。

### 两种 ROS 通信模式对照

本项目演示了 ROS 两种通信模式的完整写法：

| 项 | 运动控制（motion） | 急停（estop） |
| --- | --- | --- |
| ROS 通信方式 | topic publish | service call |
| node 方法 | `publish_cmd()` 同步 | `trigger_estop()` async |
| service 方法 | `execute_cmd()` 同步 | `execute_estop()` async |
| 路由 | `def` 同步 | `async def` 异步 |
| 等待方式 | 不等待（fire-and-forget） | `asyncio.to_thread` + `spin_until_future_complete` |

### 部署到机器人

机器人环境（Ubuntu 22.04 + ROS Humble + Cyclone DDS），推荐用 Docker + deploy.sh 一键部署。

#### 方式一：Docker 部署（推荐，开机自启）

项目提供 `deploy.sh` 一键脚本，封装了构建、启动、日志挂载、开机自启。

```bash
# 1. 拷代码到机器人
git clone https://github.com/cycyu7-pixel/bsd-unitree-controller.git
cd bsd-unitree-controller

# 2. 一键部署（构建镜像 + 启动容器 + 日志挂载 + 开机自启）
chmod +x deploy.sh
./deploy.sh
```

部署完成后：

```bash
# 看日志
./deploy.sh logs

# 看状态
./deploy.sh status

# 测试
curl http://127.0.0.1:18800/api/v1/test
ros2 node list | grep controller
```

**开机自启**：容器用 `--restart unless-stopped` 启动，机器人重启后自动恢复，无需额外配置。

**日志挂载**：容器内 `/app/logs` 挂载到宿主机 `~/bsd-unitree-controller/logs/`，可直接查看：

```bash
# 宿主机直接看日志文件
ls ~/bsd-unitree-controller/logs/
cat ~/bsd-unitree-controller/logs/app_$(date +%Y-%m-%d).log
```

#### deploy.sh 命令一览

| 命令 | 作用 |
| --- | --- |
| `./deploy.sh` | 构建镜像 + 启动容器（默认） |
| `./deploy.sh rebuild` | 强制重新构建（无缓存）+ 启动 |
| `./deploy.sh logs` | 查看日志（实时跟踪） |
| `./deploy.sh stop` | 停止容器 |
| `./deploy.sh start` | 启动已存在的容器 |
| `./deploy.sh restart` | 重启容器 |
| `./deploy.sh status` | 查看容器和镜像状态 |
| `./deploy.sh clean` | 停止容器并删除容器+镜像 |

#### 更新代码后重新部署

```bash
git pull
./deploy.sh          # 自动重建镜像 + 重启容器
```

#### Docker 关键设计

| 配置 | 值 | 原因 |
| --- | --- | --- |
| `--network host` | 必须用主机网络 | ROS 2 DDS 用多播发现节点，bridge 网络会导致容器内外节点互相看不见 |
| `--restart unless-stopped` | 开机自启 | 机器人断电重启后容器自动恢复 |
| 挂载 `/opt/ros/humble` | ROS 环境 | rclpy / std_srvs 来自系统，不装进镜像 |
| 挂载 `/home/unitree/unitree_ros2_ws` | unitree 环境 | unitree_api 包来自 Unitree 工作空间 |
| 挂载 `config.yaml` | 配置外挂 | 改配置不用重打镜像 |
| 挂载 `logs/` | 日志外挂 | 宿主机可直接查看日志文件 |

#### 方式二：进程直跑（开发调试用）

```bash
# 1. 装依赖
cd ~/bsd-unitree-controller
pip3 install -e . --user

# 2. 启动（3 个 source + DDS 环境变量）
source /opt/ros/humble/setup.bash
source /home/unitree/unitree_ros2_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
python3 main.py
```

启动后期望日志：
```
ControllerNode 已启动: controller
运动控制 publisher 已注册: /cmd_vel
急停 service client 已创建: /g1/estop/trigger
ROS service 已注册: ~/is_alive
ROS 节点已启动，spin 在后台线程运行
启动 uvicorn，监听 0.0.0.0:18800
```

### 部署后验证

```bash
# 1. ROS 节点注册成功
ros2 node list                    # 看到 /controller
ros2 node info /controller        # 看 publisher/service 列表

# 2. HTTP 接口
curl http://127.0.0.1:18800/api/v1/test
curl http://127.0.0.1:18800/api/v1/ros/status    # status=alive

# 3. ROS service 测试（验证 ROS 链路）
ros2 service call /controller/is_alive std_srvs/srv/Trigger
# 期望 success=True

# 4. 急停测试
ros2 service call /g1/estop/trigger std_srvs/srv/Trigger
curl -X POST http://127.0.0.1:18800/api/v1/estop/trigger
```

## 10. 部署与运维

### 方式一：进程直跑（机器人内部推荐）

机器人已有 ROS 环境，进程直跑最简单，见上一节"部署到机器人"。

### 方式二：Docker 部署

```bash
docker compose build
docker compose up -d
docker compose logs -f
docker compose down
```

关键配置：`network_mode: host`（ROS DDS 必须）、`ROS_DOMAIN_ID` 跟其他节点一致。

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
| 加新 HTTP 接口 | `api/v1/` 下新建模块，在 `api/v1/__init__.py` 汇总 | 只调 service，不写业务 |
| 写业务逻辑 | `service/` 下新建文件 | 不 import fastapi/httpx/rclpy |
| 加 ROS publisher/subscriber | `ros/node.py` 的 `ControllerNode.__init__` | topic 模式，参考 `publish_cmd` |
| 加 ROS service client | `ros/node.py` 的 `ControllerNode` | service call 模式，参考 `trigger_estop` |
| 加 ROS service server | `ros/node.py` 的 `ControllerNode.__init__` | 参考 `~/is_alive` |
| 调外部 HTTP | `client/http_client.py` 已提供 `get`/`post` | 传完整 URL |
| 加新数据结构 | `model/` 下：入参 `dto.py`，出参 `common.py` 或新文件 | 用 Pydantic |
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

```text
Error: [Errno 10048] 正常情况下无法将套接字绑定到本地地址
```

端口被占用：`netstat -ano | findstr :18800`（Windows）或 `ss -tlnp | grep 18800`（Linux）。

### ROS 节点看不到 /controller

```bash
ros2 node list | grep controller
```

如果看不到，检查：
1. 启动日志是否有 `ControllerNode 已启动`
2. `RMW_IMPLEMENTATION` 是否跟其他节点一致（`rmw_cyclonedds_cpp`）
3. `ROS_DOMAIN_ID` 是否跟其他节点一致（默认 0）
4. 是否 source 了 ROS 环境

### ROS service 调用超时

急停 `/g1/estop/trigger` 调用超时，检查：
1. service 是否在线：`ros2 service list | grep estop`
2. service 类型是否匹配：`ros2 service type /g1/estop/trigger`

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

---

| 项 | 内容 |
| --- | --- |
| 项目名 | `bsd-unitree-controller` |
| 仓库地址 | https://github.com/cycyu7-pixel/bsd-unitree-controller |
| 业务方/所属团队 | bsd-wl 开发团队 |
| 技术栈 | Python 3.10/3.11 + FastAPI + httpx + tenacity + Pydantic + loguru + rclpy（软依赖） |
| 部署环境 | 宇树 G1 机器人（Ubuntu 22.04 + ROS Humble + Cyclone DDS） |
| README 维护建议 | 代码、配置、接口或部署方式变化时同步更新 |
