# MindLoop（启念）

面向高认知负荷用户的 AI 认知陪伴设备 MVP。后端围绕三个核心闭环设计：帮助用户开始任务、记住临时事项，并在专注状态可能偏离时温和拉回。

## 已实现能力

- 将大型任务拆解为 3–5 个可执行步骤，并始终只突出当前下一步
- 完成、跳过、编辑步骤，以及“仍然卡住”后的进一步原子化
- 从自然语言创建 Todo 和 Reminder，并对模糊时间进行一次澄清
- 轻度与深度专注模式、IMU 弱信号、温和提醒和冷却机制
- 穿戴端命令队列：轻震、显示下一步、两分钟重置及 ACK
- 策略反馈、任务启动率、回归任务率和误提醒率等闭环指标
- 深度模式显式摄像头授权，不保存原始音视频，不进行医学诊断

## 项目结构

所有后端实现统一放在 [`backend/`](backend/)：

```text
backend/
├── app/                 # FastAPI 应用、数据模型和业务逻辑
├── tests/               # 核心闭环自动化测试
├── .env.example         # 环境变量示例
├── pyproject.toml       # Python 依赖与测试配置
└── README.md            # 后端接口详细说明
```

## 快速开始

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload
```

启动后访问：

- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>

## 测试

```bash
cd backend
pytest -q
```

当前 Agent 使用本地规则实现，不依赖外部 API Key，适合直接演示。后续可以将任务拆解、ASR 和意图识别替换为实际模型服务。
