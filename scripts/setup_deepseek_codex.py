#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AUTO DeepSeek_Codex -- 把 Codex 切到 DeepSeek API，并跳过 ChatGPT 登录。

职责（一次性完成，幂等）：
  1. 从系统剪切板读取用户已复制的 DeepSeek API Key（也可以走环境变量或显式参数）
  2. 校验 Key 形态，拒绝明显不是 Key 的内容
  3. 备份现有 ~/.codex/config.toml 与 auth.json
  4. 写入 models.json（取自 assets/models.json，官方原始内容）
  5. 合并 config.toml（只改必要字段，保留用户原有的 MCP / 插件 / desktop 配置）
  6. 写入 auth.json（这是"跳过登录"的真正开关）
  7. 调用 DeepSeek 真实接口做连通性验证

只依赖 Python 3 标准库，无第三方依赖。

用法：
  python setup_deepseek_codex.py                     # 从剪切板取 Key，默认模型 deepseek-flash
  python setup_deepseek_codex.py --model deepseek-v4-pro
  python setup_deepseek_codex.py --from-env DEEPSEEK_API_KEY
  python setup_deepseek_codex.py --no-probe          # 跳过消耗 token 的 /responses 探测
  python setup_deepseek_codex.py --restore --yes     # 还原到安装前的配置

安全：本脚本不做任何网络上报，只与 https://api.deepseek.com 通信（校验 Key 用）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

BASE_URL = "https://api.deepseek.com/"
PROVIDER_ID = "deepseek"
BACKUP_DIRNAME = "backup-deepseek"
DEFAULT_MODEL = "deepseek-flash"

# 顶层需要被本技能接管的键
TARGET_KEYS = [
    "model",
    "model_provider",
    "preferred_auth_method",
    "forced_login_method",
    "model_reasoning_effort",
    "web_search",
    "model_catalog_json",
]
# 会劫持请求或遮蔽上面这些键的顶层键，必须清掉
CONFLICT_KEYS = ["profile", "oss_provider", "openai_base_url"]

KEY_RE = re.compile(r"^sk-[A-Za-z0-9_\-]{16,200}$")
KEYLINE_RE = re.compile(r"^\s*([A-Za-z0-9_\-]+)\s*=")

OK, WARN, ERR = "[OK]", "[!] ", "[X] "


def out(prefix: str, msg: str) -> None:
    print(f"{prefix} {msg}")


def die(msg: str, code: int = 1) -> "NoReturn":  # type: ignore[name-defined]
    out(ERR, msg)
    sys.exit(code)


# --------------------------------------------------------------------------
# 剪切板
# --------------------------------------------------------------------------

def _run(cmd: list[str]) -> str | None:
    try:
        p = subprocess.run(
            cmd, capture_output=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    for enc in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
        try:
            return p.stdout.decode(enc)
        except UnicodeDecodeError:
            continue
    return p.stdout.decode("utf-8", "replace")


def read_clipboard() -> tuple[str | None, str]:
    """返回 (文本, 来源描述)。拿不到时文本为 None。"""
    if sys.platform.startswith("win"):
        txt = _run([
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw",
        ])
        return txt, "Windows 剪切板"
    if sys.platform == "darwin":
        return _run(["pbpaste"]), "macOS 剪切板 (pbpaste)"
    for cmd, label in (
        (["wl-paste", "--no-newline"], "Wayland 剪切板 (wl-paste)"),
        (["xclip", "-selection", "clipboard", "-o"], "X11 剪切板 (xclip)"),
        (["xsel", "--clipboard", "--output"], "X11 剪切板 (xsel)"),
    ):
        txt = _run(cmd)
        if txt:
            return txt, label
    return None, "当前系统没有可用的剪切板读取工具"


# --------------------------------------------------------------------------
# 取 Key
# --------------------------------------------------------------------------

def acquire_key(args: argparse.Namespace) -> str:
    raw: str | None = None
    source = ""

    if args.key:
        raw, source = args.key, "--key 参数"
    elif args.from_env:
        raw, source = os.environ.get(args.from_env), f"环境变量 {args.from_env}"
        if raw is None:
            die(f"环境变量 {args.from_env} 未设置或为空。")
    else:
        raw, source = read_clipboard()

    if raw is None:
        die(f"无法读取剪切板（{source}）。请让用户重新复制 API Key 后再试，"
            f"或改用 --from-env <环境变量名>。")

    if not raw.strip():
        die("剪切板是空的。请让用户把 DeepSeek API Key 复制到剪切板后再运行。")

    lines = [ln.strip() for ln in raw.replace("\r", "").split("\n") if ln.strip()]
    if len(lines) > 1:
        die(f"剪切板里有多行内容（{len(lines)} 行），无法确定哪一行是 API Key。"
            f"请让用户只复制 Key 本身。第一行预览：{lines[0][:12]}...")

    key = lines[0].strip().strip('"').strip("'").strip()
    out(OK, f"已从{source}读取到凭据（{len(key)} 字符，前缀 {key[:7]}...）")

    if key.lower().startswith(("http://", "https://")):
        die("剪切板里是一个网址，不是 API Key。请让用户复制 Key 本身（以 sk- 开头）。")
    if not key.startswith("sk-"):
        die(f"内容不以 'sk-' 开头（实际开头：{key[:6]}...），不是 DeepSeek API Key。"
            f"请让用户重新复制。")
    if not KEY_RE.match(key):
        die("内容形态不像 DeepSeek API Key（含空格、换行或非法字符）。请让用户重新复制。")
    return key


# --------------------------------------------------------------------------
# 路径
# --------------------------------------------------------------------------

def resolve_codex_home() -> Path:
    env = os.environ.get("CODEX_HOME", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".codex").resolve()


def catalog_value(models_path: Path) -> str:
    """TOML 里必须用绝对路径 + 正斜杠：Windows 不保证展开 ~，反斜杠又是 TOML 转义符。"""
    return str(models_path.resolve()).replace("\\", "/")


# --------------------------------------------------------------------------
# 备份 / 还原
# --------------------------------------------------------------------------

def backup(codex_home: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = codex_home / BACKUP_DIRNAME / stamp
    dest.mkdir(parents=True, exist_ok=True)
    saved = []
    for name in ("config.toml", "auth.json", "models.json"):
        src = codex_home / name
        if src.exists():
            shutil.copy2(src, dest / name)
            saved.append(name)
    (dest / "manifest.txt").write_text(
        f"backup at {datetime.now().isoformat(timespec='seconds')}\n"
        f"codex_home: {codex_home}\n"
        f"files: {', '.join(saved) if saved else '(none)'}\n"
        f"reason: before applying DeepSeek provider config\n",
        encoding="utf-8",
    )
    out(OK, f"已备份原有文件到 {dest}（{', '.join(saved) if saved else '原目录为空，无文件需备份'}）")
    return dest


def restore(codex_home: Path) -> None:
    root = codex_home / BACKUP_DIRNAME
    if not root.is_dir():
        die(f"找不到备份目录 {root}，无法还原。")
    snaps = sorted([d for d in root.iterdir() if d.is_dir()], reverse=True)
    if snaps:
        latest = snaps[0]
        out(OK, f"使用最近的备份快照：{latest}")
    elif (root / "config.toml").exists():
        # 兼容 DeepSeek 官方一键脚本的扁平布局（backup-deepseek/config.toml）
        latest = root
        out(OK, f"未找到带时间戳的快照，改用扁平备份：{latest}")
    else:
        die(f"备份目录 {root} 下没有任何可用备份（既无快照子目录，也无 config.toml）。")

    cfg = latest / "config.toml"
    if cfg.exists():
        shutil.copy2(cfg, codex_home / "config.toml")
        out(OK, "已还原 config.toml")
    else:
        out(WARN, "该快照里没有 config.toml，跳过")

    auth = latest / "auth.json"
    target_auth = codex_home / "auth.json"
    if auth.exists():
        shutil.copy2(auth, target_auth)
        out(OK, "已还原 auth.json")
    elif target_auth.exists():
        target_auth.unlink()
        out(OK, "备份中原本没有 auth.json，已删除现有的（登录态一并清除）")

    models = codex_home / "models.json"
    if models.exists():
        models.unlink()
        out(OK, "已删除 models.json")


# --------------------------------------------------------------------------
# 写文件
# --------------------------------------------------------------------------

def write_models_json(codex_home: Path, asset: Path) -> Path:
    if not asset.exists():
        die(f"技能资源缺失：{asset}")
    data = asset.read_bytes().lstrip(b"\xef\xbb\xbf")
    dest = codex_home / "models.json"
    dest.write_bytes(data)
    # 自检：必须是合法 JSON 且含两个目标模型
    try:
        obj = json.loads(dest.read_text(encoding="utf-8"))
        slugs = [m.get("slug") for m in obj.get("models", [])]
    except Exception as exc:  # noqa: BLE001
        die(f"写入的 models.json 不是合法 JSON：{exc}")
    if DEFAULT_MODEL not in slugs:
        die(f"models.json 里没有 {DEFAULT_MODEL}，内容可能被篡改。")
    out(OK, f"已写入 {dest}（{dest.stat().st_size} 字节，模型：{', '.join(slugs)}）")
    return dest


def _is_header(line: str) -> bool:
    s = line.strip()
    return s.startswith("[") and s.endswith("]")


def _merge_config(text: str, rendered: dict[str, str], provider_block: list[str]) -> str:
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.replace("\r\n", "\n").split("\n")

    first_hdr = next((i for i, l in enumerate(lines) if _is_header(l)), len(lines))
    lead, rest = lines[:first_hdr], lines[first_hdr:]

    drop = set(TARGET_KEYS) | set(CONFLICT_KEYS)

    def keep(line: str) -> bool:
        m = KEYLINE_RE.match(line)
        return not (m and m.group(1) in drop)

    lead = [l for l in lead if keep(l)]

    # 摘掉旧的 [model_providers.deepseek] 段
    rest_clean: list[str] = []
    skipping = False
    for l in rest:
        if _is_header(l):
            name = l.strip().strip("[]").strip()
            if name == f"model_providers.{PROVIDER_ID}" or name.startswith(
                f"model_providers.{PROVIDER_ID}."
            ):
                skipping = True
                continue
            skipping = False
        if not skipping:
            rest_clean.append(l)

    def tidy(block: list[str]) -> list[str]:
        while block and block[-1].strip() == "":
            block.pop()
        while block and block[0].strip() == "":
            block.pop(0)
        return block

    blocks: list[list[str]] = []
    for b in (
        tidy(lead),
        [f"{k} = {v}" for k, v in rendered.items()],
        tidy(rest_clean),
        tidy(list(provider_block)),
    ):
        if b:
            blocks.append(b)

    return ("\n\n".join("\n".join(b) for b in blocks) + "\n").replace("\n", eol)


def write_config_toml(codex_home: Path, key: str, model: str, models_path: Path) -> Path:
    path = codex_home / "config.toml"
    original = path.read_text(encoding="utf-8") if path.exists() else ""

    rendered = {
        "model": f'"{model}"',
        "model_provider": f'"{PROVIDER_ID}"',
        "preferred_auth_method": '"apikey"',
        "forced_login_method": '"api"',
        "model_reasoning_effort": '"high"',
        "web_search": '"disabled"',
        "model_catalog_json": f'"{catalog_value(models_path)}"',
    }
    provider_block = [
        f"[model_providers.{PROVIDER_ID}]",
        f'name = "{PROVIDER_ID}"',
        f'base_url = "{BASE_URL}"',
        'wire_api = "responses"',
        f'experimental_bearer_token = "{key}"',
    ]

    merged = _merge_config(original, rendered, provider_block)
    path.write_text(merged, encoding="utf-8", newline="")
    out(OK, f"已更新 {path}")
    return path


def write_auth_json(codex_home: Path, key: str) -> Path:
    """这一步才是"跳过 ChatGPT 登录"的关键。

    仅把 Key 写进 provider 的 experimental_bearer_token 只是请求头覆盖，
    不构成登录态；Codex 仍会因为没有凭据而弹登录页。
    """
    path = codex_home / "auth.json"
    payload = {"auth_mode": "apikey", "OPENAI_API_KEY": key}
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="",
    )
    out(OK, f"已写入 {path}（auth_mode=apikey，跳过 ChatGPT 登录）")
    return path


# --------------------------------------------------------------------------
# 验证
# --------------------------------------------------------------------------

def _request(url: str, key: str, payload: dict | None = None) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def verify(key: str, model: str, probe: bool) -> bool:
    print()
    ok = True

    status, body = _request(BASE_URL + "models", key)
    if status == 200:
        try:
            ids = [m["id"] for m in json.loads(body).get("data", [])]
        except Exception:  # noqa: BLE001
            ids = []
        out(OK, f"GET /models -> 200，可用模型：{', '.join(ids) or '(未解析到)'}")
        if model not in ids:
            out(WARN, f"目标模型 {model} 不在返回列表里，Codex 可能无法选用它")
    else:
        ok = False
        out(ERR, f"GET /models -> {status}：{body[:200]}")

    if probe:
        # 预算留够：推理模型会先花思考 token，卡太紧会返回 status=incomplete
        # （HTTP 仍是 200，通路本身是通的）。这里以 HTTP 状态为准判成败。
        status, body = _request(
            BASE_URL + "responses",
            key,
            {"model": model, "input": "Reply with the single word: ok",
             "max_output_tokens": 256},
        )
        if status == 200:
            try:
                st = json.loads(body).get("status") or "?"
            except Exception:  # noqa: BLE001
                st = "?"
            if st == "failed":
                ok = False
                out(ERR, f"POST /responses -> 200 但 status=failed：{body[:200]}")
            elif st == "incomplete":
                out(OK, f"POST /responses -> 200（status=incomplete，输出被预算截断，通路正常）")
            else:
                out(OK, f"POST /responses -> 200（status={st}），wire_api=responses 可用")
        else:
            ok = False
            out(ERR, f"POST /responses -> {status}：{body[:200]}")

    return ok


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        prog="setup_deepseek_codex.py",
        description="把 Codex 切换到 DeepSeek API，并跳过 ChatGPT 登录。",
    )
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    choices=["deepseek-flash", "deepseek-v4-pro"],
                    help="默认使用的模型（默认 deepseek-flash，支持图片输入）")
    ap.add_argument("--key", help="API Key（不推荐：会留在命令历史里）")
    ap.add_argument("--from-env", metavar="VAR",
                    help="从指定环境变量读取 API Key，而不是剪切板")
    ap.add_argument("--no-probe", action="store_true",
                    help="跳过 POST /responses 探测（省 token）")
    ap.add_argument("--restore", action="store_true",
                    help="还原到安装前的配置")
    ap.add_argument("--yes", action="store_true",
                    help="配合 --restore 使用，跳过确认")
    args = ap.parse_args()

    codex_home = resolve_codex_home()
    asset = Path(__file__).resolve().parent.parent / "assets" / "models.json"

    print(f"Codex 配置目录：{codex_home}")
    print(f"模型：{args.model}")
    print()

    if args.restore:
        if not args.yes:
            die("--restore 会覆盖 config.toml 并删除 models.json / auth.json，"
                "确认无误后再加 --yes 执行。")
        restore(codex_home)
        print()
        out(OK, "已还原。请重启 Codex 桌面端。")
        return 0

    if not codex_home.is_dir():
        out(WARN, f"{codex_home} 不存在。请先安装并至少运行一次 Codex CLI 或桌面端，"
                  f"再执行本技能。")

    key = acquire_key(args)
    codex_home.mkdir(parents=True, exist_ok=True)
    print()

    backup(codex_home)
    models_path = write_models_json(codex_home, asset)
    write_config_toml(codex_home, key, args.model, models_path)
    write_auth_json(codex_home, key)

    ok = verify(key, args.model, probe=not args.no_probe)

    print()
    if ok:
        out(OK, "配置完成并通过接口验证。")
    else:
        out(WARN, "文件已写入，但接口验证未全部通过——请检查 Key 是否有效/是否有余额。")
    print()
    print("下一步：重启 Codex 桌面端（CLI 无需重启），"
          "模型选择器显示 DeepSeek-Flash 或「自定义」即为生效。")
    print(f"还原命令：{Path(__file__).name} --restore --yes")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
