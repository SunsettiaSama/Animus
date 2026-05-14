# ReAct Agent - 部署快速开始指南

## 🚀 快速启动（推荐）

### Windows 用户
```bash
# 双击运行或在命令行输入
..\launch.bat help
```

### Linux/macOS/WSL 用户
```bash
# 添加执行权限并运行
chmod +x ../launch.sh
../launch.sh help
```

---

## 📖 详细使用

### 1. 初始化（首次运行）
```bash
# Windows
..\launch.bat init

# Linux/macOS
../launch.sh init
```

### 2. 启动开发环境
```bash
# Windows
..\launch.bat staging

# Linux/macOS
../launch.sh staging
```

### 3. 启动生产环境
```bash
# Windows
..\launch.bat production

# Linux/macOS
../launch.sh production
```

### 4. 查看日志
```bash
# Windows
..\launch.bat logs

# 查看特定服务日志
..\launch.bat logs react
```

### 5. 停止服务
```bash
..\launch.bat stop
```

---

## 🏗️ 新架构说明

### 管理容器架构
```
┌─────────────────────────────────────────────────────────┐
│  ReAct Agent Manager Container (react-agent-manager)    │
│  (运行所有管理脚本，操作宿主机的 Docker API         │
└─────────────────────────────────────────────────────────┘
                          │
                          │
                          ▼
    ┌───────────────┬───────────────┬───────────────┐
    │    react   │    mysql      │    redis     │  ...
    └───────────────┴───────────────┴───────────────┘
```

### 目录结构
```
ReAct/
├── launch.bat              # Windows 极简入口（仅 20 行）
├── launch.sh               # Linux/macOS 极简入口（仅 16 行）
└── docker/
    ├── manager/
    │   └── Dockerfile      # 管理容器构建文件
    ├── docker-compose.manager.yml   # 管理容器配置
    ├── docker-compose.prod.yml
    └── ... (其他配置)
```

---

## 📊 完整命令列表

| 命令 | 说明 |
|------|------|
| `init` | 初始化项目 |
| `staging` | 开发环境 |
| `production` | 生产环境 |
| `stop` | 停止服务 |
| `restart` | 重启服务 |
| `status` | 查看状态 |
| `logs [service]` | 查看日志 |
| `backup` | 备份数据 |
| `clean` | 清理镜像和容器 |
| `help` | 显示帮助 |

---

## 🌐 访问地址

| 服务 | 地址 |
|------|------|
| ReAct Agent | http://app.localhost |
| Grafana | http://grafana.localhost |
| Prometheus | http://prometheus.localhost:9090 |
| Traefik | http://traefik.localhost:8080 |
| Jaeger | http://jaeger.localhost |

---

## 📝 首次配置

首次运行前，请先复制并编辑 `.env` 文件：

```bash
cd docker
cp .env.example .env
# 编辑配置
nano .env
```

---

## 🏗️ 直接使用管理容器

如果想直接使用管理容器：

```bash
cd docker

# 构建管理容器
docker compose -f docker-compose.manager.yml build manager

# 使用管理命令
docker compose -f docker-compose.manager.yml run --rm manager help
docker compose -f docker-compose.manager.yml run --rm manager staging
```

---

## 🛠️ 旧脚本保留（已集成到管理容器中

| 原脚本 | 状态 | 说明 |
|---------|------|
| `docker/launch.sh` | ✅ 已集成到管理容器 |
| `docker/launch-windows.bat` | ✅ 已集成到管理容器 |

现在根目录只有两个极简入口，项目更整洁！

