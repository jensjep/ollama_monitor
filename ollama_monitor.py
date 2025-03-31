import requests
import time
import psutil
import json
import socket
import logging
import threading
import sqlite3
import os
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, send_from_directory
from waitress import serve
from werkzeug.middleware.proxy_fix import ProxyFix

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='ollama_monitor.log'
)
logger = logging.getLogger('ollama_monitor')

# 配置参数
OLLAMA_HOST = "http://localhost:11434"
MONITOR_INTERVAL = 60  # 监控间隔(秒)
WEB_HOST = "0.0.0.0"
WEB_PORT = 8080
DB_FILE = "ollama_metrics.db"

class OllamaMetricsDB:
    def __init__(self, db_file=DB_FILE):
        """初始化数据库连接"""
        self.db_file = db_file
        self._create_tables()
    
    def _create_tables(self):
        """创建必要的数据表"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        # 系统指标表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            server_status INTEGER,
            cpu_percent REAL,
            memory_percent REAL,
            disk_percent REAL,
            network_bytes_sent INTEGER,
            network_bytes_recv INTEGER,
            ollama_cpu_percent REAL,
            ollama_memory_percent REAL,
            ollama_connections INTEGER
        )
        ''')
        
        # 请求日志表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS request_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            client_ip TEXT,
            model_name TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            response_time REAL,
            status_code INTEGER,
            endpoint TEXT
        )
        ''')
        
        # 模型表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            model_name TEXT,
            model_size TEXT,
            parameter_size TEXT,
            modified_at TEXT,
            model_family TEXT
        )
        ''')
        
        conn.commit()
        conn.close()
    
    def save_system_metrics(self, metrics):
        """保存系统指标"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        ollama_process = metrics.get('ollama_process', {})
        
        cursor.execute('''
        INSERT INTO system_metrics (
            timestamp, server_status, cpu_percent, memory_percent, 
            disk_percent, network_bytes_sent, network_bytes_recv,
            ollama_cpu_percent, ollama_memory_percent, ollama_connections
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            metrics['timestamp'],
            1 if metrics['server_status'] else 0,
            metrics['system']['cpu_percent'],
            metrics['system']['memory_percent'],
            metrics['system']['disk_percent'],
            metrics['system']['network_bytes_sent'],
            metrics['system']['network_bytes_recv'],
            ollama_process.get('cpu_percent', 0),
            ollama_process.get('memory_percent', 0),
            ollama_process.get('connections', 0)
        ))
        
        conn.commit()
        conn.close()
    
    def save_models(self, timestamp, models):
        """保存模型信息"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        for model in models:
            details = model.get('details', {})
            cursor.execute('''
            INSERT INTO models (
                timestamp, model_name, model_size, parameter_size, 
                modified_at, model_family
            ) VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                timestamp,
                model.get('name', ''),
                str(model.get('size', 0)),
                details.get('parameter_size', ''),
                model.get('modified_at', ''),
                details.get('family', '')
            ))
        
        conn.commit()
        conn.close()
    
    def save_request_log(self, log_data):
        """保存请求日志"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO request_logs (
            timestamp, client_ip, model_name, input_tokens, 
            output_tokens, response_time, status_code, endpoint
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            log_data['timestamp'],
            log_data['client_ip'],
            log_data['model_name'],
            log_data['input_tokens'],
            log_data['output_tokens'],
            log_data['response_time'],
            log_data['status_code'],
            log_data['endpoint']
        ))
        
        conn.commit()
        conn.close()
    
    def get_recent_system_metrics(self, hours=24):
        """获取最近的系统指标"""
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT * FROM system_metrics
        WHERE timestamp > datetime('now', ?)
        ORDER BY timestamp
        ''', (f'-{hours} hours',))
        
        rows = cursor.fetchall()
        result = [dict(row) for row in rows]
        
        conn.close()
        return result
    
    def get_recent_requests(self, hours=24):
        """获取最近的请求日志"""
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT * FROM request_logs
        WHERE timestamp > datetime('now', ?)
        ORDER BY timestamp DESC
        ''', (f'-{hours} hours',))
        
        rows = cursor.fetchall()
        result = [dict(row) for row in rows]
        
        conn.close()
        return result
    
    def get_client_ip_stats(self, hours=24):
        """获取客户端IP统计"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT client_ip, COUNT(*) as request_count 
        FROM request_logs
        WHERE timestamp > datetime('now', ?)
        GROUP BY client_ip
        ORDER BY request_count DESC
        ''', (f'-{hours} hours',))
        
        result = cursor.fetchall()
        conn.close()
        return result
    
    def get_model_usage_stats(self, hours=24):
        """获取模型使用统计"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT model_name, 
               COUNT(*) as request_count,
               SUM(input_tokens) as total_input_tokens,
               SUM(output_tokens) as total_output_tokens,
               AVG(response_time) as avg_response_time
        FROM request_logs
        WHERE timestamp > datetime('now', ?)
        GROUP BY model_name
        ORDER BY request_count DESC
        ''', (f'-{hours} hours',))
        
        result = cursor.fetchall()
        conn.close()
        return result
    
    def get_latest_models(self):
        """获取最新的模型列表"""
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT * FROM models
        WHERE timestamp = (SELECT MAX(timestamp) FROM models)
        ''')
        
        rows = cursor.fetchall()
        result = [dict(row) for row in rows]
        
        conn.close()
        return result

class OllamaMonitor:
    def __init__(self, host=OLLAMA_HOST, interval=MONITOR_INTERVAL):
        """
        初始化Ollama监控器
        
        参数:
            host: Ollama服务的URL
            interval: 检查间隔(秒)
        """
        self.host = host
        self.interval = interval
        self.api_endpoint = f"{host}/api"
        self.db = OllamaMetricsDB()
        self.running = True
        self.default_model = None
    
    def get_models(self):
        """获取所有可用的模型"""
        try:
            response = requests.get(f"{self.api_endpoint}/tags")
            if response.status_code == 200:
                models = response.json().get('models', [])
                # 更新默认模型
                if models and not self.default_model:
                    self.default_model = models[0].get('name')
                return models
            else:
                logger.error(f"获取模型列表失败: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"获取模型列表异常: {str(e)}")
            return []
    
    def get_model_details(self, model_name):
        """获取模型详细信息"""
        try:
            data = {"model": model_name}
            response = requests.post(f"{self.api_endpoint}/show", json=data)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"获取模型详情失败: {response.status_code}")
                return {}
        except Exception as e:
            logger.error(f"获取模型详情异常: {str(e)}")
            return {}
    
    def get_server_status(self):
        """检查服务器状态"""
        try:
            # 使用/api/tags接口检查服务状态，更可靠
            response = requests.get(f"{self.api_endpoint}/tags")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"服务器状态检查异常: {str(e)}")
            return False
    
    def get_system_metrics(self):
        """获取系统资源指标"""
        metrics = {
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage('/').percent,
        }
        
        # 获取网络使用数据
        network = psutil.net_io_counters()
        metrics["network_bytes_sent"] = network.bytes_sent
        metrics["network_bytes_recv"] = network.bytes_recv
        
        return metrics
    
    def get_ollama_process_info(self):
        """获取Ollama进程的资源使用情况"""
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            if 'ollama' in proc.info['name'].lower():
                return {
                    "pid": proc.info['pid'],
                    "cpu_percent": proc.info['cpu_percent'],
                    "memory_percent": proc.info['memory_percent'],
                    "connections": len(proc.connections())
                }
        return None
    
    def test_model_generation(self, model_name=None):
        """测试模型生成能力"""
        if not model_name and self.default_model:
            model_name = self.default_model
        
        if not model_name:
            logger.warning("没有可用的模型来测试生成能力")
            return None
        
        try:
            start_time = time.time()
            prompt = "Hello, world!"
            data = {
                "model": model_name,
                "prompt": prompt,
                "stream": False
            }
            response = requests.post(f"{self.api_endpoint}/generate", json=data)
            response_time = time.time() - start_time
            
            if response.status_code == 200:
                result = response.json()
                log_data = {
                    "timestamp": datetime.now().isoformat(),
                    "client_ip": "127.0.0.1",  # 内部测试
                    "model_name": model_name,
                    "input_tokens": result.get('prompt_eval_count', 0),
                    "output_tokens": result.get('eval_count', 0),
                    "response_time": response_time,
                    "status_code": response.status_code,
                    "endpoint": "/api/generate"
                }
                self.db.save_request_log(log_data)
                return response_time
            else:
                logger.error(f"模型生成测试失败: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"模型生成测试异常: {str(e)}")
            return None
    
    def run(self):
        """运行监控循环"""
        logger.info("Ollama监控服务已启动")
        
        while self.running:
            try:
                timestamp = datetime.now().isoformat()
                
                # 检查服务器状态
                server_status = self.get_server_status()
                
                # 收集系统指标
                metrics = {
                    "timestamp": timestamp,
                    "server_status": server_status,
                    "system": self.get_system_metrics(),
                    "ollama_process": self.get_ollama_process_info() or {},
                }
                
                # 保存系统指标
                self.db.save_system_metrics(metrics)
                
                # 如果服务器在线，获取并保存模型列表
                if server_status:
                    models = self.get_models()
                    if models:
                        self.db.save_models(timestamp, models)
                        
                        # 测试默认模型的生成能力
                        self.test_model_generation()
                
                # 等待下一个间隔
                time.sleep(self.interval)
            except Exception as e:
                logger.error(f"监控循环异常: {str(e)}")
                time.sleep(10)  # 发生错误时短暂暂停后重试
    
    def stop(self):
        """停止监控循环"""
        self.running = False

# 创建Flask应用
app = Flask(__name__, static_folder='static')
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# 确保静态文件夹存在
if not os.path.exists('static'):
    os.makedirs('static')

# 创建CSS和JS文件
with open('static/style.css', 'w') as f:
    f.write('''
body {
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    margin: 0;
    padding: 0;
    background-color: #f5f7fa;
    color: #333;
}

.container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 20px;
}

header {
    background-color: #2c3e50;
    color: white;
    padding: 15px 0;
    margin-bottom: 20px;
}

header h1 {
    margin: 0;
    padding: 0 20px;
}

.card {
    background-color: white;
    border-radius: 8px;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    margin-bottom: 20px;
    padding: 20px;
}

.card h2 {
    margin-top: 0;
    color: #2c3e50;
    border-bottom: 1px solid #eee;
    padding-bottom: 10px;
}

.chart-container {
    height: 300px;
    margin-bottom: 20px;
}

table {
    width: 100%;
    border-collapse: collapse;
}

table th, table td {
    padding: 12px 15px;
    text-align: left;
    border-bottom: 1px solid #ddd;
}

table th {
    background-color: #f8f9fa;
    color: #2c3e50;
}

tr:hover {
    background-color: #f5f5f5;
}

.dashboard {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 20px;
    margin-bottom: 20px;
}

.stat-card {
    background-color: white;
    border-radius: 8px;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    padding: 20px;
    text-align: center;
}

.stat-value {
    font-size: 2rem;
    font-weight: bold;
    color: #3498db;
    margin: 10px 0;
}

.stat-title {
    color: #7f8c8d;
    font-size: 1rem;
}

.status-indicator {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-right: 5px;
}

.status-up {
    background-color: #2ecc71;
}

.status-down {
    background-color: #e74c3c;
}

.nav-tabs {
    display: flex;
    border-bottom: 1px solid #ddd;
    margin-bottom: 20px;
}

.nav-tabs .tab {
    padding: 10px 15px;
    cursor: pointer;
    margin-right: 5px;
    border: 1px solid transparent;
    border-radius: 4px 4px 0 0;
}

.nav-tabs .tab.active {
    background-color: white;
    border: 1px solid #ddd;
    border-bottom-color: white;
    margin-bottom: -1px;
}

.tab-content > div {
    display: none;
}

.tab-content > div.active {
    display: block;
}

@media (max-width: 768px) {
    .dashboard {
        grid-template-columns: 1fr;
    }
    
    table {
        font-size: 0.9rem;
    }
    
    table th, table td {
        padding: 8px 10px;
    }
}
''')

with open('static/script.js', 'w') as f:
    f.write('''
// 页面加载完成后运行
document.addEventListener('DOMContentLoaded', function() {
    // 初始化图表
    initCharts();
    
    // 设置标签页切换
    setupTabs();
    
    // 设置自动刷新
    setInterval(refreshData, 60000); // 每分钟刷新一次
    
    // 初始加载数据
    refreshData();
});

// 设置标签页切换
function setupTabs() {
    const tabs = document.querySelectorAll('.tab');
    const tabContents = document.querySelectorAll('.tab-content > div');
    
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            // 移除所有active类
            tabs.forEach(t => t.classList.remove('active'));
            tabContents.forEach(tc => tc.classList.remove('active'));
            
            // 给当前标签和内容添加active类
            tab.classList.add('active');
            const target = tab.getAttribute('data-target');
            document.getElementById(target).classList.add('active');
            
            // 如果切换到图表标签页，重绘图表
            if (target === 'charts') {
                window.dispatchEvent(new Event('resize'));
            }
        });
    });
}

// 初始化所有图表
function initCharts() {
    // CPU使用率图表
    const cpuCtx = document.getElementById('cpuChart').getContext('2d');
    window.cpuChart = new Chart(cpuCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: '系统CPU使用率(%)',
                data: [],
                borderColor: '#3498db',
                backgroundColor: 'rgba(52, 152, 219, 0.1)',
                borderWidth: 2,
                pointRadius: 0,
                fill: true
            }, {
                label: 'Ollama CPU使用率(%)',
                data: [],
                borderColor: '#e74c3c',
                backgroundColor: 'rgba(231, 76, 60, 0.1)',
                borderWidth: 2,
                pointRadius: 0,
                fill: true
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    ticks: {
                        maxTicksLimit: 10
                    }
                },
                y: {
                    beginAtZero: true,
                    max: 100
                }
            },
            plugins: {
                tooltip: {
                    mode: 'index',
                    intersect: false
                },
                legend: {
                    position: 'top'
                }
            }
        }
    });
    
    // 内存使用率图表
    const memoryCtx = document.getElementById('memoryChart').getContext('2d');
    window.memoryChart = new Chart(memoryCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: '系统内存使用率(%)',
                data: [],
                borderColor: '#2ecc71',
                backgroundColor: 'rgba(46, 204, 113, 0.1)',
                borderWidth: 2,
                pointRadius: 0,
                fill: true
            }, {
                label: 'Ollama内存使用率(%)',
                data: [],
                borderColor: '#9b59b6',
                backgroundColor: 'rgba(155, 89, 182, 0.1)',
                borderWidth: 2,
                pointRadius: 0,
                fill: true
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    ticks: {
                        maxTicksLimit: 10
                    }
                },
                y: {
                    beginAtZero: true,
                    max: 100
                }
            },
            plugins: {
                tooltip: {
                    mode: 'index',
                    intersect: false
                },
                legend: {
                    position: 'top'
                }
            }
        }
    });
    
    // 网络流量图表
    const networkCtx = document.getElementById('networkChart').getContext('2d');
    window.networkChart = new Chart(networkCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: '发送流量(MB)',
                data: [],
                borderColor: '#f39c12',
                backgroundColor: 'rgba(243, 156, 18, 0.1)',
                borderWidth: 2,
                pointRadius: 0,
                fill: true
            }, {
                label: '接收流量(MB)',
                data: [],
                borderColor: '#16a085',
                backgroundColor: 'rgba(22, 160, 133, 0.1)',
                borderWidth: 2,
                pointRadius: 0,
                fill: true
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    ticks: {
                        maxTicksLimit: 10
                    }
                },
                y: {
                    beginAtZero: true
                }
            },
            plugins: {
                tooltip: {
                    mode: 'index',
                    intersect: false
                },
                legend: {
                    position: 'top'
                }
            }
        }
    });
    
    // Token使用图表
    const tokensCtx = document.getElementById('tokensChart').getContext('2d');
    window.tokensChart = new Chart(tokensCtx, {
        type: 'bar',
        data: {
            labels: [],
            datasets: [{
                label: '输入Token',
                data: [],
                backgroundColor: 'rgba(52, 152, 219, 0.7)',
                borderColor: 'rgba(52, 152, 219, 1)',
                borderWidth: 1
            }, {
                label: '输出Token',
                data: [],
                backgroundColor: 'rgba(46, 204, 113, 0.7)',
                borderColor: 'rgba(46, 204, 113, 1)',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    stacked: false
                },
                y: {
                    beginAtZero: true
                }
            },
            plugins: {
                tooltip: {
                    mode: 'index',
                    intersect: false
                },
                legend: {
                    position: 'top'
                }
            }
        }
    });
}

// 刷新所有数据
function refreshData() {
    fetchSystemMetrics();
    fetchRequestStats();
    fetchModelStats();
    fetchIpStats();
    fetchLatestRequests();
    updateServerStatus();
}

// 获取系统指标数据
function fetchSystemMetrics() {
    fetch('/api/metrics/system')
        .then(response => response.json())
        .then(data => {
            updateSystemCharts(data);
            updateSystemStats(data);
        })
        .catch(error => console.error('获取系统指标失败:', error));
}

// 获取请求统计数据
function fetchRequestStats() {
    fetch('/api/stats/requests')
        .then(response => response.json())
        .then(data => {
            document.getElementById('totalRequests').innerText = data.total_requests;
            document.getElementById('avgResponseTime').innerText = data.avg_response_time.toFixed(2) + 's';
            document.getElementById('totalInputTokens').innerText = data.total_input_tokens.toLocaleString();
            document.getElementById('totalOutputTokens').innerText = data.total_output_tokens.toLocaleString();
        })
        .catch(error => console.error('获取请求统计失败:', error));
}

// 获取模型统计数据
function fetchModelStats() {
    fetch('/api/stats/models')
        .then(response => response.json())
        .then(data => {
            const tableBody = document.getElementById('modelStatsBody');
            tableBody.innerHTML = '';
            
            // 更新Token使用图表
            const labels = [];
            const inputTokens = [];
            const outputTokens = [];
            
            data.forEach(model => {
                // 添加表格行
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${model.model_name}</td>
                    <td>${model.request_count}</td>
                    <td>${model.total_input_tokens.toLocaleString()}</td>
                    <td>${model.total_output_tokens.toLocaleString()}</td>
                    <td>${model.avg_response_time.toFixed(2)}s</td>
                `;
                tableBody.appendChild(row);
                
                // 更新图表数据
                labels.push(model.model_name);
                inputTokens.push(model.total_input_tokens);
                outputTokens.push(model.total_output_tokens);
            });
            
            // 更新Token图表
            window.tokensChart.data.labels = labels;
            window.tokensChart.data.datasets[0].data = inputTokens;
            window.tokensChart.data.datasets[1].data = outputTokens;
            window.tokensChart.update();
        })
        .catch(error => console.error('获取模型统计失败:', error));
}

// 获取IP统计数据
function fetchIpStats() {
    fetch('/api/stats/ips')
        .then(response => response.json())
        .then(data => {
            const tableBody = document.getElementById('ipStatsBody');
            tableBody.innerHTML = '';
            
            data.forEach(ip => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${ip.client_ip}</td>
                    <td>${ip.request_count}</td>
                `;
                tableBody.appendChild(row);
            });
        })
        .catch(error => console.error('获取IP统计失败:', error));
}

// 获取最近请求记录
function fetchLatestRequests() {
    fetch('/api/logs/requests')
        .then(response => response.json())
        .then(data => {
            const tableBody = document.getElementById('requestLogsBody');
            tableBody.innerHTML = '';
            
            data.slice(0, 20).forEach(request => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${request.timestamp}</td>
                    <td>${request.client_ip}</td>
                    <td>${request.model_name}</td>
                    <td>${request.input_tokens}</td>
                    <td>${request.output_tokens}</td>
                    <td>${request.response_time.toFixed(2)}s</td>
                    <td>${request.status_code}</td>
                    <td>${request.endpoint}</td>
                `;
                tableBody.appendChild(row);
            });
        })
        .catch(error => console.error('获取请求日志失败:', error));
}

// 更新服务器状态
function updateServerStatus() {
    fetch('/api/status')
        .then(response => response.json())
        .then(data => {
            const statusElement = document.getElementById('serverStatus');
            if (data.server_status) {
                statusElement.innerHTML = '<span class="status-indicator status-up"></span>运行中';
                statusElement.style.color = '#2ecc71';
            } else {
                statusElement.innerHTML = '<span class="status-indicator status-down"></span>已停止';
                statusElement.style.color = '#e74c3c';
            }
        })
        .catch(error => {
            console.error('获取服务器状态失败:', error);
            const statusElement = document.getElementById('serverStatus');
            statusElement.innerHTML = '<span class="status-indicator status-down"></span>连接失败';
            statusElement.style.color = '#e74c3c';
        });
}

// 更新系统图表
function updateSystemCharts(data) {
    // 仅保留最近24小时的数据点（假设每分钟1个数据点，最多1440个点）
    const maxDataPoints = 1440;
    
    // 提取最近的数据点
    const recentData = data.slice(-maxDataPoints);
    
    // 格式化时间标签
    const timeLabels = recentData.map(d => {
        const date = new Date(d.timestamp);
        return date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
    });
    
    // 提取CPU数据
    const cpuData = recentData.map(d => d.cpu_percent);
    const ollamaCpuData = recentData.map(d => d.ollama_cpu_percent);
    
    // 提取内存数据
    const memoryData = recentData.map(d => d.memory_percent);
    const ollamaMemoryData = recentData.map(d => d.ollama_memory_percent);
    
    // 提取网络数据并转换为MB
    const networkSentData = recentData.map(d => d.network_bytes_sent / (1024 * 1024));
    const networkRecvData = recentData.map(d => d.network_bytes_recv / (1024 * 1024));
    
    // 更新CPU图表
    window.cpuChart.data.labels = timeLabels;
    window.cpuChart.data.datasets[0].data = cpuData;
    window.cpuChart.data.datasets[1].data = ollamaCpuData;
    window.cpuChart.update();
    
    // 更新内存图表
    window.memoryChart.data.labels = timeLabels;
    window.memoryChart.data.datasets[0].data = memoryData;
    window.memoryChart.data.datasets[1].data = ollamaMemoryData;
    window.memoryChart.update();
    
    // 更新网络图表
    window.networkChart.data.labels = timeLabels;
    window.networkChart.data.datasets[0].data = networkSentData;
    window.networkChart.data.datasets[1].data = networkRecvData;
    window.networkChart.update();
}

// 更新系统统计信息
function updateSystemStats(data) {
    if (data.length > 0) {
        const latest = data[data.length - 1];
        document.getElementById('cpuUsage').innerText = latest.cpu_percent.toFixed(1) + '%';
        document.getElementById('memoryUsage').innerText = latest.memory_percent.toFixed(1) + '%';
        document.getElementById('diskUsage').innerText = latest.disk_percent.toFixed(1) + '%';
        document.getElementById('ollamaConnections').innerText = latest.ollama_connections;
    }
}
''')

# 模板渲染
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory('static', path)

# 创建模板文件
@app.route('/templates/index.html')
def get_index_template():
    html = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ollama监控系统</title>
    <link rel="stylesheet" href="/static/style.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <header>
        <div class="container">
            <h1>Ollama监控系统</h1>
        </div>
    </header>
    
    <div class="container">
        <div class="dashboard">
            <div class="stat-card">
                <div class="stat-title">服务器状态</div>
                <div id="serverStatus" class="stat-value"><span class="status-indicator"></span>检查中...</div>
            </div>
            <div class="stat-card">
                <div class="stat-title">总请求数</div>
                <div id="totalRequests" class="stat-value">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-title">平均响应时间</div>
                <div id="avgResponseTime" class="stat-value">0s</div>
            </div>
            <div class="stat-card">
                <div class="stat-title">CPU使用率</div>
                <div id="cpuUsage" class="stat-value">0%</div>
            </div>
            <div class="stat-card">
                <div class="stat-title">内存使用率</div>
                <div id="memoryUsage" class="stat-value">0%</div>
            </div>
            <div class="stat-card">
                <div class="stat-title">磁盘使用率</div>
                <div id="diskUsage" class="stat-value">0%</div>
            </div>
            <div class="stat-card">
                <div class="stat-title">Ollama连接数</div>
                <div id="ollamaConnections" class="stat-value">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-title">总输入Token</div>
                <div id="totalInputTokens" class="stat-value">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-title">总输出Token</div>
                <div id="totalOutputTokens" class="stat-value">0</div>
            </div>
        </div>
        
        <div class="nav-tabs">
            <div class="tab active" data-target="charts">图表监控</div>
            <div class="tab" data-target="models">模型统计</div>
            <div class="tab" data-target="clients">客户端统计</div>
            <div class="tab" data-target="requests">请求日志</div>
        </div>
        
        <div class="tab-content">
            <div id="charts" class="active">
                <div class="card">
                    <h2>CPU使用率</h2>
                    <div class="chart-container">
                        <canvas id="cpuChart"></canvas>
                    </div>
                </div>
                
                <div class="card">
                    <h2>内存使用率</h2>
                    <div class="chart-container">
                        <canvas id="memoryChart"></canvas>
                    </div>
                </div>
                
                <div class="card">
                    <h2>网络流量</h2>
                    <div class="chart-container">
                        <canvas id="networkChart"></canvas>
                    </div>
                </div>
                
                <div class="card">
                    <h2>Token使用情况</h2>
                    <div class="chart-container">
                        <canvas id="tokensChart"></canvas>
                    </div>
                </div>
            </div>
            
            <div id="models">
                <div class="card">
                    <h2>模型使用统计</h2>
                    <table>
                        <thead>
                            <tr>
                                <th>模型名称</th>
                                <th>请求次数</th>
                                <th>输入Token</th>
                                <th>输出Token</th>
                                <th>平均响应时间</th>
                            </tr>
                        </thead>
                        <tbody id="modelStatsBody">
                            <tr>
                                <td colspan="5">加载中...</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
            
            <div id="clients">
                <div class="card">
                    <h2>客户端IP统计</h2>
                    <table>
                        <thead>
                            <tr>
                                <th>客户端IP</th>
                                <th>请求次数</th>
                            </tr>
                        </thead>
                        <tbody id="ipStatsBody">
                            <tr>
                                <td colspan="2">加载中...</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
            
            <div id="requests">
                <div class="card">
                    <h2>最近请求日志</h2>
                    <table>
                        <thead>
                            <tr>
                                <th>时间</th>
                                <th>客户端IP</th>
                                <th>模型</th>
                                <th>输入Token</th>
                                <th>输出Token</th>
                                <th>响应时间</th>
                                <th>状态码</th>
                                <th>接口</th>
                            </tr>
                        </thead>
                        <tbody id="requestLogsBody">
                            <tr>
                                <td colspan="8">加载中...</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    
    <script src="/static/script.js"></script>
</body>
</html>
    '''
    with open('templates/index.html', 'w') as f:
        f.write(html)
    return html

# 确保模板文件夹存在
if not os.path.exists('templates'):
    os.makedirs('templates')
    get_index_template()

# API路由
@app.route('/api/status')
def api_status():
    monitor = app.config['MONITOR']
    return jsonify({
        "server_status": monitor.get_server_status(),
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/metrics/system')
def api_system_metrics():
    db = OllamaMetricsDB()
    hours = request.args.get('hours', 24, type=int)
    metrics = db.get_recent_system_metrics(hours)
    return jsonify(metrics)

@app.route('/api/logs/requests')
def api_request_logs():
    db = OllamaMetricsDB()
    hours = request.args.get('hours', 24, type=int)
    logs = db.get_recent_requests(hours)
    return jsonify(logs)

@app.route('/api/stats/models')
def api_model_stats():
    db = OllamaMetricsDB()
    hours = request.args.get('hours', 24, type=int)
    stats = db.get_model_usage_stats(hours)
    result = []
    for row in stats:
        result.append({
            "model_name": row[0],
            "request_count": row[1],
            "total_input_tokens": row[2] or 0,
            "total_output_tokens": row[3] or 0,
            "avg_response_time": row[4] or 0
        })
    return jsonify(result)

@app.route('/api/stats/ips')
def api_ip_stats():
    db = OllamaMetricsDB()
    hours = request.args.get('hours', 24, type=int)
    stats = db.get_client_ip_stats(hours)
    result = []
    for row in stats:
        result.append({
            "client_ip": row[0],
            "request_count": row[1]
        })
    return jsonify(result)

@app.route('/api/stats/requests')
def api_request_stats():
    db = OllamaMetricsDB()
    hours = request.args.get('hours', 24, type=int)
    logs = db.get_recent_requests(hours)
    
    total_requests = len(logs)
    total_input_tokens = sum(log['input_tokens'] for log in logs)
    total_output_tokens = sum(log['output_tokens'] for log in logs)
    
    # 计算平均响应时间
    response_times = [log['response_time'] for log in logs if log['response_time'] is not None]
    avg_response_time = sum(response_times) / len(response_times) if response_times else 0
    
    return jsonify({
        "total_requests": total_requests,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "avg_response_time": avg_response_time
    })

# Ollama API代理
@app.route('/ollama/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def proxy_ollama(path):
    db = OllamaMetricsDB()
    start_time = time.time()
    client_ip = request.remote_addr
    
    url = f"{OLLAMA_HOST}/{path}"
    headers = {key: value for (key, value) in request.headers if key != 'Host'}
    
    try:
        if request.method == 'GET':
            resp = requests.get(url, headers=headers, params=request.args)
        elif request.method == 'POST':
            json_data = request.get_json(silent=True)
            if json_data:
                # 对于API请求，记录输入输出token
                if path == 'api/generate' or path == 'api/chat':
                    model_name = json_data.get('model', '')
                    stream = json_data.get('stream', False)
                    
                    resp = requests.post(url, headers=headers, json=json_data)
                    response_time = time.time() - start_time
                    
                    # 提取token信息
                    if resp.status_code == 200 and not stream:
                        result = resp.json()
                        input_tokens = result.get('prompt_eval_count', 0)
                        output_tokens = result.get('eval_count', 0)
                        
                        # 保存请求日志
                        log_data = {
                            "timestamp": datetime.now().isoformat(),
                            "client_ip": client_ip,
                            "model_name": model_name,
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "response_time": response_time,
                            "status_code": resp.status_code,
                            "endpoint": f"/{path}"
                        }
                        db.save_request_log(log_data)
                else:
                    resp = requests.post(url, headers=headers, json=json_data)
            else:
                resp = requests.post(url, headers=headers, data=request.get_data())
        elif request.method == 'PUT':
            resp = requests.put(url, headers=headers, data=request.get_data())
        elif request.method == 'DELETE':
            resp = requests.delete(url, headers=headers)
        else:
            return jsonify({"error": "Method not allowed"}), 405
        
        response_headers = [(name, value) for (name, value) in resp.raw.headers.items()]
        return resp.content, resp.status_code, response_headers
    except Exception as e:
        logger.error(f"代理请求异常: {str(e)}")
        return jsonify({"error": str(e)}), 500

def run_monitor():
    """运行监控线程"""
    monitor = OllamaMonitor()
    threading.Thread(target=monitor.run, daemon=True).start()
    return monitor

def run_web_server(monitor):
    """运行Web服务器"""
    app.config['MONITOR'] = monitor
    logger.info(f"Web服务器正在启动，地址为 http://{WEB_HOST}:{WEB_PORT}")
    serve(app, host=WEB_HOST, port=WEB_PORT, threads=10)

# 增加系统监控守护进程功能
def write_systemd_service():
    """创建系统服务文件"""
    service_content = f'''[Unit]
Description=Ollama Monitor
After=network.target

[Service]
User={os.getlogin()}
WorkingDirectory={os.getcwd()}
ExecStart=/usr/bin/python3 {os.path.abspath(__file__)}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
'''
    
    service_path = '/tmp/ollama-monitor.service'
    with open(service_path, 'w') as f:
        f.write(service_content)
    
    print(f"系统服务文件已生成: {service_path}")
    print("要安装此服务，请以root运行:")
    print(f"sudo cp {service_path} /etc/systemd/system/")
    print("sudo systemctl daemon-reload")
    print("sudo systemctl enable ollama-monitor")
    print("sudo systemctl start ollama-monitor")

if __name__ == "__main__":
    # 确保必要的目录存在
    if not os.path.exists('templates'):
        os.makedirs('templates')
    if not os.path.exists('static'):
        os.makedirs('static')
    
    # 生成系统服务文件
    # if '--install' in sys.argv:
    #     write_systemd_service()
    #     sys.exit(0)
    
    # 启动监控
    monitor = run_monitor()
    
    try:
        # 启动Web服务器
        run_web_server(monitor)
    except KeyboardInterrupt:
        logger.info("接收到中断信号，正在关闭...")
        monitor.stop()
    except Exception as e:
        logger.error(f"程序异常: {str(e)}")
        monitor.stop()