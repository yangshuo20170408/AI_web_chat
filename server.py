#!/usr/bin/env python3
"""本地 ChatGPT 风格聊天应用 —— 零第三方依赖，仅用 Python 标准库。

用法:
    python server.py            # 启动并自动打开浏览器
    python server.py --port 8080
    python server.py --no-open
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"
CONFIG_PATH = APP_DIR / "config.json"

DEFAULT_CONFIG = {
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "",
    "model": "deepseek-chat",
    "models": ["deepseek-chat", "deepseek-reasoner"],
    "temperature": 0.7,
    "system_prompt": "你是一个乐于助人的 AI 助手，回答准确、简洁，必要时给出可执行的步骤。",
}

_config_lock = threading.Lock()

MOCK_TEXT = """你好！👋 应用已经成功跑起来了，但还没有配置 API Key，所以我现在只能做演示回复。

**三步开始对话：**

1. 点左下角 **设置**
2. 填入你的 API Key（支持 DeepSeek、OpenAI 以及任何 OpenAI 兼容接口）
3. 保存后回到这里重新发送消息

配置会保存在项目目录的 `config.json` 里，不会上传到任何地方。

> 提示：DeepSeek 开放平台的 Key 以 `sk-` 开头，默认地址 `https://api.deepseek.com/v1` 已经帮你填好了。
"""

MOCK_REASONING = """当前还没有配置 API Key，所以这是一次演示回复。
我先用这段文字模拟推理模型的思考过程：
- 思考时推理框自动展开，并显示实时计时
- 正文开始输出后自动收起为「已思考 N 秒」
- 点击标题可以随时重新展开
配置好支持推理的模型（例如 deepseek-reasoner）后，这里会显示真实的思考内容。"""


# --------------------------------------------------------------------------
# 配置读写
# --------------------------------------------------------------------------
def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
        except (OSError, ValueError) as exc:
            print(f"[警告] 无法读取 config.json：{exc}")

    # 环境变量优先，方便临时覆盖
    env_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if env_key:
        cfg["api_key"] = env_key
    if os.environ.get("OPENAI_BASE_URL"):
        cfg["base_url"] = os.environ["OPENAI_BASE_URL"]
    if os.environ.get("OPENAI_MODEL"):
        cfg["model"] = os.environ["OPENAI_MODEL"]
    return cfg


def save_config(cfg: dict) -> None:
    data = {key: cfg.get(key, DEFAULT_CONFIG[key]) for key in DEFAULT_CONFIG}
    with _config_lock:
        CONFIG_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def public_config(cfg: dict) -> dict:
    key = str(cfg.get("api_key") or "")
    if len(key) > 12:
        hint = f"{key[:5]}…{key[-4:]}"
    elif key:
        hint = "已设置"
    else:
        hint = ""
    return {
        "base_url": cfg["base_url"],
        "model": cfg["model"],
        "models": cfg.get("models") or [],
        "temperature": cfg["temperature"],
        "system_prompt": cfg["system_prompt"],
        "has_key": bool(key),
        "key_hint": hint,
    }


def sse_bytes(obj) -> bytes:
    return b"data: " + json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n\n"


# --------------------------------------------------------------------------
# HTTP 处理器
# --------------------------------------------------------------------------
class AppHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "LocalChat/1.0"

    # ---------------------------- 基础工具 ----------------------------
    def log_message(self, fmt: str, *args) -> None:
        if self.path.startswith("/api/"):
            if args and str(args[1]) not in ("200", "204"):
                sys.stderr.write(f"[{self.log_date_time_string()}] {fmt % args}\n")
        # 静态资源不刷屏

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length <= 0 or length > 8 * 1024 * 1024:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _start_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    # ------------------------------ 路由 ------------------------------
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            self._send_json({"ok": True})
        elif path == "/api/config":
            self._send_json(public_config(load_config()))
        elif path.startswith("/api/"):
            self._send_json({"error": "接口不存在"}, 404)
        else:
            self._serve_static(path)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/api/chat":
            self._handle_chat(self._read_json())
        elif path == "/api/config":
            self._handle_save_config(self._read_json())
        elif path == "/api/models":
            self._handle_models(self._read_json())
        else:
            self._send_json({"error": "接口不存在"}, 404)

    # ---------------------------- 静态文件 ----------------------------
    def _serve_static(self, path: str) -> None:
        rel = path.lstrip("/") or "index.html"
        if rel.endswith("/"):
            rel += "index.html"
        try:
            target = (WEB_DIR / rel).resolve()
            target.relative_to(WEB_DIR.resolve())
        except (ValueError, OSError):
            self._send_json({"error": "非法路径"}, 403)
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            self._send_json({"error": "文件不存在"}, 404)
            return

        content_type, _ = mimetypes.guess_type(str(target))
        if content_type is None:
            content_type = "application/octet-stream"
        if content_type.startswith("text/") or content_type in (
            "application/javascript",
            "application/json",
            "image/svg+xml",
        ):
            content_type += "; charset=utf-8"

        try:
            data = target.read_bytes()
        except OSError:
            self._send_json({"error": "读取文件失败"}, 500)
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    # ------------------------------ 配置 ------------------------------
    def _handle_save_config(self, body: dict) -> None:
        cfg = load_config()
        if isinstance(body.get("base_url"), str):
            cfg["base_url"] = body["base_url"].strip() or DEFAULT_CONFIG["base_url"]
        if isinstance(body.get("model"), str) and body["model"].strip():
            cfg["model"] = body["model"].strip()
        if isinstance(body.get("system_prompt"), str):
            cfg["system_prompt"] = body["system_prompt"].strip()
        if isinstance(body.get("models"), list):
            cfg["models"] = [str(m) for m in body["models"] if str(m).strip()][:200]
        if "temperature" in body:
            try:
                cfg["temperature"] = max(0.0, min(2.0, float(body["temperature"])))
            except (TypeError, ValueError):
                pass
        if body.get("clear_key"):
            cfg["api_key"] = ""
        elif isinstance(body.get("api_key"), str) and body["api_key"].strip():
            cfg["api_key"] = body["api_key"].strip()

        save_config(cfg)
        self._send_json(public_config(cfg))

    # ---------------------------- 模型列表 ----------------------------
    def _handle_models(self, body: dict) -> None:
        cfg = load_config()
        key = (body.get("api_key") or "").strip() or str(cfg["api_key"] or "")
        base = (body.get("base_url") or cfg["base_url"]).strip().rstrip("/")
        if not key:
            self._send_json({"error": "请先填写 API Key"}, 400)
            return

        req = urllib.request.Request(
            base + "/models",
            headers={
                "Authorization": f"Bearer {key}",
                "Accept": "application/json",
                "User-Agent": "LocalChat/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            self._send_json({"error": f"上游返回 {exc.code}", "detail": detail}, 502)
            return
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": f"请求失败：{exc}"}, 502)
            return

        items = payload.get("data") if isinstance(payload, dict) else None
        models = []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    models.append(item["id"])
        self._send_json({"models": sorted(set(models))})

    # ------------------------------ 对话 ------------------------------
    def _handle_chat(self, body: dict) -> None:
        cfg = load_config()
        raw_messages = body.get("messages")
        if not isinstance(raw_messages, list) or not raw_messages:
            self._send_json({"error": "messages 不能为空"}, 400)
            return

        messages = []
        for item in raw_messages[-100:]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            if role not in ("system", "user", "assistant"):
                continue
            content = item.get("content")

            if isinstance(content, list):
                # 多模态：text + image_url
                parts = []
                for part in content[:20]:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "text" and isinstance(part.get("text"), str):
                        parts.append({"type": "text", "text": part["text"][:400000]})
                    elif part.get("type") == "image_url":
                        image_url = part.get("image_url")
                        if isinstance(image_url, dict):
                            url = image_url.get("url")
                            if isinstance(url, str) and url.startswith(
                                ("data:image/", "http://", "https://")
                            ):
                                parts.append({"type": "image_url", "image_url": {"url": url}})
                if not parts:
                    continue
                content = parts
            elif isinstance(content, str):
                if role != "assistant" and not content.strip():
                    continue
            else:
                continue

            messages.append({"role": role, "content": content})

        if not any(m["role"] == "user" for m in messages):
            self._send_json({"error": "缺少用户消息"}, 400)
            return

        system_prompt = str(body.get("system_prompt") or cfg.get("system_prompt") or "").strip()
        if system_prompt and not any(m["role"] == "system" for m in messages):
            messages.insert(0, {"role": "system", "content": system_prompt})

        api_key = str(cfg.get("api_key") or "").strip()
        if not api_key:
            self._stream_mock()
            return

        try:
            temperature = float(body.get("temperature", cfg.get("temperature", 0.7)))
        except (TypeError, ValueError):
            temperature = float(cfg.get("temperature", 0.7))

        payload = {
            "model": body.get("model") or cfg["model"],
            "messages": messages,
            "temperature": max(0.0, min(2.0, temperature)),
            "stream": True,
        }

        # 推理强度：仅透传明确取值，默认不发送该字段
        effort = body.get("reasoning_effort")
        if isinstance(effort, str) and effort.strip().lower() in ("low", "medium", "high"):
            payload["reasoning_effort"] = effort.strip().lower()

        url = str(cfg["base_url"]).rstrip("/") + "/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "Accept": "text/event-stream",
                "User-Agent": "LocalChat/1.0",
            },
        )

        try:
            upstream = urllib.request.urlopen(req, timeout=300)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:2000]
            self._send_json({"error": f"上游返回 HTTP {exc.code}", "detail": detail}, 502)
            return
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": f"无法连接上游 API：{exc}"}, 502)
            return

        self._start_sse()
        try:
            while True:
                line = upstream.readline()
                if not line:
                    break
                self.wfile.write(line)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OSError:
            pass
        finally:
            try:
                upstream.close()
            except OSError:
                pass

    def _stream_mock(self) -> None:
        self._start_sse()
        try:
            # 演示推理框：先流式返回 reasoning_content，再返回正文
            for start in range(0, len(MOCK_REASONING), 5):
                piece = MOCK_REASONING[start:start + 5]
                self.wfile.write(
                    sse_bytes({"choices": [{"delta": {"reasoning_content": piece}}]})
                )
                self.wfile.flush()
                time.sleep(0.018)
            time.sleep(0.15)

            # 按字符切块（不能用 . 正则，否则换行符会被丢掉）
            for start in range(0, len(MOCK_TEXT), 4):
                piece = MOCK_TEXT[start:start + 4]
                self.wfile.write(sse_bytes({"choices": [{"delta": {"content": piece}}]}))
                self.wfile.flush()
                time.sleep(0.012)
            self.wfile.write(b"data: [DONE]\n\n")
        except (BrokenPipeError, ConnectionResetError):
            pass


# --------------------------------------------------------------------------
# 启动
# --------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="本地 ChatGPT 风格聊天应用")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认仅本机）")
    parser.add_argument("--port", type=int, default=8000, help="端口，默认 8000")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    if not (WEB_DIR / "index.html").exists():
        sys.exit(f"找不到前端文件：{WEB_DIR / 'index.html'}")

    httpd = None
    port = args.port
    for _ in range(30):
        try:
            httpd = ThreadingHTTPServer((args.host, port), AppHandler)
            break
        except OSError:
            port += 1
    if httpd is None:
        sys.exit("端口都被占用了，请用 --port 指定一个空闲端口。")

    cfg = load_config()
    url = f"http://{args.host}:{port}/"
    print("=" * 56)
    print("  本地 AI 聊天")
    print(f"  地址   : {url}")
    print(f"  模型   : {cfg['model']}")
    print(f"  API Key: {'已配置' if cfg.get('api_key') else '未配置（演示模式）'}")
    print("  退出   : Ctrl + C")
    print("=" * 56)

    if not args.no_open:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
