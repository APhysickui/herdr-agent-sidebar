# 配置与命名规则

## 三行侧栏

示例见 [`examples/sidebar.toml`](../examples/sidebar.toml)。内置 `pane` 字段显示明确设置的名称，`$task` 显示自动名称。手动名称存在时，插件会清除自己的 `$task`，避免重复显示。

`$pane_id` 显示完整稳定 ID，`$folder` 显示经过缩短的当前目录。可选前景目录优先于启动目录。

自动名称顺序：Pi 当前会话的有效提问 → Pi 输入扩展发布的提问 → 有意义的终端标题 → 目录。在 home 目录没有有效标题时，显示“新任务 / agent”。

## 运行时设置

安装目录中的 `settings.toml`：

```toml
herdr_binary = "herdr"
socket_path = ""
pi_sessions = ""
pi_titles = true
kimi_compat = false
```

安装器会填写当前机器的绝对路径。空 socket 路径默认使用当前用户的 `~/.config/herdr/herdr.sock`，空 Pi 会话路径默认使用 `~/.pi/agent/sessions`。`HERDR_SIDEBAR_CONFIG` 可指向另一份设置。

启用 Pi 后，扫描每个目录最近的最多 30 个会话文件，单文件上限 8 MB。至少两个独特的长文本行匹配当前画面，而且最佳匹配不能并列，才会采用该会话的最近有效提问。匹配不确定时使用其他信息，不按文件时间直接分配。

## 固定名称与自动名称

```sh
herdr pane rename w1:p1 '论文公式检查'
herdr pane rename w1:p1 --clear
```

第一条固定，第二条恢复自动模式。若之前某个脚本替你改过名，它在 Herdr 看来同样属于明确名称，必须清除一次。仅仅增加定时器无法让固定名称变化。

## 排序

在自己的 Herdr 配置中选择：

```toml
[ui]
agent_panel_sort = "spaces" # 按工作区、标签页分组
# agent_panel_sort = "priority" # 优先看需要关注的 agent
```

已有 `rows_by_agent` 配置可能覆盖默认侧栏行。如果某一类 agent 布局不同，检查该覆盖项。安装器保留这些个人配置。
