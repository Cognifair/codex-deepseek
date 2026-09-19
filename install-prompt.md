# 一键安装提示词

把下面整段复制给任意能执行命令的 AI 助手（Codex、Claude Code、Cursor 等），它会自己下载并安装这个技能，不需要你手动解压或复制文件。

~~~text
请把 GitHub 上的 Codex 技能 codex-deepseek 直接下载并安装到本机，不要问我步骤，自己判断操作系统和网络情况后动手：

仓库地址：https://github.com/Cognifair/codex-deepseek

一、确定安装位置
- 技能根目录优先取环境变量 CODEX_HOME，没有就用 ~/.codex（Windows 是 %USERPROFILE%\.codex）。
- 目标目录 = <CODEX_HOME>/skills/codex-deepseek；父目录 skills 不存在就先创建。

二、下载并安装
- 首选 git：git clone --depth 1 https://github.com/Cognifair/codex-deepseek.git "<目标目录>"。
- 如果目标目录已存在，先重命名成 codex-deepseek.bak-<时间戳> 备份保留，再安装，不要直接删。
- 没有 git、或克隆失败（例如网络不通）就下载压缩包再解压：
  https://codeload.github.com/Cognifair/codex-deepseek/tar.gz/refs/heads/main
  Windows 也可以直接用：https://github.com/Cognifair/codex-deepseek/archive/refs/heads/main.zip
  注意解压后会多出一层 codex-deepseek-main 目录，要把里面的内容直接放到 <目标目录> 下，不要多一层目录。
- 如果直连 GitHub 失败，尝试本机代理（常见 127.0.0.1:7897 或 127.0.0.1:7890）；Windows 上用 git 时可加 -c http.sslBackend=openssl。

三、校验安装结果
- <目标目录> 下必须存在：SKILL.md、assets/models.json、scripts/setup_deepseek_codex.py、references/deepseek-codex.md、README.md。
- SKILL.md 的 YAML frontmatter 里 name 应为 AUTO DeepSeek_Codex。
- 校验不通过就重试一次；仍然失败就把原始报错贴给我。

四、收尾汇报
- 告诉我装到了哪个路径、校验结果，以及下一步怎么用（在 Codex 里说「配置 Codex 接入 DeepSeek」）。
- 提醒我重启 Codex 桌面端才会加载新技能。

五、本次只做安装
- 不要执行 scripts/setup_deepseek_codex.py，不要改我的 ~/.codex/config.toml、auth.json 或 API Key，这次只安装技能文件。
~~~

## 说明

- 提示词刻意把「只安装、不配置」写死，避免助手顺手改你的 Codex 配置或读取 API Key。
- 覆盖安装时走备份改名，不会直接删除旧版本。
- 如果对方助手习惯先问问题，可以直接回一句「按提示词执行」。
