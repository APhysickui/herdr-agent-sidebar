# 安装与卸载

## 基本安装

```sh
python3 install.py --dry-run
python3 install.py
```

默认安装到 `~/.local/share/herdr-agent-sidebar`，链接插件 `community.agent-sidebar`，将侧栏布局合并进 `~/.config/herdr/config.toml`。不会修改主题、前缀键、排序和其他插件配置。

macOS 会生成 `~/Library/LaunchAgents/dev.herdr.agent-sidebar.plist`，在当前用户登录会话中常驻监听，并每 2 秒检查会话文件。Herdr 没运行时等待重连。Linux 不创建定时服务，仍会响应插件事件。

## 可选项

| 参数 | 作用 |
| --- | --- |
| `--with-pi` | 安装 Pi 输入扩展，并启用已有会话的自动取名 |
| `--with-kimi` | 安装 Kimi 状态兼容钩子，需先检查旧集成 |
| `--prefix PATH` | 自定义安装目录，不能是源码目录 |
| `--herdr PATH` | 指定 Herdr 可执行文件 |
| `--config PATH` | 指定 Herdr 配置文件 |
| `--socket PATH` | 指定当前 Herdr 会话的 socket |
| `--interval 2` | 会话文件兜底检查间隔，至少 0.5 秒 |
| `--auto-tabs` | 将现有 tab 纳入任务自动命名；之后手动改名会保留 |
| `--no-timer` | 仅安装事件刷新，不创建定时服务 |
| `--no-activate` | 只写文件，不链接插件或启动服务 |
| `--dry-run` | 列出文件和操作，不写入或启动任何内容 |

命名会话需要正确的 `--socket`。一个安装对应一个定时检查的 socket，事件调用仍使用 Herdr 注入的当前会话环境。不要给多个安装复用同一个插件 ID 和 LaunchAgent 标签。

Pi 新扩展会在下次启动或 Pi 自身加载扩展后接收输入；现有 Pi 不必重启，也能通过每分钟的会话匹配获得任务名。Kimi 新配置需要其进程加载配置；安装器不会代你退出、重启或关闭任何 pane。

## 卸载

从源码目录运行：

```sh
python3 install.py --uninstall --dry-run
python3 install.py --uninstall
```

自定义过安装目录时，加上同样的 `--prefix`。卸载会注销本项目的插件和定时服务，并恢复安装时记录的原文件。发现后续编辑时会在操作前停止；先备份并协调差异，再卸载。不要通过覆盖安装备份来绕过差异检查。

恢复信息保存在安装目录的 `install-state.json`，权限为 `0600`。它可能包含原配置的备份，**不要提交到 GitHub**。源码仓库不生成这个文件。
