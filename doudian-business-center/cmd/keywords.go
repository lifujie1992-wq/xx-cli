package cmd

import (
	"fmt"
	"os"
	"strings"

	"github.com/spf13/cobra"

	"doudian-business-center-cli/browser"
	"doudian-business-center-cli/doudian"
	"doudian-business-center-cli/feishu"
	"doudian-business-center-cli/output"
)

func init() {
	var (
		opt            = doudian.DefaultOptions()
		tags           = "全网热卖,热度高,成交增速快"
		tagIDs         string
		brandBlocklist string
		outDir         = "output"
		writeFeishu    bool
		feishuCLI      = feishu.DefaultCLIPath
		feishuAppToken = feishu.DefaultAppToken
		feishuTable    = "抖店商机关键词100"
		feishuTableID  string
		feishuColumns  = "compact"
		feishuDryRun   bool
	)

	keywordsCmd := &cobra.Command{
		Use:           "keywords",
		Short:         "抓取搜索次数大于阈值的商机关键词，并可写入飞书多维表格",
		SilenceUsage:  true,
		SilenceErrors: true,
		Run: func(cmd *cobra.Command, args []string) {
			ids, err := doudian.ParseTagIDs(tags, tagIDs)
			if err != nil {
				fail("bad_tags", err)
			}
			opt.TagIDs = ids
			opt.BrandBlocklist = doudian.MergeBrandBlocklist(brandBlocklist)
			opt.Session = strings.TrimSpace(opt.Session)
			if opt.Session == "" {
				opt.Session = doudian.DefaultSession
			}

			client := browser.NewClient(opt.Session)
			fmt.Fprintf(os.Stderr, "抓取抖店商机关键词：tags=%v min_search>%d limit=%d page_size=%d\n", opt.TagIDs, opt.MinSearch, opt.Limit, opt.PageSize)
			runRes, err := doudian.Run(client, opt, outDir)
			if err != nil {
				if strings.Contains(err.Error(), "daemon unreachable") {
					fail("daemon_unreachable", fmt.Errorf("%w (检查 curl -s http://127.0.0.1:10088/health)", err))
				}
				fail("collect_failed", err)
			}
			fmt.Fprintf(os.Stderr, "已抓取 %d 条，扫描 %d 行/%d 页，品牌词剔除 %d 条\n",
				runRes.Result.CollectedCount, runRes.Result.RowsScanned, runRes.Result.PagesScanned, runRes.Result.RejectedBrandCount)

			payload := map[string]any{
				"options": runRes.Options,
				"result":  runRes.Result,
				"exports": map[string]string{
					"json": runRes.JSONPath,
					"tsv":  runRes.TSVPath,
					"csv":  runRes.CSVPath,
				},
			}

			if writeFeishu || feishuDryRun || feishuTableID != "" {
				records, fieldTypes, err := doudian.Records(runRes.Result.Items, feishuColumns)
				if err != nil {
					fail("feishu_records_failed", err)
				}
				fmt.Fprintf(os.Stderr, "写入飞书：table=%q table_id=%q columns=%s records=%d\n", feishuTable, feishuTableID, feishuColumns, len(records))
				fres, err := feishu.WriteRecords(feishu.Options{
					CLIPath:   feishuCLI,
					AppToken:  feishuAppToken,
					TableName: feishuTable,
					TableID:   feishuTableID,
					Columns:   feishuColumns,
					DryRun:    feishuDryRun,
				}, records, fieldTypes)
				if err != nil {
					fail("feishu_write_failed", err)
				}
				payload["feishu"] = fres
			}

			output.Success(payload)
		},
	}

	keywordsCmd.Flags().StringVar(&opt.URL, "url", opt.URL, "抖店商机中心 URL")
	keywordsCmd.Flags().StringVar(&opt.Session, "session", opt.Session, "OpenBridge session 名")
	keywordsCmd.Flags().BoolVar(&opt.OpenNewTab, "open-new-tab", opt.OpenNewTab, "未找到商机中心标签页时，在新标签页打开")
	keywordsCmd.Flags().BoolVar(&opt.RequireFindFirst, "require-existing-tab", opt.RequireFindFirst, "必须复用已打开的商机中心标签页，不自动导航")
	keywordsCmd.Flags().IntVar(&opt.Limit, "limit", opt.Limit, "收集数量")
	keywordsCmd.Flags().Int64Var(&opt.MinSearch, "min-search", opt.MinSearch, "搜索次数必须大于该值")
	keywordsCmd.Flags().IntVar(&opt.PageSize, "page-size", opt.PageSize, "每页请求数量，最大 100")
	keywordsCmd.Flags().IntVar(&opt.MaxPages, "max-pages", opt.MaxPages, "最多扫描页数，0 表示直到收满或无数据")
	keywordsCmd.Flags().StringVar(&tags, "tags", tags, "推荐理由标签名，逗号分隔")
	keywordsCmd.Flags().StringVar(&tagIDs, "tag-ids", "", "推荐理由标签 ID，逗号分隔；设置后覆盖 --tags")
	keywordsCmd.Flags().StringVar(&opt.Query, "query", opt.Query, "关键词搜索条件，对应 condition.clue_info")
	keywordsCmd.Flags().BoolVar(&opt.ExcludeBrands, "exclude-brands", opt.ExcludeBrands, "剔除有品牌字段或命中品牌黑名单的词")
	keywordsCmd.Flags().StringVar(&brandBlocklist, "brand-blocklist", "", "追加品牌黑名单，逗号分隔")
	keywordsCmd.Flags().StringVar(&opt.SortField, "sort-field", opt.SortField, "排序字段，如 MATCH_DEGREE/TRADING_AMOUNT/PAY_AMOUNT_RATE/DEMAND_SUPPLY_RATE")
	keywordsCmd.Flags().IntVar(&opt.SortDirection, "sort-direction", opt.SortDirection, "排序方向：1=降序，0=升序")
	keywordsCmd.Flags().StringVar(&outDir, "out-dir", outDir, "导出目录")

	keywordsCmd.Flags().BoolVar(&writeFeishu, "feishu", false, "写入飞书多维表格")
	keywordsCmd.Flags().StringVar(&feishuCLI, "feishu-cli", feishuCLI, "feishu-cli 路径")
	keywordsCmd.Flags().StringVar(&feishuAppToken, "feishu-app-token", feishuAppToken, "飞书多维表格 app_token/base token")
	keywordsCmd.Flags().StringVar(&feishuTable, "feishu-table", feishuTable, "新建飞书数据表名称")
	keywordsCmd.Flags().StringVar(&feishuTableID, "feishu-table-id", "", "写入已有数据表 ID；为空则新建数据表")
	keywordsCmd.Flags().StringVar(&feishuColumns, "feishu-columns", feishuColumns, "飞书列模式：compact 或 full")
	keywordsCmd.Flags().BoolVar(&feishuDryRun, "feishu-dry-run", false, "只展示飞书写入计划，不调用 feishu-cli")

	rootCmd.AddCommand(keywordsCmd)
}

func fail(code string, err error) {
	output.Error(code, err.Error())
	os.Exit(1)
}
