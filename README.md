# xx-cli

你想在网页上反复做的事，一句话告诉 AI agent，它就能帮你做成 CLI 工具。生成的 CLI 让 agent 随时调用，直接驱动你真实的 Chrome 登录态，不走 API，不折腾 token。

仓库里收录了几个这样做出来的 CLI，既能装好就用，也作为参考案例，演示 AI agent + [OpenBridge](https://github.com/60ke/openBridge) 是怎么从一句需求生成一个完整 CLI 的。后文「自己做一个新 CLI」会走完整流程。

DEMO（一个 CLI 的诞生过程）：

https://github.com/user-attachments/assets/c1d04187-972a-4b8a-b243-df085281fc77

## 自己做一个新 CLI

仓库里几个 CLI 都是用 `skills/agent-cli-creator/` 这个 skill，让 AI agent 自动产出的。给你的 agent 装好下面这一套，对它说一句「帮我给 example.com 做个 CLI」就行。

### 前置依赖

要让 agent 控制你当前登录的 Chrome，需要安装 [OpenBridge](https://github.com/60ke/openBridge)：

1. **安装本地 daemon 和配套 skill**：

   ```bash
   curl -fsSL https://raw.githubusercontent.com/60ke/openBridge/master/install.sh | bash
   ```

   也可以只用 npm 安装 daemon：

   ```bash
   npm install -g @openbridge-org/daemon
   openbridge start
   ```

2. **安装 Chrome 扩展**：[OpenBridge - Chrome Web Store](https://chromewebstore.google.com/detail/openbridge/mdoemfmcfdgoehpcnjiecocecjcmmblh)。打开扩展面板完成授权，并启用本仓库需要的 `browser_evaluate` 工具。

3. **检查连接**：

   ```bash
   curl -s http://127.0.0.1:10088/health
   ```

   返回的 `ok` 应为 `true`，`connectedSessions` 应非空。OpenBridge 默认使用 `10088`；若端口被占用，它可能自动切换到 `10089`–`10098`。此时可查看 `.openbridge-data/runtime.json`，并设置：

   ```bash
   export OPENBRIDGE_URL=http://127.0.0.1:<实际端口>
   ```

### 安装 skill

```bash
npx skills add guoguo931112-spec/xx-cli
```

<details>
<summary>没有 Node.js？手动安装</summary>

把 `skills/agent-cli-creator/` 复制到你 agent 的 skills 目录即可（Claude Code 是 `~/.claude/skills/`）。不确定路径？把这一段 README 丢给你的 agent，它会自己判断。

</details>

装完就能用，对话里说一句「帮我给 example.com 做个 CLI」即可触发。

### 怎么用

1. 启动 OpenBridge daemon、连接并授权 Chrome 扩展，然后在 Chrome 里登录目标网站。
2. 对 agent 说，比如：
   > "帮我做一个 example.com 的 CLI，我要能拉首页信息流，并且能发评论。"
3. agent 会先问你几个问题（用什么语言、前 1–3 个功能是什么），然后自己去分析站点、搭脚手架、实现命令，关键节点会停下来确认。
4. 最终你会拿到一个这样用的工具：
   ```bash
   example-cli login-status
   example-cli home --limit 10
   example-cli post --content "hello"
   ```

## 包含的 CLI

| 工具 | 一句话 |
|---|---|
| [`baidu-cli`](./baidu-cli/) | 百度搜索，输出 JSON |
| [`google-cli`](./google-cli/) | Google 搜索 + 网页抓取，输出 JSON |
| [`nanobanana-cli`](./nanobanana-cli/) | 用 Gemini 2.5 Flash Image (Nano Banana) 生成图片 |
| [`chatgpt-image-cli`](./chatgpt-image-cli/) | 用 chatgpt.com/images 生成图片 |
| [`taobao-cli`](./taobao-cli/) | 淘宝搜索 + 包邮/48h筛选 + 价格/销量过滤 + 翻页，导出 CSV |
| [`aldspdd-cli`](./aldspdd-cli/) | 阿奇索·拼多多自动发货：批量体检在售商品绑定的货源编号是否失效（搜不到=货源没了） |

## 安装预编译二进制

去 [Releases 页面](https://github.com/guoguo931112-spec/xx-cli/releases) 下载对应平台的归档，解压即可用。

### macOS 打开提示

遇到「无法打开，因为开发者身份未验证」时，执行：

```bash
xattr -d com.apple.quarantine ./<cli-name>
```

### 本地编译

```bash
git clone https://github.com/guoguo931112-spec/xx-cli
cd xx-cli/<某个-cli>
go build -o ./<cli-name> .
```

## License

MIT，见 [LICENSE](./LICENSE)。
