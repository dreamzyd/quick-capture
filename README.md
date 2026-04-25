# Quick Capture / 记一下

一个极低摩擦的杂事收集工具，支持电脑端和手机端快速输入，先专注"收集"，后续再处理。

## 产品理念

- **输入速度第一** - 想到什么就记什么，别打断自己
- **收集和处理分离** - 先记下来，之后再整理
- **默认允许很烂的输入** - 不用管格式，不用管分类
- **多设备共享** - 手机、电脑、Pad 都属于同一个账号，记录互通
- **架构预留多用户** - 当前优先自己可用，但架构保留未来分享给别人的能力

## 技术栈

- **后端**: Flask 2.0.3
- **模板**: Jinja2
- **前端交互**: HTMX
- **数据库**: SQLite
- **样式**: 原生 CSS
- **部署**: Docker Compose

## 快速开始

### 环境要求

- Docker
- Docker Compose

### 启动

```bash
cd quick-capture
docker compose up -d --build
```

服务默认运行在 `http://localhost:18901`

## 产品模型

### 账号体系

- 一个用户 = 一个账号空间
- 一个用户可有多个设备（手机、电脑、Pad）
- 用户的所有设备都能看到该账号下的全部记录
- 不同用户之间的数据严格隔离

### 页面结构

- **首页 `/`** - 快速采集入口，显示当前账号记录
- **我的账号 `/me`** - 用户空间，包含账号信息、加入码、设备管理
- **加入页 `/join`** - 新设备通过加入码并入已有账号
- **管理员后台 `/admin/*`** - 系统管理员专用，负责批准新账号

### 管理员

管理员通过环境变量配置：

```yaml
environment:
  - QUICK_CAPTURE_ADMIN_PASSWORD=your-password
```

管理员职责：
- 批准新账号首次开通
- 查看系统状态
- 不做普通用户的设备管理

## 功能列表

### 采集
- 快速新增记录
- 多行粘贴自动拆分
- Ctrl/⌘ + Enter 快速提交
- 公开首页只采集，不读记录

### 查看
- 首页显示当前账号记录
- 轻量搜索 / 文本过滤
- 数据导出（CSV / JSON）

### 账号管理
- 账号首次审批
- 加入码 / join link
- 设备自管理（改名、查看）

### 管理员后台
- 待审批账号列表
- 已开通账号列表
- 批准 / 查看

## 部署

### Docker Compose

```yaml
version: '3.8'
services:
  quick-capture:
    build: .
    container_name: quick-capture
    ports:
      - "18901:18901"
    volumes:
      - ./data:/app/data
    environment:
      - QUICK_CAPTURE_DB=/app/data/quick_capture.db
      - QUICK_CAPTURE_ADMIN_PASSWORD=your-password
    restart: unless-stopped
```

### 数据持久化

数据存储在 `./data` 目录，通过 Docker volume 挂载。

## 开发

### 项目结构

```
quick-capture/
├── app/
│   ├── main.py          # Flask 应用主文件
│   ├── templates/       # Jinja2 模板
│   └── static/          # 静态文件
├── data/                # SQLite 数据库
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── TODO.md
└── README.md
```

### 本地开发

```bash
pip install -r requirements.txt
python app/main.py
```

## 未来计划

- [ ] 同账号多设备共享记录
- [ ] 用户自管理设备群
- [ ] 邀请链接 / 邀请码
- [ ] 外网入口 / HTTPS
- [ ] 每日回顾视图

## License

MIT


## API 返回说明

`/api/records` 当前返回的每条记录包含：

- `id`
- `content`
- `created_at`
- `source_device_id`
- `source_device_name`

说明：当前产品不再维护“是否完成/已处理”流程，因此 API 不再强调 `status` 字段。
