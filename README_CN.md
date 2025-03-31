# Ollama Monitor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.7%2B-blue) (https://www.python.org/)

[English](README.md) | [中文](README_CN.md)

## 一个简单实用的 Ollama 服务监控工具，提供实时指标统计、请求分析和资源使用监控，并配有直观的 Web 界面。

## 功能特性

* **实时监控仪表板** ：通过浏览器随时查看 Ollama 服务的运行状态
* **完整的请求统计** ：记录所有 API 请求，包括客户端 IP、请求模型、输入/输出 token
* **系统资源监控** ：追踪 CPU、内存、磁盘使用率和网络流量
* **模型使用分析** ：分析不同模型的使用频率和性能
* **直观的图表展示** ：使用交互式图表可视化关键指标变化趋势
* **可作为 API 代理** ：可同时作为 Ollama API 的代理服务器使用
* **支持系统服务部署** ：可作为系统守护进程长期稳定运行

![dashboard](ollama_monitor_dashboard.png)

## 快速开始

### 安装依赖

```bash
pip install flask waitress requests psutil
```

### 启动监控工具

```bash
python ollama_monitor.py
```

启动后，在浏览器中访问 `http://localhost:8080` 即可打开监控仪表板。

### 安装为系统服务

```bash
python ollama_monitor.py --install
```

然后按照终端提示完成系统服务的安装：

```bash
sudo cp /tmp/ollama-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ollama-monitor
sudo systemctl start ollama-monitor
```

## 配置选项

您可以在脚本顶部修改以下配置参数：

```python
# 配置参数
OLLAMA_HOST = "http://localhost:11434"  # Ollama 服务地址
MONITOR_INTERVAL = 60  # 监控间隔(秒)
WEB_HOST = "0.0.0.0"   # Web 服务监听地址
WEB_PORT = 8080        # Web 服务监听端口
DB_FILE = "ollama_metrics.db"  # 数据库文件路径
```

## 监控指标说明

### 系统指标

* 服务器状态：Ollama 服务是否正常运行
* CPU 使用率：系统和 Ollama 进程的 CPU 使用情况
* 内存使用率：系统和 Ollama 进程的内存使用情况
* 磁盘使用率：系统磁盘空间使用情况
* 网络流量：发送和接收的网络数据量

### 请求指标

* 总请求数：处理的 API 请求总数
* 平均响应时间：请求的平均响应时间
* 输入/输出 Token：处理的输入和输出 token 总量
* 客户端 IP 统计：各 IP 地址的请求数统计
* 模型使用统计：各模型的使用频率和性能数据

## 作为 API 代理使用

除了监控功能外，该工具还可以作为 Ollama API 的代理服务使用。通过请求下面的地址使用 API 服务：

```
http://your-server:8080/ollama/api/...
```

这样所有的请求都会被记录并计入统计数据。

## 数据存储

所有监控数据存储在 SQLite 数据库中，默认文件名为 `ollama_metrics.db`。您可以使用任何 SQLite 浏览工具查看或分析这些数据。

## 系统要求

* Python 3.7+
* 操作系统：Linux、macOS 或 Windows
* 支持 Ollama 服务的所有平台

## 贡献指南

欢迎提交问题报告和功能请求！如果您想贡献代码，请先开 issue 讨论您想要进行的更改。

## 许可证

MIT 许可证 - 详情请查看 [LICENSE](https://poe.com/chat/LICENSE) 文件。

## 致谢

* [Ollama](https://github.com/ollama/ollama) - 令人惊叹的本地大语言模型运行工具
* [Flask](https://flask.palletsprojects.com/) - 提供 Web 服务功能
* [Chart.js](https://www.chartjs.org/) - 提供数据可视化功能
* [Waitress](https://docs.pylonsproject.org/projects/waitress/) - 提供生产级 WSGI 服务

## 联系方式

如有问题或建议，请通过 GitHub Issues 提交。

---

希望 Ollama Monitor 能帮助您更有效地管理和监控您的 Ollama 服务！
