# AudioMate 文档

这个目录存放 AudioMate 开源桌面应用的用户文档和开发文档。

## 推荐入口

- [Plugin 开发格式](plugin-development-format.md)：如何编写本地 Python 插件。
- [新手教程](新手教程.md)：面向最终用户的工作流说明。
- [Wwise 操作正确率与复杂系统评测](wwise-operation-evaluation.md)：如何评测 WAAPI 操作、真实工程结果和复杂声音系统实现程度。

## 扩展模型

AudioMate 支持两类本地扩展：

- **Skills**：用 Markdown 指令和可选元数据引导 Agent 行为。
- **Plugins**：用 Python 包注册可被 Agent 调用的工具。

Skills 和 Plugins 可以作为普通文件夹、压缩包或版本化包共享。
