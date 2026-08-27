# MinIO 私有媒体运维

## 媒体浏览器直传集成冒烟测试

`backend/tests/integration/test_minio_media_direct_put.py` 使用当前已配置的私有
S3/MinIO 设置，生成一个 `image/jpeg` PUT 预签名 URL，并用无 Cookie、无额外凭据的
HTTP 客户端直接上传固定字节。测试随后以 HeadObject 验证对象大小、`Content-Type`、
ETag 和 `x-amz-meta-sha256` 元数据，并在 `finally` 中删除 UUID 键
`media/integration-smoke/` 下的对象。测试不会输出预签名 URL、访问密钥或密钥值。

默认不会连接 MinIO。满足私有 bucket 已存在、endpoint 可达且已配置受限 S3 凭据后，
从 `backend` 目录显式启用：

```bash
RUN_MINIO_INTEGRATION_TESTS=true pytest tests/integration/test_minio_media_direct_put.py
```

默认跳过验证可运行：

```bash
pytest tests/integration/test_minio_media_direct_put.py
```

### 生产浏览器 CORS

上述测试不执行浏览器 CORS 预检。要让消费者前端从浏览器直传私有 MinIO bucket，bucket
CORS 规则必须满足以下条件：

1. `AllowedOrigin` 精确列出每个消费者前端 origin，例如开发环境的
   `http://localhost:5173`；生产环境填写实际的 `https://` origin。不要使用 `*`。
2. `AllowedMethod` 包含 `PUT`。
3. `AllowedHeader` 至少包含预签名请求实际签名并发送的 `Content-Type` 和
   `x-amz-meta-sha256`。若客户端或代理会发送其他请求头，也必须逐项加入，且这些头应与
   生成预签名 URL 时的签名约束一致。
4. `ExposeHeader` 包含 `ETag`，以便浏览器端在需要时读取上传响应的 ETag。

应用 API 的 CORS 设置不能替代 MinIO bucket CORS：浏览器 PUT 的目标是预签名的对象存储
URL。跨域直传应保持 `credentials: "omit"`，不得在请求中附加应用认证头、Cookie 或 S3
访问密钥。

### 非敏感验证步骤

1. 使用上面的显式命令运行冒烟测试，只记录 pytest 的通过、失败或跳过结果。
2. 在 MinIO 控制台或受限审计界面确认测试生成的对象已清理；无需复制对象 URL 或签名查询参数。
3. 从允许的消费者 origin 发起浏览器预检和一次测试上传，确认 PUT 成功且可读取 `ETag`；
   记录 HTTP 状态、请求 origin、方法和响应头名称，不记录预签名 URL、签名参数或任何密钥。

## 导出对象集成冒烟测试

`backend/tests/integration/test_minio_export_storage.py` 使用当前已配置的私有 S3/MinIO
设置，验证服务端生成的 DOCX 导出对象上传、HeadObject 元数据和附件下载预签名 URL。
测试会创建一个带 UUID 的 `exports/integration-smoke/` 对象，并始终尝试删除该对象；它不会下载或输出预签名 URL。

默认不会连接 MinIO。仅在以下前提均满足时运行：

1. MinIO/S3 endpoint 可从运行测试的主机访问，且私有 bucket 已存在。
2. 已通过受限权限的环境变量或应用 `.env` 配置 `S3_ENDPOINT_URL`、`S3_REGION`、`S3_ACCESS_KEY_ID`、`S3_SECRET_ACCESS_KEY` 和 `S3_BUCKET_PRIVATE`；按部署需要配置 `S3_USE_PATH_STYLE`。
3. 所用凭据仅具备该私有 bucket 的对象写入、读取元数据、生成预签名 URL 和删除权限。

在应用虚拟环境中，从 `backend` 目录显式启用：

```bash
RUN_MINIO_INTEGRATION_TESTS=true pytest tests/integration/test_minio_export_storage.py
```

不要将访问密钥、密钥值或完整预签名 URL 写入 shell 历史、CI 日志、工单或测试输出。未设置
`RUN_MINIO_INTEGRATION_TESTS=true` 时，该测试会被跳过，不会初始化 S3 客户端或发出网络请求。

## 统一过期清理入队

未完成的私有媒体上传和成功生成的 DOCX 导出都由 Worker 清理。统一运维命令在同一个 MySQL
事务中向 Outbox 写入 `media.expired_upload_cleanup_requested` 和
`export_task.expiration_cleanup_requested` 两个事件，然后只提交一次。命令本身不会扫描或删除
MinIO 对象。

媒体清理 Worker 收到事件后会将过期的待上传记录标为 `expired`，并对对应对象作一次尽力删除。
导出清理 Worker 只处理 `succeeded` 且已到期的导出任务，将任务变为 `expired`，并对导出对象
作一次尽力删除。当前成功导出保留期为七天；`queued`、`running`、`failed` 和 `cancelled` 任务
不会被清理。

在已加载生产环境变量的应用目录中执行：

```bash
cd /srv/ai-travel/backend
/srv/ai-travel/backend/.venv/bin/python -m app.modules.media.cli enqueue-expired-cleanup
```

成功时标准输出只包含两个事件的 `event_id` 和 `event_type`，每个事件一行。配置或 MySQL 连接
失败时命令以状态码 `2` 退出，且不会输出连接字符串、密码或其他密钥。旧的
`enqueue-expired-upload-cleanup` 命令仍可用于仅入队媒体上传清理。

## 定时执行

建议在运行应用代码且可访问 MySQL 的 VM 上每五分钟执行一次。使用专用的、最小权限的系统账户，并将标准输出与错误输出写入受限权限的日志目录。

Cron 示例：

```cron
*/5 * * * * appuser cd /srv/ai-travel/backend && /srv/ai-travel/backend/.venv/bin/python -m app.modules.media.cli enqueue-expired-cleanup >> /var/log/ai-travel/media-cleanup.log 2>&1
```

也可以创建同一命令的 `systemd` oneshot service，并由 timer 每五分钟触发：

```ini
# /etc/systemd/system/ai-travel-media-cleanup.service
[Service]
Type=oneshot
User=appuser
WorkingDirectory=/srv/ai-travel/backend
ExecStart=/srv/ai-travel/backend/.venv/bin/python -m app.modules.media.cli enqueue-expired-cleanup
```

```ini
# /etc/systemd/system/ai-travel-media-cleanup.timer
[Timer]
OnCalendar=*:0/5
Persistent=true

[Install]
WantedBy=timers.target
```

启用 timer：

```bash
systemctl enable --now ai-travel-media-cleanup.timer
```

不要把 `.env`、数据库 URL、MinIO 密钥或 RabbitMQ 凭据写入 cron 行、unit 文件或日志。

## 验证结果

1. 手动执行统一命令，确认输出恰有两个事件 ID，类型分别为 `media.expired_upload_cleanup_requested` 和 `export_task.expiration_cleanup_requested`。
2. 在 MySQL 中按两个 ID 查询 `outbox_events`，确认两条记录都存在；Worker 发布后各自的 `published_at` 应不为空。
3. 确认对应 Worker 消费成功：`processed_events` 中应分别存在 `consumer_name = media.expired_upload_cleanup` 和 `consumer_name = exports.expiration_cleanup` 的事件 ID。

若事件未发布，先检查 Worker 与 RabbitMQ 的运行状态；若事件已发布但未消费，检查 Worker 日志和死信队列。重复执行入队命令是安全的：每次会产生新的 Outbox 事件，清理处理只作用于仍为 `pending` 的过期上传或仍为 `succeeded` 的到期导出。
