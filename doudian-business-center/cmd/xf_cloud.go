package cmd

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"

	"github.com/spf13/cobra"
)

func init() {
	var (
		nodePath             = "node"
		scriptPath           string
		baseToken            = "REPLACE_WITH_FEISHU_APP_TOKEN"
		tableID              = "tblV47nFb6dhqgrR"
		viewID               = "vewuNwuUGQ"
		statusField          = "晓风云库状态"
		larkCLI              = "~/.npm-global/bin/lark-cli"
		doudianSession       = "doudian-business-center"
		xfSession            = "doudian-xf-batch"
		relationID           = "123456789"
		plugID               = "REPLACE_WITH_PLUGIN_ID"
		xfBaseURL            = "https://xfdyorder.zzbtool.com/zzb_super_goods_xf/index.html?t=1783143706746"
		stateFile            = "~/xx-cli/doudian-business-center/output/xf-cloud-batch-state.jsonl"
		keyword              string
		limit                int
		startOffset          int
		retryGrowthSkipped   bool
		retryFindTabFailures bool
		retryXFEmpty         bool
	)

	xfCloudCmd := &cobra.Command{
		Use:           "xf-cloud",
		Short:         "从飞书表读取关键词并添加晓风云商品库",
		SilenceUsage:  true,
		SilenceErrors: true,
		Long: `从飞书多维表读取关键词，逐条查抖店商机中心的完全匹配商机；
搜索次数需大于 1w，然后打开晓风截流页面，筛选「抖音面单 / 一件代发 / 包邮」，
在前三个货源中选择价格最低的商品添加到晓风云商品库，并回写飞书状态列。`,
		Run: func(cmd *cobra.Command, args []string) {
			if scriptPath == "" {
				var err error
				scriptPath, err = defaultXFCloudScriptPath()
				if err != nil {
					fail("script_not_found", err)
				}
			}
			argv := []string{
				scriptPath,
				"--base-token", baseToken,
				"--table-id", tableID,
				"--view-id", viewID,
				"--status-field", statusField,
				"--lark-cli", larkCLI,
				"--doudian-session", doudianSession,
				"--xf-session", xfSession,
				"--relation-id", relationID,
				"--plug-id", plugID,
				"--xf-base-url", xfBaseURL,
				"--state-file", stateFile,
			}
			if limit > 0 {
				argv = append(argv, "--limit", fmt.Sprint(limit))
			}
			if startOffset > 0 {
				argv = append(argv, "--start-offset", fmt.Sprint(startOffset))
			}
			if keyword != "" {
				argv = append(argv, "--keyword", keyword)
			}
			if retryGrowthSkipped {
				argv = append(argv, "--retry-growth-skipped")
			}
			if retryFindTabFailures {
				argv = append(argv, "--retry-find-tab-failures")
			}
			if retryXFEmpty {
				argv = append(argv, "--retry-xf-empty")
			}

			run := exec.Command(nodePath, argv...)
			run.Stderr = os.Stderr
			var stdout bytes.Buffer
			run.Stdout = &stdout
			if err := run.Run(); err != nil {
				if stdout.Len() > 0 && json.Valid(stdout.Bytes()) {
					fmt.Print(stdout.String())
					os.Exit(1)
				}
				fail("xf_cloud_failed", err)
			}
			if stdout.Len() == 0 {
				fail("xf_cloud_failed", fmt.Errorf("empty output from %s", scriptPath))
			}
			if !json.Valid(stdout.Bytes()) {
				fail("xf_cloud_failed", fmt.Errorf("non-JSON output from %s: %s", scriptPath, stdout.String()))
			}
			fmt.Print(stdout.String())
		},
	}

	xfCloudCmd.Flags().StringVar(&nodePath, "node", nodePath, "node 可执行文件路径")
	xfCloudCmd.Flags().StringVar(&scriptPath, "script", "", "晓风云库批处理脚本路径；默认自动从 doudian-biz 同目录查找")
	xfCloudCmd.Flags().StringVar(&baseToken, "base-token", baseToken, "飞书多维表格 base/app token")
	xfCloudCmd.Flags().StringVar(&tableID, "table-id", tableID, "飞书数据表 ID")
	xfCloudCmd.Flags().StringVar(&viewID, "view-id", viewID, "飞书视图 ID")
	xfCloudCmd.Flags().StringVar(&statusField, "status-field", statusField, "回写状态字段名")
	xfCloudCmd.Flags().StringVar(&larkCLI, "lark-cli", larkCLI, "lark-cli 路径，需有用户授权")
	xfCloudCmd.Flags().StringVar(&doudianSession, "doudian-session", doudianSession, "抖店商机中心 OpenBridge session 名")
	xfCloudCmd.Flags().StringVar(&xfSession, "xf-session", xfSession, "晓风页面 OpenBridge session 名")
	xfCloudCmd.Flags().StringVar(&relationID, "relation-id", relationID, "晓风 iframe relationId，当前为店铺 ID")
	xfCloudCmd.Flags().StringVar(&plugID, "plug-id", plugID, "晓风插件 ID")
	xfCloudCmd.Flags().StringVar(&xfBaseURL, "xf-base-url", xfBaseURL, "晓风截流页面基础 URL")
	xfCloudCmd.Flags().StringVar(&stateFile, "state-file", stateFile, "本地处理日志 JSONL 路径")
	xfCloudCmd.Flags().StringVar(&keyword, "keyword", "", "只处理指定关键词")
	xfCloudCmd.Flags().IntVar(&limit, "limit", 0, "最多处理多少条，0 表示不限制")
	xfCloudCmd.Flags().IntVar(&startOffset, "start-offset", 0, "从飞书记录偏移位置开始读取")
	xfCloudCmd.Flags().BoolVar(&retryGrowthSkipped, "retry-growth-skipped", false, "重跑旧版按成交增速跳过的记录")
	xfCloudCmd.Flags().BoolVar(&retryFindTabFailures, "retry-find-tab-failures", false, "重跑 find_tab 临时失败的记录")
	xfCloudCmd.Flags().BoolVar(&retryXFEmpty, "retry-xf-empty", false, "重跑晓风页面未加载出货源列表的记录")

	rootCmd.AddCommand(xfCloudCmd)
}

func defaultXFCloudScriptPath() (string, error) {
	exe, err := os.Executable()
	if err != nil {
		return "", err
	}
	if resolved, err := filepath.EvalSymlinks(exe); err == nil {
		exe = resolved
	}
	candidates := []string{
		filepath.Join(filepath.Dir(exe), "scripts", "process_feishu_xf_cloud.mjs"),
	}
	if wd, err := os.Getwd(); err == nil {
		candidates = append(candidates, filepath.Join(wd, "scripts", "process_feishu_xf_cloud.mjs"))
	}
	for _, candidate := range candidates {
		if _, err := os.Stat(candidate); err == nil {
			return candidate, nil
		}
	}
	return "", fmt.Errorf("process_feishu_xf_cloud.mjs not found near %s", exe)
}
