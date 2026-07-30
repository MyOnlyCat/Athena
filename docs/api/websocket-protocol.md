# Web SSH WebSocket 协议

连接地址：`/api/v1/terminal/ws/{host_id}`。先使用 Bearer JWT 调用
`POST /api/v1/terminal/tickets` 并发送 `{"host_id":"..."}`。票据有效期
30 秒、只能使用一次且绑定用户和主机；每个用户最多 5 个并发终端。

## 握手

WebSocket 建立后，客户端发送的第一帧必须是 JSON：

```json
{"ticket":"一次性票据","cols":120,"rows":36}
```

服务端完成 SSH PTY 创建后确认：

```json
{"type":"connected"}
```

PTY 类型固定为 `xterm-256color`，初始尺寸来自第一帧。

## 二进制输入输出

SSH PTY 以二进制模式运行。JSON 只是传输信封；`input` 与 `output` 的 `data`
都是原始字节的 Base64，不应先按 UTF-8、行或字符重新解释：

```json
{"type":"input","data":"bHMNCg=="}
{"type":"output","data":"ZmlsZS50eHQNCg=="}
```

浏览器把 xterm 输入编码为字节再 Base64；输出则先 Base64 解码为
`Uint8Array` 后直接写入 xterm。因此 ANSI 控制序列、中文输出和任意分块边界
不会被 JSON 文本编码破坏。

调整终端尺寸和应用层保活：

```json
{"type":"resize","cols":160,"rows":42}
{"type":"ping"}
{"type":"pong"}
```

## 页面和会话生命周期

进入 UI `/terminal` 时默认启用“应用内全屏”：隐藏 Athena 侧栏与顶栏，让三栏
终端占满应用视口。工具栏按钮可恢复导航或再次进入；该功能不调用浏览器 Fullscreen
API。

选择另一台服务器会提示当前 SSH 会话将关闭。确认切换、离开 `/terminal` 或组件
卸载时，浏览器关闭 WebSocket 并销毁 xterm。服务端在 WebSocket 断开、任一桥接
方向结束或桥接报错时，取消另一方向任务并关闭 SSH 进程与连接。

## 错误与排查

- 无效、过期、主机不匹配或已使用票据：发送
  `{"type":"error","code":"INVALID_TERMINAL_TICKET"}`，随后以 4401 关闭。
- 主机不存在或尚未确认 SSH 指纹：以 4404 关闭。先在 `/hosts` 完成连接测试和
  指纹确认；未确认主机不会出现在终端服务器列表中。
- SSH 认证失败、主机指纹变更、网络连接失败、通道打开失败会分别尽力发送
  `TERMINAL_AUTH_FAILED`、`TERMINAL_HOST_KEY_CHANGED`、
  `TERMINAL_NETWORK_ERROR`、`TERMINAL_CHANNEL_ERROR`；其他会话打开失败发送
  `TERMINAL_OPEN_ERROR`。
- 建立 SSH 后桥接失败会尽力发送对应的网络或通道错误；无法进一步分类时发送
  `TERMINAL_BRIDGE_ERROR`，然后清理连接。
- UI 长期显示 `connecting` 或很快变为 `closed`：检查主机在线状态、端口、账号
  密码、防火墙和已保存指纹；必要时在主机页重新运行连接测试。
- 票据在 30 秒后失效，网络恢复后不会复用旧票据；重新选择主机或重新进入页面以
  创建新会话。
