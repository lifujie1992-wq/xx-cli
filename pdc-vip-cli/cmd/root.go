package cmd

import "github.com/spf13/cobra"

var rootCmd = &cobra.Command{
	Use:   "pdc-cli",
	Short: "唯品会 PDC 供应商创建商品 CLI（基于 OpenBridge 驱动你的真实 Chrome）",
	Long: `pdc-cli 在你已登录的真实 Chrome 里(经 OpenBridge http://127.0.0.1:10088)
读取唯品会供应商平台 pdc-portal.vip.com 的创建商品数据：

  pdc-cli login-status            # 确认登录态 + 当前商家
  pdc-cli categories              # 商品分类树（默认去掉停用项）
  pdc-cli config <categoryId>     # 某叶子类目的必填/开关配置
  pdc-cli get <vendorProductId>   # 读一个完整商品（创建提交体的样板）

所有调用都在浏览器页面内以 fetch 复用你的登录 cookie，结果以 JSON 输出到 stdout。
接口与提交体结构见 ARCHAEOLOGY.md。`,
}

func Execute() error { return rootCmd.Execute() }
