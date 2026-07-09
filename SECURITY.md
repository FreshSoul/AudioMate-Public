# 安全政策

## 漏洞报告

请将安全问题私下报告给项目维护者。不要在公开 issue 中提供可利用细节、密钥、私有项目路径或客户数据。

## 敏感信息

请不要提交：

- API Key 或 Provider Token。
- Session Cookie。
- 私有模型端点 URL。
- 客户或项目文件。
- 本地 `settings.json`、`chats/`、`knowledge/`、`logs/`、`memory/` 或 `reports/` 数据。

## 插件安全

Plugins 会执行本地 Python 代码。安装前请审阅插件源码，清楚记录写操作行为，并在 `plugin.json` 中为只读工具标记 `read_only`。
