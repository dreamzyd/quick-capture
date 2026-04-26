# Quick Capture / 记一下

一个极低摩擦的记录组工具。你可以在手机、电脑、Pad 上快速记内容，同一记录组内的设备共享同一份数据。

## 功能概览

- 快速记录内容，支持多行粘贴拆分
- 多设备加入同一个记录组
- 新建组走管理员批准
- 新设备加入走组内已批准设备确认
- `/me` 管理记录组名称、加入码、设备、Recovery Token 和 API Token
- `/api/records` 支持按 token 拉取记录
- 支持导出 CSV / JSON

## 安装

### 1. 准备目录

```bash
git clone git@github.com:dreamzyd/quick-capture.git
cd quick-capture
mkdir -p data
```

### 2. 修改管理员密码

编辑 `docker-compose.yml`，设置你自己的管理员密码：

```yaml
environment:
  - QUICK_CAPTURE_ADMIN_PASSWORD=your-password
```

### 3. 启动

`docker-compose.yml` 已内置 `TZ=Asia/Shanghai`，容器时区默认为东八区。


```bash
docker compose up -d --build quick-capture
```

默认访问地址：

- 本机：`http://localhost:18901`
- 局域网 / 外网：`http://<你的IP>:18901`

## 使用说明

页面、接口和新写入数据的时间统一按东八区（Asia/Shanghai / UTC+8）处理。


### 新建记录组

1. 首次访问首页
2. 选择“新建组”
3. 输入记录组名称
4. 等待管理员批准
5. 批准后回到首页即可开始记录

### 加入已有记录组

1. 在已开通设备的 `/me` 页面拿到加入码
2. 新设备访问首页，选择“加入组”
3. 输入加入码
4. 等待组内已批准设备确认
5. 批准后即可加入同一个记录组

### 管理记录组

访问 `/me` 可以：

- 修改记录组名称
- 查看加入码
- 管理当前设备和已批准设备
- 批准新加入设备
- 配置 Recovery Token
- 配置 API Token

### Recovery Token 说明

Recovery Token 是账号级恢复凭证，不是普通加入码。

- 默认关闭
- 只能由已批准账户自行设置或关闭
- 留空提交表示关闭
- 建议离线保存，不要只存在浏览器里
- 它是清空全部浏览器 Cookie 后，重新找回设备身份的唯一路径

当前规则：

- 长度必须在 `24` 到 `128` 字符之间
- 必须同时包含字母和数字
- 只允许字符：`A-Z a-z 0-9 - _ . ~`

### 加入码 vs Recovery Token

- **加入码**：用于把一个新浏览器/新设备提交到现有记录组，提交后默认进入待批准状态
- **Recovery Token**：用于在已知账号恢复凭证的前提下，直接批准当前浏览器，跳过待批准流程

### 管理员操作

管理员登录入口：

- `/admin/login`

管理员可以：

- 批准新建记录组
- 查看已开通记录组
- 删除整个记录组（会同时删除组、设备、记录）

## API

### 拉取记录

```bash
curl "http://127.0.0.1:18901/api/records?token=YOUR_TOKEN&since=1d"
```

支持的 `since` 参数：

- `30m` 最近 30 分钟
- `1h` 最近 1 小时
- `6h` 最近 6 小时
- `1d` 最近 1 天
- `7d` 最近 7 天

返回字段示例：

```json
{
  "user": "GOTI",
  "count": 2,
  "records": [
    {
      "id": 12,
      "content": "买电池",
      "created_at": "2026-04-25T14:10:00",
      "source_device_id": "device-uuid",
      "source_device_name": "iPhone"
    }
  ]
}
```

## 重置

如果你要清空测试数据并重新开始：

```bash
./scripts/reset-dev.sh
```

这个脚本会：

1. 备份当前数据库到 `data/backups/`
2. 删除当前数据库
3. 重新 build 并启动容器

## 数据目录

- 数据库：`data/quick_capture.db`
- 备份：`data/backups/`

## 开发说明

当前推荐开发方式是**直接在宿主机真仓库里开发**，不要再以其他机器上的副本为主，避免覆盖掉宿主机上更晚的改动。

典型流程：

```bash
ssh -p 59422 root@172.20.0.1
cd /root/dev/quick-capture
git status
# 修改代码
docker compose up -d --build quick-capture
git add .
git commit -m "your message"
git push origin HEAD
```

## 常用命令

### 重建服务

```bash
docker compose up -d --build quick-capture
```

### 查看日志

```bash
docker compose logs -f quick-capture
```

### 停止服务

```bash
docker compose stop quick-capture
```
