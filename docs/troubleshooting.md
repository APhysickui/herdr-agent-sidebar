# 故障处理

## 为什么名字还是旧的

先检查是否曾经执行过 `pane rename`。固定名称始终优先：

```sh
herdr pane get w1:p1
herdr pane rename w1:p1 --clear
herdr plugin action invoke community.agent-sidebar.refresh
```

Pi 的 `π - 用户名` 是通用终端标题，没有任务内容。只读取终端标题无法更新它；需要启用 `--with-pi`。自动名称是最新有效提问的短预览，不是模型生成的摘要。

## Kimi Code 不显示

实际遇到的组合是 **Herdr 0.8.2 + Kimi Code 2.1.1**：进程名为 `kimi`，但 argv0 显示为 `kimi-co`。该版 Herdr 优先使用 argv0，无法识别这个别名。某些官方状态来源又要求原生进程识别成功，因此写入状态也可能被静默忽略。

检查当前 pane：

```sh
herdr pane process-info --pane w1:p1
herdr pane read w1:p1 --source detection --lines 25
herdr pane get w1:p1
```

本项目的可选兼容层使用 Herdr 支持的自定义 agent `kimi-local`，显示名为 **Kimi Code**。Kimi 的生命周期事件负责即时状态；定时检查会核实前景进程和当前 Kimi 画面，并在进程退出后解除该身份。状态不确定时不会把一个普通 shell 强行标成工作中。

**不要把静态页脚里的 `thinking` 当成正在生成。** 工作状态需要实际 spinner 或生命周期事件；等待确认需要确认面板或对应钩子事件。

### 已安装官方或旧版钩子

先备份 `~/.kimi-code/config.toml`，检查其中调用 `herdr-agent-state.sh` 或旧版 `kimi-state.sh` 的 `[[hooks]]`。按自己的安装方式移除这些 Herdr 状态钩子，保留其他服务的 hook，然后运行本项目安装器。不要同时保留两套争夺状态的来源。

如果旧 pane 已绑定官方会话来源，Herdr 0.8.2 可能拒绝自定义来源接管。已验证的办法是：记录原 session ID，在同一目录的新 pane 用 `kimi --session SESSION_ID` 恢复，核对聊天和状态后，再决定是否关闭旧 pane。安装器不会自动创建或关闭会话。

这属于旧版本兼容处理。已经能原生识别 Kimi 的 Herdr 版本优先使用官方集成，不启用 `--with-kimi`。

## 定时器未刷新

```sh
launchctl print gui/$(id -u)/dev.herdr.agent-sidebar
cat ~/.local/share/herdr-agent-sidebar/refresh.log
```

确认 `last exit code = 0`，配置的 socket 对应当前会话。新版实时服务应显示 `running`；`runs` 不应持续快速增加。旧版分钟服务才会执行后退出。pane 被显式命名时请先清除固定标签；tab 自动命名需要安装时加 `--auto-tabs`。

## 从早期本机脚本迁移

早期手工方案可能注册为 `local.pane-id`，并使用 `dev.herdr.sidebar-refresh` 定时器。先记录原路径和备份，停用旧定时器与插件，再按本项目的安装步骤操作。确认新安装正常后再归档旧脚本。不要删除聊天目录或 Herdr 会话文件。

## 卸载提示文件有修改

安装后编辑过 Herdr/Kimi 配置会触发保护。先自行备份当前文件，查看安装目录 `install-state.json` 中保存的原版本，协调需要保留的差异。卸载器会在任何移除操作之前停止，不提供强制覆盖开关。
