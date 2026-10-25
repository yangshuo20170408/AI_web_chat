# 本地 AI 聊天

一个 **ChatGPT 风格**的本地聊天应用。零第三方依赖，只用 Python 标准库 + 原生前端，下载即用。

![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB) ![deps](https://img.shields.io/badge/dependencies-0-success)

## 功能

- 🌊 **流式输出**：逐字显示，可随时停止
- 💬 **多会话管理**：自动命名、按时间分组、本地持久化
- 🧠 **Codex 风格推理框**：实时展开思考过程、显示耗时，正文开始后自动收起，可随时展开
- 🔀 **快捷切换模型**：点右上角模型名即可切换，每条回复标注所用模型
- 🎚️ **推理强度**：自动 / 低 / 中 / 高，按需透传 `reasoning_effort`
- 📝 **Markdown 渲染**：标题、列表、表格、引用、代码块（一键复制）
- 📎 **添加文件**：文本/代码文件与图片，支持点击选择、拖拽、粘贴
- 🔌 **任意 OpenAI 兼容接口**：DeepSeek / OpenAI / 通义 / Moonshot / Ollama / OneAPI…
- 🎛️ **参数可调**：模型、温度、系统提示词，支持一键拉取模型列表
- 🌗 **深色 / 浅色主题**，移动端自适应
- 🔒 **密钥不出本机**：保存在 `config.json`，浏览器只拿到掩码

## 快速开始

1. 确认已安装 Python 3.9+（命令行执行 `python --version`）
2. 双击 **`start.bat`**（或命令行 `python server.py`）
3. 浏览器自动打开 http://127.0.0.1:8000
4. 点左下角 **设置**，填入 API Key，保存

首次没有 Key 时是**演示模式**，界面可以正常体验：AI 会返回配置说明，并顺带演示推理框和流式输出的效果。

### 常用命令

```bash
python server.py                # 默认 8000 端口，自动开浏览器
python server.py --port 8080    # 指定端口
python server.py --no-open      # 不自动打开浏览器
```

## 配置

设置面板里的内容会写入项目目录的 `config.json`：

```json
{
  "base_url": "https://api.deepseek.com/v1",
  "api_key": "sk-xxxxxxxx",
  "model": "deepseek-chat",
  "models": ["deepseek-chat", "deepseek-reasoner"],
  "temperature": 0.7,
  "system_prompt": "你是一个乐于助人的 AI 助手……"
}
```

也可以直接用环境变量覆盖（无需改文件）：

| 环境变量 | 说明 |
| --- | --- |
| `OPENAI_API_KEY` | API Key（也支持 `DEEPSEEK_API_KEY`） |
| `OPENAI_BASE_URL` | 接口地址，例如 `https://api.openai.com/v1` |
| `OPENAI_MODEL` | 模型名 |

### 常见服务商地址

| 服务商 | base_url | 模型示例 |
| --- | --- | --- |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` / `deepseek-reasoner` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Moonshot | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| 阿里百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| Ollama（本地） | `http://127.0.0.1:11434/v1` | `qwen2.5:7b` |

> Ollama 的 Key 随便填一个非空值即可，例如 `ollama`。

## 添加文件

输入框左侧的 **回形针按钮** 可以选文件，也可以把文件直接拖进窗口，或粘贴剪贴板里的图片（例如截图）。

| 类型 | 支持格式 | 限制 |
| --- | --- | --- |
| 文本 / 代码 | `.txt` `.md` `.json` `.csv` `.py` `.js` `.ts` `.html` `.css` `.java` `.go` `.rs` `.sql` `.yaml` `.sh` `.bat` 等 | 单文件 ≤ 200 KB，单条消息 ≤ 6 个 |
| 图片 | PNG / JPEG / WebP / GIF 等常见格式 | 原图 ≤ 10 MB，自动压缩到最长边 1280 px |

- 文本文件会以 `<file name="...">` 块拼进消息内容，模型可以直接阅读；
- 图片以 OpenAI 多模态格式（`image_url`）发送，**需要模型支持视觉输入**，例如 `gpt-4o`、`qwen-vl-plus`、`glm-4v` 等。`deepseek-chat` 目前不支持看图，图片会被上游拒绝或忽略；
- 图片会以 base64 存在浏览器 `localStorage`，附件较多时注意存储空间（存满会提示）。

## 模型与推理强度

点右上角的 **模型名称** 打开菜单：

- **模型**：列出 `config.json` 里的 `models`，点击立即切换（写入服务端配置，下一条消息生效）。鼠标移到回复上，可在操作栏看到本条实际使用的模型。
- **推理强度**：`自动` / `低` / `中` / `高`。选「自动」不发送该参数；其余会作为 `reasoning_effort` 透传给上游接口。仅部分模型支持（如 OpenAI o 系列、GPT-5 等）；如果上游报参数不支持，改回「自动」即可。DeepSeek 的 `deepseek-reasoner` 选「自动」即可。
- 要增删模型列表：点菜单里的「管理模型」，在设置面板中修改并保存。

### 推理框

支持流式返回 `reasoning_content` 或 `reasoning` 字段的模型（如 `deepseek-reasoner`）：

- 思考时推理框自动展开，标题带流光动画和实时计时；
- 正文开始输出后自动收起，显示「已思考 N 秒」；
- 点击标题随时展开 / 收起，展开状态会随对话一起保存在本地。

## 项目结构

```
默认项目/
├── server.py          # 后端：静态服务 + /api/chat 流式代理 + 配置
├── start.bat          # Windows 一键启动
├── config.json        # 运行时生成，保存 Key（不要提交到 Git）
└── web/
    ├── index.html     # 页面结构
    ├── styles.css     # 主题与布局
    └── app.js         # 会话、流式解析、附件、推理框、Markdown 渲染
```

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/config` | 读取配置（Key 已脱敏） |
| POST | `/api/config` | 保存配置 |
| POST | `/api/models` | 代理上游 `GET /models` |
| POST | `/api/chat` | SSE 流式对话（可选 `reasoning_effort`） |

## 说明

- 服务默认只监听 `127.0.0.1`，仅本机可访问。要局域网共享可加 `--host 0.0.0.0`，但**请自行加认证**，否则同网段任何人都能用你的 Key。
- 对话记录保存在浏览器 `localStorage`，换浏览器/清缓存会丢失；API Key 保存在服务端 `config.json`。
- 本项目是「客户端 + 代理」，模型能力由你接入的 API 决定，本身不训练模型。
