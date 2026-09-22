# MindLoop Backend

MindLoop（启念）MVP 后端：把用户意图转成一个可立即执行的下一步，并支持 Todo/Reminder、专注会话、穿戴端事件与闭环指标。

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload
```

打开 `http://127.0.0.1:8000/docs` 查看交互式 API。默认使用 SQLite，不需要外部服务或密钥。

## 核心流程

- `POST /v1/tasks`：创建并拆解任务，只返回一个突出显示的当前步骤。
- `POST /v1/tasks/{id}/actions`：完成、跳过、编辑或把当前步骤缩得更小。
- `POST /v1/captures`：将一句文本识别为 Todo、Reminder 或任务启动意图；时间模糊时返回一次澄清问题。
- `POST /v1/focus/sessions`：显式开启轻度/深度专注模式。
- `POST /v1/focus/sessions/{id}/signals`：接收抽象 IMU/摄像头弱信号；达到阈值且不在冷却期时创建一次轻震指令。
- `POST /v1/focus/sessions/{id}/respond`：忽略、需要帮助、已回来或重置两分钟。
- `GET /v1/devices/{id}/commands`：穿戴端轮询待执行命令。
- `GET /v1/metrics/summary`：查看 Hackathon 闭环指标。

## 隐私边界

服务只接收结构化语义和抽象行为事件，不接收或保存原始音视频。深度模式必须在创建会话时显式传入摄像头授权。所有判断使用“可能偏离”，不进行疾病、情绪或注意力诊断。
