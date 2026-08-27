# VM 开发服务启停手册

更新时间：2026-08-22

## 当前环境

Windows 开发机通过 VMware NAT 网络访问 CentOS 7 虚拟机。当前已验证的地址如下：

| 项目 | 地址 |
|---|---|
| Windows VMnet8 | `192.168.142.1` |
| CentOS VM | `192.168.142.50` |
| MySQL | `192.168.142.50:3306` |
| Redis | `192.168.142.50:6379` |
| RabbitMQ AMQP | `192.168.142.50:5672` |
| RabbitMQ 管理台 | `http://192.168.142.50:15672` |
| Elasticsearch | `http://192.168.142.50:9200` |
| PostgreSQL | `192.168.142.50:5432` |

根目录 `.env` 使用这些 VM 地址，不要使用 `127.0.0.1`。Windows 上的 `127.0.0.1` 只表示 Windows 自己；CentOS 上的 `127.0.0.1` 才表示虚拟机自己。

`.env` 不可提交到 Git。密码如包含 `@`、`:`、`/`、`?` 或 `#`，必须在连接 URL 中进行 URL 编码。

```dotenv
MYSQL_DSN=mysql+pymysql://travel_app:<password>@192.168.142.50:3306/ai_travel_platform
REDIS_URL=redis://192.168.142.50:6379/0
RABBITMQ_URL=amqp://<user>:<password>@192.168.142.50:5672/
ELASTICSEARCH_URL=http://192.168.142.50:9200
AI_POSTGRES_DSN=postgresql://ai_app:<password>@192.168.142.50:5432/ai_travel_ai
```

项目采用双数据库：MySQL 存业务数据（用户、订单、确认后的行程）；PostgreSQL 只存 AI 私有数据（LangGraph checkpoint、行程 preview、审计、AI 会话、长期记忆）。AI 模块全部通过根目录 `.env` 的 `AI_POSTGRES_DSN` 连接 PG，不使用 MySQL。

## 每次开发前检查

在 Windows PowerShell 执行。五项都应为 `True`：

```powershell
Test-NetConnection 192.168.142.50 -Port 3306
Test-NetConnection 192.168.142.50 -Port 6379
Test-NetConnection 192.168.142.50 -Port 5672
Test-NetConnection 192.168.142.50 -Port 9200
Test-NetConnection 192.168.142.50 -Port 5432
```

也可检查 HTTP 服务：

```powershell
Invoke-RestMethod http://192.168.142.50:9200/_cluster/health
```

Elasticsearch 返回中的 `status` 应为 `green` 或开发期可接受的 `yellow`。

## MySQL

MySQL 8.0.27 二进制目录为 `/usr/local/mysql/mysql8`，现有数据目录为 `/usr/local/mysql/data`。该目录包含其他项目的历史数据，因此禁止运行 `mysqld --initialize` 或删除其中的文件。

### 检查与连接

在 CentOS 执行：

```bash
ps -ef | grep '[m]ysqld'
ss -lntp | grep 3306
/usr/local/mysql/mysql8/bin/mysql -h 127.0.0.1 -P 3306 -uroot -p
```

客户端必须显式使用 `-h 127.0.0.1 -P 3306`，因为该 MySQL 的 socket 不在客户端默认查找的 `/tmp/mysql.sock`。

### 启动与关闭

MySQL 已登记为 `systemd` 服务，服务文件为 `/etc/systemd/system/mysql.service`。该服务使用已验证的参数启动：

```text
/usr/local/mysql/mysql8/bin/mysqld --defaults-file=/etc/my.cnf --console
```

日常启动 MySQL：

```bash
systemctl start mysql
```

检查服务状态：

```bash
systemctl status mysql --no-pager
ss -lntp | grep 3306
```

正常状态应显示 `Active: active (running)`，并且 `3306` 端口处于监听状态。

虚拟机重启后，MySQL 会因为已经执行过 `systemctl enable mysql` 而自动启动。确认开机自启状态：

```bash
systemctl is-enabled mysql
```

正常结果为：

```text
enabled
```

日常停止、重启和设置开机自启：

```bash
systemctl stop mysql
systemctl restart mysql
systemctl enable mysql
```

不要再直接执行 `mysqld --console`，否则可能与 systemd 管理的 MySQL 进程重复启动并争用数据目录或 3306 端口。也不要运行 `mysqld --initialize`，更不能删除 `/usr/local/mysql/data` 中的文件；该数据目录包含其他项目的历史数据。

如果启动失败，查看 systemd 日志：

```bash
journalctl -u mysql -n 100 --no-pager
```

如果修改了 `/etc/my.cnf` 或 `/etc/systemd/system/mysql.service`，先重新加载配置，再重启服务：

```bash
systemctl daemon-reload
systemctl restart mysql
```

## Redis

Redis 程序目录为 `/usr/local/bin`，配置文件为 `/usr/local/bin/redis-stable/redis.conf`。配置的 `daemonize yes` 会使启动命令立即返回，Redis 继续在后台运行。

### 启动

以 `root` 执行：

```bash
cd /usr/local/bin
./redis-server ./redis-stable/redis.conf
```

### 检查

```bash
ps -ef | grep '[r]edis-server'
ss -lntp | grep 6379
/usr/local/bin/redis-cli -h 127.0.0.1 -p 6379 ping
```

最后一条应返回 `PONG`。

### 关闭

```bash
/usr/local/bin/redis-cli -h 127.0.0.1 -p 6379 shutdown
```

首次启动看到 `vm.overcommit_memory` 警告不阻止开发，但应由 root 持久修复：

```bash
sysctl -w vm.overcommit_memory=1
printf 'vm.overcommit_memory = 1\n' >> /etc/sysctl.conf
sysctl -p
```

## RabbitMQ

RabbitMQ 运行在 Docker 容器 `rabbitmq` 中，容器将 VM 的 `5672` 和 `15672` 映射出去。

### 启动

```bash
docker start rabbitmq
docker exec rabbitmq rabbitmqctl await_startup
```

### 检查

```bash
docker ps --filter "name=^/rabbitmq$" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
docker exec rabbitmq rabbitmqctl list_users
docker exec rabbitmq rabbitmqctl list_vhosts
```

### 关闭

```bash
docker stop rabbitmq
```

使 Docker 服务或 VM 重启后自动恢复：

```bash
docker update --restart unless-stopped rabbitmq
```

管理台地址为 `http://192.168.142.50:15672`。项目应使用专用 RabbitMQ 账号，不要共享其他项目的管理账号。

## Elasticsearch

Elasticsearch 目录为 `/usr/local/es/elasticsearch-8.14.3`，必须使用非 root 用户 `es` 启动。当前为前台运行模式，关闭启动它的终端或按 `Ctrl+C` 都会停止服务。

### 启动

先以 root 登录 CentOS，再执行：

```bash
su es
cd /usr/local/es/elasticsearch-8.14.3
./bin/elasticsearch
```

已经处于 `[es@localhost ...]$` 提示符时，不要再次执行 `su es` 或 `su - es`。要返回 root shell，执行 `exit`；若该命令直接断开 SSH，则重新以 Linux root 用户登录。MySQL 的 root 密码不能用于 Linux root 登录。

### 检查

另开一个 CentOS 终端：

```bash
ss -lntp | grep 9200
curl http://127.0.0.1:9200/_cluster/health
```

Windows 侧检查：

```powershell
Invoke-RestMethod http://192.168.142.50:9200/_cluster/health
```

### 关闭

在运行 `./bin/elasticsearch` 的前台终端按 `Ctrl+C`，等待进程退出。不要使用 `kill -9`。

### 待完成的持久化修复

当前配置曾将 `path.logs` 指向数据目录。下次以 root 修改 `/usr/local/es/elasticsearch-8.14.3/config/elasticsearch.yml`，确保存在以下两项：

```yaml
path.data: /usr/local/es/elasticsearch-8.14.3/data
path.logs: /usr/local/es/elasticsearch-8.14.3/logs
```

然后修正目录属主：

```bash
chown -R es:es /usr/local/es/elasticsearch-8.14.3/data /usr/local/es/elasticsearch-8.14.3/logs
chmod 750 /usr/local/es/elasticsearch-8.14.3/data /usr/local/es/elasticsearch-8.14.3/logs
```

后续应为 Elasticsearch 建立 `systemd` 服务。此操作需要结合 VM 内核参数、内存大小和现有路径单独验证。

## PostgreSQL

PostgreSQL 16 运行在 Docker 容器中（版本串含 `linux-musl`，即 Alpine 系镜像），将 VM 的 `5432` 映射出去，数据库为 `ai_travel_ai`。它只服务 AI 模块：LangGraph checkpoint、行程 preview、审计、AI 会话和长期记忆都在这里；业务数据仍在 MySQL。

### 启动与关闭

先确认容器名（下文以 `postgres` 为例，以 `docker ps` 实际输出为准）：

```bash
docker ps -a | grep -i postgres
```

日常启停：

```bash
docker start postgres
docker stop postgres
```

使 Docker 服务或 VM 重启后自动恢复：

```bash
docker update --restart unless-stopped postgres
```

### 检查

在 CentOS 执行：

```bash
docker ps --filter "name=postgres" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
docker exec postgres pg_isready -U ai_app -d ai_travel_ai
```

`pg_isready` 应返回 `accepting connections`。

Windows 侧检查端口：

```powershell
Test-NetConnection 192.168.142.50 -Port 5432
```

深度验证（真实连接，需在 `backend` 目录的虚拟环境中执行；输出 `server version: 160014` 即 16.14 正常）：

```powershell
cd backend
.\.venv\Scripts\python.exe -c "import asyncio, psycopg; from app.core.settings import Settings; asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy()); conn = asyncio.run(psycopg.AsyncConnection.connect(Settings().ai_postgres_dsn)); print('Connected, server version:', conn.info.server_version)"
```

端口通但 AI 功能报数据库错误时，优先怀疑 PG 容器停止或表结构未初始化；后端启动时会在连接池初始化阶段自动建表（`ai_conversations`、`ai_messages`、`ai_assistant_runs`、`ai_memories`、`ai_memory_projection_tasks`、`ai_generation_previews`、`ai_preview_citations`、`ai_preview_audits`）。

## 防火墙

当前服务只应允许 Windows VMnet8 地址 `192.168.142.1` 访问。检查现有规则：

```bash
firewall-cmd --list-rich-rules
```

新增规则的通用形式如下，替换端口后执行：

```bash
firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="192.168.142.1/32" port protocol="tcp" port="<port>" accept'
firewall-cmd --reload
```

RabbitMQ 管理端口 `15672` 不应向公网开放。Redis 当前无密码，MySQL 和 RabbitMQ 均应使用项目专用账号和强密码。

## Nginx 与上线

当前本地开发不需要启动 Nginx：FastAPI 在 Windows 的 `http://localhost:8000` 运行，两个 Vite 前端分别运行在 `http://localhost:5173` 和 `http://localhost:5174`。Nginx 不会替代这些开发服务器。

仓库中的 `docker-compose.yml` 只适用于将基础设施和 Nginx 都运行在同一台本机 Docker 主机的场景。当前服务在 VM 中运行，因此不要从 Windows 项目根目录执行 `docker compose up -d`，否则会再创建一套本地基础设施，并可能与本机端口冲突。

上线时需要运行 Nginx，但部署模式会改变：

1. 构建两个前端，Nginx 提供静态文件。
2. Nginx 将 `/api/` 反向代理到长期运行的 FastAPI 进程。
3. Nginx 终止 HTTPS，并设置真实客户端 IP、上传大小、超时和安全响应头。
4. MySQL、Redis、RabbitMQ 和 Elasticsearch 应运行在受限私网，应用通过内网访问；管理端口不得公开暴露。
5. FastAPI 和 Worker 应由 `systemd`、Docker Compose、Kubernetes 或等价进程管理器维持运行和自动重启，不能依赖 SSH 前台终端。

部署到公网前必须替换所有弱密码，设置随机 `JWT_SECRET`，配置生产 `CORS_ORIGINS`，启用 TLS，并将 Redis、RabbitMQ、MySQL 和 Elasticsearch 的访问范围限制为应用网络。当前的 VM NAT 开发配置不能原样用于生产。

## API 与 Worker

API 和 Worker 运行在 Windows 开发机，不在 CentOS 基础设施 VM 中运行。API 启动：

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

健康检查：

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/health
```

Worker 配置检查和启动：

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.workers.main --check-config
.\.venv\Scripts\python.exe -m app.workers.main
```

开发 seed：

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.seed
```

Worker 当前只发布 Outbox 事件并运行已注册的消费者；具体领域模块完成后会注册行程、搜索、通知、订单等消费者。




