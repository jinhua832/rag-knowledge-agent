# 星尘笔记 OpenAPI 接入指南

> 面向第三方开发者的接口文档，最后更新于 2026-03-10。

## 一、基础信息

- 接口根地址：`https://api.xingchen-notes.com/v1`
- 所有请求与响应均为 `application/json`
- 所有时间字段为 ISO 8601 格式，时区为 UTC
- 请求需带 `Content-Type: application/json`

## 二、鉴权

在控制台「开发者设置」生成 Access Token，请求时放在 Header 中：

```
Authorization: Bearer <your_token>
```

- Token 有效期为 **30 天**，到期前 7 天可续期；
- 每个账号最多同时保留 5 个有效 Token；
- Token 泄露需立即在控制台吊销，吊销后 5 分钟内全网生效。

## 三、频率限制

| 版本 | 限制 |
| --- | --- |
| 免费版 | 60 次/分钟 |
| Pro 版 | 300 次/分钟 |
| 团队版 | 1000 次/分钟 |

超出限制返回 HTTP **429**，响应头 `Retry-After` 会给出建议等待的秒数（通常 10–60 秒）。建议客户端实现指数退避重试，最多重试 3 次。

## 四、错误码

| 状态码 | 含义 | 处理建议 |
| --- | --- | --- |
| 400 | 参数缺失或格式错误 | 检查请求体字段 |
| 401 | Token 无效或已过期 | 重新生成 Token |
| 403 | 权限不足（如免费版调用 Pro 接口） | 升级版本或改调对应接口 |
| 404 | 资源不存在 | 确认 note_id 是否正确 |
| 409 | 版本冲突（并发编辑同一篇笔记） | 拉取最新版本后重试 |
| 429 | 触发限流 | 按 Retry-After 等待后重试 |
| 500 | 服务端异常 | 记录 request_id 后联系技术支持 |

所有错误响应体格式统一为：

```json
{ "error": { "code": "RATE_LIMITED", "message": "too many requests", "request_id": "req_8f2c" } }
```

## 五、主要接口

### 5.1 创建笔记

`POST /notes`

```json
{ "title": "周会纪要", "content": "……", "tags": ["会议"] }
```

响应返回 `note_id`（24 位十六进制字符串）。单篇笔记正文上限 10 万字符。

### 5.2 获取笔记

`GET /notes/{note_id}`

### 5.3 搜索笔记

`GET /notes/search?q=关键词&limit=20&cursor=<cursor>`

- `limit` 最大 **100**，默认 20；
- 分页使用 `cursor` 游标，响应中 `next_cursor` 为空表示没有更多数据；
- 搜索为全文检索，支持中文分词，不支持正则表达式。

### 5.4 列出标签

`GET /tags`

### 5.5 Webhook

团队版可配置 Webhook，订阅 `note.created`、`note.updated`、`note.deleted` 三类事件。回调采用「至少一次」投递，失败重试 5 次，间隔分别为 1、5、30、300、1800 秒。回调需在 5 秒内返回 2xx，否则视为失败。

## 六、SDK 与示例

官方提供 Python 与 JavaScript SDK：

```bash
pip install xingchen-notes
```

```python
from xingchen_notes import Client

client = Client(token="<your_token>")
note = client.notes.create(title="周会纪要", content="……")
print(note["note_id"])
```

## 七、技术支持

- 文档问题：docs@xingchen-notes.com
- 接口故障：提交工单时请附上 `request_id`，工作日 2 小时内响应
- 沙箱环境：`https://sandbox-api.xingchen-notes.com/v1`，数据每日重置
