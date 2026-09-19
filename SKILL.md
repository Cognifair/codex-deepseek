---
name: AUTO DeepSeek_Codex
display_name: AUTO DeepSeek_Codex
description: "把 Codex（Codex CLI、Codex/ChatGPT 桌面端、VS Code 的 Codex 插件）从 ChatGPT 账号登录切换为 DeepSeek API，并自动跳过登录页。执行时先要求用户把 DeepSeek API Key 复制到系统剪切板（而不是粘贴到对话里），再从剪切板读取该 Key，写入 models.json、config.toml、auth.json，最后调用 DeepSeek 真实接口做连通性验证。当用户提出「配置 Codex 接入 DeepSeek」「把 DeepSeek 接到 Codex」「Codex 免登录」「Codex 跳过 ChatGPT 登录」「Codex 换掉 GPT 用 DeepSeek API」这类需求时使用。"
agent_created: true
---

# AUTO DeepSeek_Codex

把 Codex 全形态（Codex CLI / Codex 桌面端 / VS Code 插件）从 ChatGPT 账号登录切换到 DeepSeek API，并让登录页不再出现。

三种形态共用同一份 `$CODEX_HOME`（默认 `~/.codex`，Windows 为 `%USERPROFILE%\.codex`）配置，因此**配置一次即可全部生效**。

## 何时触发

- 用户说「配置 Codex 接入 DeepSeek」「把 DeepSeek 接到 Codex」「Codex 用 DeepSeek API」
- 用户说「Codex 免登录」「跳过 ChatGPT 登录」「不要让我登 GPT 账号」
- 用户已经在 Codex 里被卡在 ChatGPT 登录页，想改用 DeepSeek

## 铁律：API Key 只走剪切板，不进对话

这是本技能最容易被做错的一步，必须严格执行：

- **绝不**请用户把 API Key 粘贴到对话里。对话内容会进入会话记录、日志与上下文，Key 一旦写进对话就等于泄露。
- **必须**请用户把 Key 复制到系统剪切板，然后由脚本从剪切板读取。这样 Key 只存在于用户的剪贴板和本机配置文件中。

## 工作流

### 第 1 步：向用户索取 Key（必须先做，再动任何文件）

先向用户说明下面这段话，不要跳过、不要自己编 Key、不要先用占位符跑一遍：

> 请到 DeepSeek 开放平台（platform.deepseek.com）复制你的 API Key（以 `sk-` 开头），**复制到系统剪切板**即可 —— 不要粘贴到这里，避免密钥留在对话记录里。复制好了回我一句「好了」。

### 第 2 步：等用户确认

用户明确回复「好了 / 已复制 / OK」之后再继续。若用户直接把 Key 贴在对话里，仍按剪切板流程走，并提醒他下次用剪切板；同时不要复述该 Key。

### 第 3 步：运行脚本

脚本会自动完成「读剪切板 → 校验 → 备份 → 写三个文件 → 调接口验证」全流程，幂等，可重复执行。

```bash
python scripts/setup_deepseek_codex.py
```

常用变体：

```bash
# 换用推理更强的纯文本模型
python scripts/setup_deepseek_codex.py --model deepseek-v4-pro

# 省 token：跳过 POST /responses 探测
python scripts/setup_deepseek_codex.py --no-probe

# 还原到安装前的配置
python scripts/setup_deepseek_codex.py --restore --yes
```

若系统 PATH 里没有 `python`，改用 WorkBuddy 自带解释器（Windows 示例）：

```bash
"C:/Users/<用户名>/.workbuddy/binaries/python/versions/3.13.12/python.exe" scripts/setup_deepseek_codex.py
```

### 第 4 步：核对脚本输出

成功时应看到这些行：

| 输出 | 含义 |
| --- | --- |
| `已从 Windows 剪切板读取到凭据` | 剪切板读到内容（脚本只打印前 7 位，不回显完整 Key） |
| `已备份原有文件到 ...\backup-deepseek\<时间戳>` | 备份成功，可随时还原 |
| `已写入 ...\models.json` | 模型目录就位 |
| `已更新 ...\config.toml` | 配置合并完成 |
| `已写入 ...\auth.json（auth_mode=apikey，跳过 ChatGPT 登录）` | 登录态就位 |
| `GET /models -> 200` | Key 有效 |
| `POST /responses -> 200` | `wire_api = "responses"` 通路可用 |

脚本退出码：`0` 全部成功，`2` 文件已写入但接口验证未全通过，`1` 前置条件失败（未改动任何文件）。

### 第 5 步：汇报并提醒重启

向用户汇报：写到哪三个文件、备份在哪、验证结果。然后**必须**提醒：**Codex 桌面端需要重启**才会重新读取 `auth.json`（CLI 不用重启，直接 `codex` 即可）。

## 脚本落地的三个文件

| 文件 | 作用 |
| --- | --- |
| `$CODEX_HOME/models.json` | 模型元数据目录，声明 `deepseek-flash`（支持图片输入）与 `deepseek-v4-pro`（纯文本） |
| `$CODEX_HOME/config.toml` | 顶层 7 个键 + `[model_providers.deepseek]` 段；其余内容原样保留 |
| `$CODEX_HOME/auth.json` | **跳过登录的真正开关**，`auth_mode = "apikey"` |

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

## 关键实现细节（这些是踩过坑才知道的，不要自行简化）

### 1. 只设 `preferred_auth_method` 是不够的

`preferred_auth_method = "apikey"` 只在**确实存在一份可用的 API Key 凭据**时才跳过登录页。把 Key 只写进 provider 的 `experimental_bearer_token` 属于「请求头覆盖」，**不构成登录态**——Codex 查不到凭据，照旧弹 ChatGPT 登录。所以必须额外落一份 `auth.json`。

### 2. `auth.json` 的字段名是硬性的

依据 Codex 源码 `codex-rs/login/src/auth/storage.rs` 的 `AuthDotJson` 结构体：

- `OPENAI_API_KEY` 是 serde rename 后的**大写下划线**形式（Rust 字段名其实是 `openai_api_key`）。写错大小写会静默失效。
- `auth_mode` 取值是小写 `apikey`（枚举 `ApiKey` 配了 `rename_all = "lowercase"`）。
- `tokens`、`last_refresh` 等字段可省略；`Option` 字段缺失时按 `None` 处理。

```json
{
  "auth_mode": "apikey",
  "OPENAI_API_KEY": "<DeepSeek API Key>"
}
```

### 3. `model_catalog_json` 必须用绝对路径 + 正斜杠

Windows 下 Codex 不保证展开 `~`，而反斜杠又是 TOML 的转义字符。脚本统一转成 `C:/Users/.../models.json` 这种形式。

### 4. 顶层键必须写在第一个表头之前

TOML 里表头之后的键会归属到该表。脚本把 7 个目标键插到首个 `[...]` 之前，并清掉会劫持请求的 `profile` / `oss_provider` / `openai_base_url`。其它表里的同名键（例如 `[profile.ci]` 下的 `model`）**不动**。

### 5. 凭据存储模式不用额外配

`AuthCredentialsStoreMode` 的默认值就是 `File`（`codex-rs/config/src/types.rs` 里的 `#[default]`），因此不写 `cli_auth_credentials_store` 也会读 `auth.json`。默认 `File` 也意味着 Windows 凭据管理器里的旧记录不会覆盖它。

### 6. 用 API Key 时日志里那句报错是正常的

日志会反复出现：

```
remote control requires ChatGPT authentication; API key auth is not supported
```

这是 Codex Cloud **远程控制**功能在等 ChatGPT 登录，与聊天能否使用无关。看到它不要以为配错了。

### 7. 切换后历史会话「消失」是分组显示

Codex 按登录方式分组存放会话：ChatGPT 订阅产生的会话与第三方 API 产生的会话分属两组，界面只显示与当前配置匹配的那组。会话没有被删除，还原配置即可重新看到。

## 排错

| 现象 | 处理 |
| --- | --- |
| 脚本报「剪切板是空的」 | 让用户重新复制；确认复制的是 Key 本身而不是页面上别的内容 |
| 脚本报「多行内容」 | 用户复制时带了杂质，让ta只选中 Key 再复制 |
| 脚本报「不以 sk- 开头」 | 复制错内容（常见是复制了网址） |
| `GET /models -> 401` | Key 无效或已吊销 |
| `GET /models -> 402` | DeepSeek 账户余额不足 |
| 桌面端重启后仍弹登录页 | 确认 `auth.json` 还在（有些登录流程会覆写它）；用 `CODEX_HOME` 指向别处启动的话要写到那个目录 |
| 仍旧显示 GPT 模型 | 桌面端没重启；或 `model_catalog_json` 路径不对导致回退到内置目录 |
| 想确认登录态 | `codex login status` 应输出 `Logged in using an API key - sk-xxxxx***xxxx` |

## 还原默认

```bash
python scripts/setup_deepseek_codex.py --restore --yes
```

会取 `backup-deepseek/` 下最近一次快照，还原 `config.toml` 与 `auth.json`，并删除 `models.json`。

## 目录结构

```
AUTO DeepSeek_Codex/
├── SKILL.md                          # 本文件
├── assets/
│   └── models.json                   # 官方模型目录（76 KB，含完整 Codex 系统提示词，勿裁剪）
├── scripts/
│   └── setup_deepseek_codex.py       # 一键配置 / 还原脚本（仅用标准库）
└── references/
    └── deepseek-codex.md             # 官方接入文档要点与来源
```

`assets/models.json` 里每个模型都内嵌了约 17 KB 的 Codex 系统提示词（`instructions_template` 与 `base_instructions`）。**不要为了瘦身删掉它们**——DeepSeek 官方文档页面把这部分省略成了占位符，照页面抄会得到缺系统提示词的残缺配置。此处保留的是官方一键脚本内嵌的原始内容。

## 修改本技能的注意事项

- 改动涉及可执行脚本或外部网络调用后，建议对技能目录做一次安全扫描再分发。
- `name`、`description`、`agent_created` 三个字段不要改名或删除。
- 新增踩坑点请补进上面的「关键实现细节」或「排错」章节。
