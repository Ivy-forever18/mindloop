# MindLoop（启念）

MindLoop 是一个面向高认知负荷场景的 AI 吊坠 MVP：用户说出难以开始的任务，AI 把它转成一个短小、明确、可观察的动作；用户可以反馈“完成”或“太难了”，设备据此继续记录效果或进一步缩小动作。

## 当前已经实现

- EvoMap OAuth、Recipe、Gene 与复用关系 API 接入
- 通过 EvoMap OpenAI-compatible 模型网关调用 `evomap-deepseek-v4-flash`
- AI 生成 1–2 分钟内可完成的原子动作
- 用户反馈 `stuck` 后，由 AI 生成更小的动作
- 模型超时、返回异常或网络失败时自动切换到规则兜底
- SQLite 匿名行为记忆：Done/Stuck、响应时间、缩小次数和有效动作
- Apple 风格吊坠网页模拟器，支持完成、太难了和模拟走神震动
- API 文档、健康检查、匿名指标与事件查询
- 旧版任务、提醒、专注检测与穿戴端命令原型保留在 `backend/app/`

## 当前产品边界

目前 AI 使用的是“单步生成”模式：创建任务时生成一个动作，`stuck` 时缩小动作，`done` 时结束当前会话。

下一阶段将升级为“预先规划完整 Steps”：AI 在任务开始时生成步骤列表，用户正常完成时直接进入下一步；只有卡住或目标变化时，AI 才调整当前及后续步骤。语音识别、VAD、实体按键、BLE 和真实震动马达尚未接入。

## 项目结构

所有实现集中在 [`backend/`](backend/)：

```text
backend/
├── main.py                    # 当前 FastAPI 入口
├── atomic_step_agent.py       # AI 原子步骤 Agent 与 Prompt
├── llm_client.py              # OpenAI-compatible 模型客户端
├── evomap_client.py           # EvoMap OAuth / Recipe API 客户端
├── mindloop.py                # 会话、规则兜底、指标与匿名 Memory
├── static/                    # 吊坠网页模拟器
├── test_*.py                  # 当前 AI/EvoMap/MindLoop 测试
├── app/                       # 早期模块化产品原型（保留）
├── tests/                     # 早期原型测试
├── .env.example               # 环境变量模板，不包含真实密钥
├── requirements.txt           # 当前 Demo 依赖
└── README.md                  # 后端与接口详细说明
```

## 本地启动

需要 Python 3.11 或更高版本。

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

在 `.env` 中填写自己的 EvoMap 与模型网关凭据：

```dotenv
AI_BASE_URL=https://api.evomap.ai/v1
AI_API_KEY=sk-evomap-your-key
AI_MODEL=evomap-deepseek-v4-flash
```

不要提交真实 `.env`。然后启动：

```bash
uvicorn main:app --reload --port 8000
```

访问：

- 吊坠模拟器：<http://127.0.0.1:8000/>
- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>
- 匿名 Memory：<http://127.0.0.1:8000/api/mindloop/memory?task_type=writing>

最后一个地址是后端 JSON 接口，不是产品页面。

## 测试

```bash
cd backend
python -m unittest test_mindloop.py test_atomic_step_agent.py
python -m pytest test_client.py -q
```

测试不需要真实 API Key。真实模型连通性可在启动后通过 `/health` 和吊坠模拟器验证。

## 隐私与安全

- `.env`、SQLite 数据库、虚拟环境和缓存均被 Git 忽略。
- 原始任务文本只为当前会话临时保存在进程内存，不写入 SQLite。
- Memory 只保存匿名行为结果，不保存原始语音、诊断、位置或生理数据。
- EvoMap 测试发布默认关闭，只有显式设置 `EVOMAP_ALLOW_TEST_PUBLISH=true` 才会启用。
