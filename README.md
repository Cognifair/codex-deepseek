# Codex DeepSeek Skill（AUTO DeepSeek_Codex）

把 **Codex**（Codex CLI、Codex 桌面端、VS Code 的 Codex 插件）从 ChatGPT 账号登录切换成 **DeepSeek API**，自动跳过登录页，并调用 DeepSeek 真实接口做连通性验证。

这是一个 Codex Skill：配一次，三种形态全部生效（它们共用同一份 `$CODEX_HOME` 配置）。

## 它解决什么问题

- Codex 打开就卡在 ChatGPT 登录页，登不进去、或者不想登；
- 想用自己的 DeepSeek API Key 驱动 Codex 的 Agent 能力；
- 手动改配置总差一点：只写 `preferred_auth_method` 不够，缺少 `auth.json` 时登录页照样弹出来。

## 安装

把仓库放进 Codex 的 skills 目录，然后重启 Codex 即可被识别。

Windows（PowerShell）：

```powershell
git clone https://github.com/Cognifair/codex-deepseek "$env:USERPROFILE\.codex\skills\codex-deepseek"
```

macOS / Linux：

```bash
git clone https://github.com/Cognifair/codex-deepseek ~/.codex/skills/codex-deepseek
```

## 使用

在 Codex 里直接说一句：**「配置 Codex 接入 DeepSeek」**，技能就会接管流程：

1. 请你去 [platform.deepseek.com](https://platform.deepseek.com) 复制 API Key **到系统剪切板**——不要粘贴到对话里；
2. 你回一句「好了」；
3. 脚本从剪切板读取 Key，校验后备份原配置，写入 `models.json`、`config.toml`、`auth.json`，再调用 `GET /models` 与 `POST /responses` 验证 Key 和接口通路；
4. 脚本汇报写入结果与备份位置，并提醒你重启 Codex 桌面端。

全程 API Key 只存在于你的剪切板和本机配置文件里，**不会进入对话记录**。

常用变体：

```bash
# 换用推理更强的纯文本模型
python scripts/setup_deepseek_codex.py --model deepseek-v4-pro

# 省 token：跳过接口探测
python scripts/setup_deepseek_codex.py --no-probe

# 还原到安装前的配置
python scripts/setup_deepseek_codex.py --restore --yes
```

## 写入的三个文件

| 文件 | 作用 |
| --- | --- |
| `$CODEX_HOME/models.json` | 模型目录：`deepseek-flash`（支持图片输入）与 `deepseek-v4-pro`（纯文本），内含完整 Codex 系统提示词 |
| `$CODEX_HOME/config.toml` | 顶层 7 个键 + `[model_providers.deepseek]` 段，原有 MCP / 项目信任配置原样保留 |
| `$CODEX_HOME/auth.json` | `auth_mode = "apikey"` —— **跳过 ChatGPT 登录的真正开关** |

`config.toml` 写入的顶层键：

```toml
model = "deepseek-flash"
model_provider = "deepseek"
preferred_auth_method = "apikey"
forced_login_method = "api"
model_reasoning_effort = "high"
web_search = "disabled"
model_catalog_json = "<CODEX_HOME>/models.json"
```

## 还原默认

```bash
python scripts/setup_deepseek_codex.py --restore --yes
```

会取 `~/.codex/backup-deepseek/` 下最近一次快照，还原 `config.toml` 与 `auth.json`，并删除 `models.json`。

## 目录结构

```
codex-deepseek/
├── SKILL.md                          # 技能正文：触发条件、工作流、踩坑细节、排错
├── assets/
│   └── models.json                   # 官方模型目录（76 KB，含完整 Codex 系统提示词）
├── scripts/
│   └── setup_deepseek_codex.py       # 一键配置 / 还原脚本（仅用 Python 标准库）
└── references/
    └── deepseek-codex.md             # DeepSeek 官方接入文档要点与源码依据
```

## 说明

- 配置方式整理自 DeepSeek 官方的 Codex 接入文档与一键配置脚本，并补充了 Codex 源码层面的鉴权细节（`auth.json` 字段名、凭据读取顺序、`model_catalog_json` 路径写法等）。
- 切换后如果历史会话「消失」，那是 Codex 按登录方式分组显示，会话没有被删除；执行 `--restore` 即可回到原分组。
- 需要自备 DeepSeek API Key；配置完成后请重启 Codex 桌面端。
