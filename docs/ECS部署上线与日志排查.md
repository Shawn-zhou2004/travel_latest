# ECS 部署上线与日志排查

本文用于面试演示环境 `travel-latest`，服务器为 Ubuntu 22.04，项目目录为 `/opt/travel-latest`。

## 一、当前部署结构

项目使用 Docker Compose 运行以下服务：

```text
nginx          公网入口，监听 80
frontend-c     C 端静态页面
frontend-b     管理端静态页面
backend        FastAPI API
worker         RabbitMQ 事件消费者和 Outbox Worker
mysql          业务数据库
postgres       AI 记忆和 LangGraph Checkpointer 数据库
redis          缓存、Worker 心跳和聊天实时消息
rabbitmq       异步事件消息队列
elasticsearch  BM25 搜索
minio          私有媒体和导出文件存储
```

生产演示 Compose 文件：

```text
/opt/travel-latest/docker-compose.deploy.yml
```

## 二、SSH 登录

在本地 PowerShell 执行：

```powershell
ssh -i "D:\路径\travel-key.pem" ecs-user@47.113.185.195
```

登录后切换到项目目录：

```bash
cd /opt/travel-latest
```

如果提示私钥权限过宽，Windows 本地执行：

```powershell
icacls.exe "D:\路径\travel-key.pem" /inheritance:r
icacls.exe "D:\路径\travel-key.pem" /grant:r "${env:USERDOMAIN}\${env:USERNAME}:(R)"
```

## 三、启动服务

服务器重启后，Docker 服务会自动启动，Compose 容器也设置了 `restart: unless-stopped`。手动启动或补启动时执行：

```bash
cd /opt/travel-latest
docker compose -f docker-compose.deploy.yml --env-file .env up -d
```

首次部署或更新代码后重新构建：

```bash
cd /opt/travel-latest
docker compose -f docker-compose.deploy.yml --env-file .env up -d --build
```

只重启某个服务：

```bash
docker compose -f docker-compose.deploy.yml restart backend
docker compose -f docker-compose.deploy.yml restart worker
docker compose -f docker-compose.deploy.yml restart nginx
```

停止服务但保留数据库数据：

```bash
docker compose -f docker-compose.deploy.yml stop
```

启动已创建的容器：

```bash
docker compose -f docker-compose.deploy.yml start
```

不要使用下面的命令清理面试环境，因为它会删除 Compose 容器；带 `-v` 的命令还会删除数据库、MinIO 和 Elasticsearch 数据卷：

```bash
docker compose down -v
```

## 四、查看服务状态

查看全部服务：

```bash
docker compose -f docker-compose.deploy.yml ps
```

查看包括已退出的初始化容器：

```bash
docker compose -f docker-compose.deploy.yml ps -a
```

正常情况下应看到以下服务为 `Up`：

```text
backend
worker
mysql
postgres
redis
rabbitmq
elasticsearch
minio
frontend-c
frontend-b
nginx
```

`minio-init` 显示 `Exited (0)` 是正常的。它只负责创建 MinIO Bucket，完成后自动退出。

## 五、查看日志

### 5.1 查看所有服务最近 200 行日志

```bash
docker compose -f docker-compose.deploy.yml logs --tail=200
```

### 5.2 实时查看后端日志

```bash
docker compose -f docker-compose.deploy.yml logs -f --tail=200 backend
```

按 `Ctrl+C` 退出日志查看，不会停止服务。

### 5.3 实时查看 Worker 日志

```bash
docker compose -f docker-compose.deploy.yml logs -f --tail=200 worker
```

### 5.4 查看 Nginx 访问和错误日志

```bash
docker compose -f docker-compose.deploy.yml logs -f --tail=200 nginx
```

### 5.5 按时间查看最近 10 分钟日志

```bash
docker compose -f docker-compose.deploy.yml logs --since=10m backend worker nginx
```

### 5.6 只筛选错误关键词

```bash
docker compose -f docker-compose.deploy.yml logs --since=30m backend worker nginx | grep -Ei 'error|traceback|exception|failed|unauthorized|undefined'
```

没有匹配结果时，`grep` 会返回非 0 状态，这是正常的。

## 六、健康检查命令

### 6.1 从服务器内部检查 API

```bash
curl -i http://127.0.0.1/api/v1/health
```

预期结果：

```json
{"status":"ok","service":"ai-travel-api"}
```

### 6.2 从公网检查 API

```bash
curl -i http://47.113.185.195/api/v1/health
```

### 6.3 检查前端页面

```bash
curl -I http://47.113.185.195/
```

预期为 `HTTP/1.1 200 OK`。

### 6.4 检查 Worker 心跳

```bash
docker compose -f docker-compose.deploy.yml exec -T redis redis-cli GET ai_travel:worker:heartbeat
```

如果能返回最近的 ISO 时间，说明 Worker 正在运行。

### 6.5 检查 Nginx 配置

```bash
docker compose -f docker-compose.deploy.yml exec -T nginx nginx -t
```

预期：

```text
syntax is ok
test is successful
```

## 七、数据库迁移

每次首次部署或更新包含数据库结构变化的代码后执行：

```bash
docker compose -f docker-compose.deploy.yml exec -T backend alembic upgrade head
```

查看当前迁移版本：

```bash
docker compose -f docker-compose.deploy.yml exec -T backend alembic current
```

首次启用 AI 功能时初始化 PostgreSQL 和 LangGraph Checkpointer：

```bash
docker compose -f docker-compose.deploy.yml exec -T backend python -m app.modules.ai_memory.cli
```

初始化命令成功时会显示：

```text
AI PostgreSQL and LangGraph checkpoint schemas are initialized.
```

## 八、401、502 和 500 的区别

### 401 Unauthorized

通常表示后端已经收到请求，但请求没有有效登录凭证。常见情况：

- 第一次打开页面，浏览器还没有登录会话
- localStorage 中保存的是过期 Token
- Cookie 或 Authorization Header 不存在
- C 端会话被清理后，前端仍尝试刷新旧会话

浏览器控制台中看到：

```text
POST /api/v1/auth/sessions/refresh 401
```

不代表后端没有启动。先访问登录页面并重新登录即可。

清理当前站点旧会话的方法：

1. 打开浏览器开发者工具。
2. 进入 Application 或 Storage。
3. 清理当前网站的 Local Storage 和 Cookies。
4. 刷新页面，重新登录。

也可以使用无痕窗口重新访问：

```text
http://47.113.185.195/
```

### 502 Bad Gateway

通常表示 Nginx 找不到后端或前端上游服务。排查：

```bash
docker compose -f docker-compose.deploy.yml ps
docker compose -f docker-compose.deploy.yml logs --tail=200 backend nginx
```

重点检查 `backend` 是否为 `Up`，以及 Nginx 配置中的 `proxy_pass` 服务名是否正确。

### 500 Internal Server Error

表示请求已到达后端，但代码或依赖运行时报错。排查：

```bash
docker compose -f docker-compose.deploy.yml logs --since=10m backend
```

### 503 Service Unavailable

通常是外部 AI、Milvus、地图、对象存储或供应商服务不可用。查看后端日志中的具体依赖名称。

## 九、更新项目代码

如果代码已经提交到 GitHub：

```bash
cd /opt/travel-latest
docker compose -f docker-compose.deploy.yml --env-file .env up -d --build
docker compose -f docker-compose.deploy.yml exec -T backend alembic upgrade head
```

如果只是修改了 `.env`，不需要重新构建：

```bash
docker compose -f docker-compose.deploy.yml --env-file .env up -d
```

如果修改了 Nginx 配置：

```bash
docker compose -f docker-compose.deploy.yml --env-file .env up -d nginx
docker compose -f docker-compose.deploy.yml exec -T nginx nginx -t
```

## 十、磁盘和 Docker 清理

查看磁盘：

```bash
df -h
docker system df
```

查看数据盘：

```bash
df -h /data
```

只删除未使用的构建缓存：

```bash
docker builder prune
```

不要在没有确认的情况下使用：

```bash
docker system prune -a --volumes
```

它可能删除未使用镜像和数据卷，面试演示环境不建议执行。

## 十一、当前演示地址

C 端：

```text
http://47.113.185.195/
```

API 健康检查：

```text
http://47.113.185.195/api/v1/health
```

管理端的正式域名和 HTTPS 证书尚未配置。当前 Compose 为管理端预留了 `admin.example.com`，使用真实域名前需要修改 Nginx 配置并申请证书。
