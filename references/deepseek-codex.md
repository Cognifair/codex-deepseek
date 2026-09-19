# DeepSeek 接入 Codex —— 官方资料要点与来源

本文件是 `AUTO DeepSeek_Codex` 的事实依据留档。脚本里的每个取值都来自下面这些来源，不是推测。

## 一、官方文档

- 接入 Codex（中文）：
  `https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/codex/`
- 一键配置脚本（Windows PowerShell，本技能的 `assets/models.json` 即来自此脚本内嵌内容）：
  `https://cdn.deepseek.com/api-docs/codex-deepseek-setup.ps1`
- 一键配置脚本（macOS / Linux）：
  `https://cdn.deepseek.com/api-docs/codex-deepseek-setup.sh`

### 官方 `config.toml` 字段说明

| 字段 | 作用 |
| --- | --- |
| `model` | 默认使用的模型 |
| `model_provider` | 模型提供方，对应下方 `[model_providers.<id>]` 段的 id |
| `preferred_auth_method`、`forced_login_method` | 使用 API Key 认证，跳过 ChatGPT 账号登录 |
| `model_reasoning_effort` | 推理强度。越高思考越深入，越慢越贵 |
| `web_search` | 内置联网搜索，DeepSeek 模型下必须 `"disabled"` |
| `model_catalog_json` | 自定义模型目录文件（`models.json`）的路径 |
| `[model_providers.deepseek]` 的 `name` | 提供方显示名称 |
| `[model_providers.deepseek]` 的 `base_url` | `https://api.deepseek.com/` |
| `[model_providers.deepseek]` 的 `wire_api` | `"responses"` 表示走 Responses API |
| `[model_providers.deepseek]` 的 `experimental_bearer_token` | 直接写在配置里的 API Key |

### 官方脚本做了四件事

1. 把现有 `~/.codex/config.toml` 备份到 `~/.codex/backup-deepseek/`
2. 写入 `~/.codex/models.json`
3. 只改写必要字段并新增 `[model_providers.deepseek]` 段，原有 MCP / 项目信任级别配置全部保留；冲突字段会删除并打印原因
4. 写入前校验 `config.toml` / `models.json` 语法，失败则中止且不修改任何文件

官方脚本版本记录中，`<= 1.2.0` 曾安装 `deepseek-v4-flash` / `deepseek-v4-flash-vision-exp`，新版本会清理这些旧条目，只保留 `deepseek-flash` 与 `deepseek-v4-pro`。

## 二、Codex 侧的行为（读源码得到）

来源仓库：`https://github.com/openai/codex`

| 结论 | 源码位置 |
| --- | --- |
| `AuthDotJson` 结构：`auth_mode` / `OPENAI_API_KEY`（serde 大写下划线）/ `tokens` / `last_refresh` / `agent_identity` / `personal_access_token` / `bedrock_*` | `codex-rs/login/src/auth/storage.rs` |
| `AuthMode::ApiKey` 序列化为小写 `"apikey"`（`rename_all = "lowercase"`） | `codex-rs/protocol/src/auth.rs` |
| `AuthCredentialsStoreMode` 枚举顺序为 `File`（`#[default]`）/ `Keyring` / `Auto` / `Ephemeral` | `codex-rs/config/src/types.rs` |
| 取凭据顺序：`CODEX_API_KEY` 环境变量 → 内存临时存储 → `CODEX_ACCESS_TOKEN` → 持久化存储（file/keyring） | `codex-rs/login/src/auth/manager.rs` 的 `load_auth` |
| `forced_login_method = "api"` + `auth_mode = "apikey"` 是合法组合，不会触发「登出并退出」 | `codex-rs/login/src/auth/manager.rs` 的 `enforce_login_restrictions` |
| 凭据文件路径为 `$CODEX_HOME/auth.json` | `codex-rs/login/src/auth/storage.rs` 的 `get_auth_file` |

要点：**`preferred_auth_method = "apikey"` 只有在「存在可用 API Key 凭据」时才跳过登录页。** provider 段的 `experimental_bearer_token` 只是请求头覆盖，不算凭据。

## 三、其它参考

- Codex 官方鉴权文档（登录方式、`cli_auth_credentials_store`、`forced_login_method`、Access Token）：
  `https://developers.openai.com/codex/auth`
- 令牌化认证、API Key 认证的差别说明（含 `preferred_auth_method` 取值 `chatgpt` / `apikey` / `access_token`）：
  `https://github.com/rnarciso/open-codex/blob/main/docs/authentication.md`

## 四、模型差异

| 配置项 | `deepseek-flash` | `deepseek-v4-pro` |
| --- | --- | --- |
| `input_modalities` | `["text", "image"]` | `["text"]` |
| `supports_image_detail_original` | `true` | `false` |
| `supports_search_tool` | `true` | `false` |
| `display_name` | `DeepSeek-Flash` | `DeepSeek-V4-Pro` |
| `priority` | `1` | `2` |

两者相同的项：`context_window` / `max_context_window` 均为 1048576，`effective_context_window_percent` 95，`comp_hash` `"3000"`，`supported_reasoning_levels` 为 `low` / `high` / `max`，`minimal_client_version` `0.144.0`。

## 五、接口验证方式

无需 Codex 即可验证 Key 与通路：

```bash
# 1) Key 有效性 + 可用模型
curl https://api.deepseek.com/models -H "Authorization: Bearer $KEY"

# 2) Responses API 通路（Codex 依赖的协议）
curl https://api.deepseek.com/responses \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"deepseek-flash","input":"reply with the single word: ok","max_output_tokens":16}'
```

正常响应中 `status` 为 `"completed"`，`output` 数组同时包含 `reasoning` 与 `message`（`phase: "final_answer"`）两类条目。

若本机已装 Codex CLI，可用更贴近真实链路的验证：

```bash
codex login status                                    # 期望：Logged in using an API key - sk-xxxxx***xxxx
codex exec --skip-git-repo-check --sandbox read-only "reply with exactly: OK"
# 启动信息里应显示 model: deepseek-flash / provider: deepseek
```
