package cmd

import (
	"fmt"
	"os"
	"strings"

	"github.com/spf13/cobra"

	"doudian-business-center-cli/browser"
	"doudian-business-center-cli/doudian"
	"doudian-business-center-cli/output"
)

func init() {
	var (
		opt         = doudian.DefaultOptions()
		tags        string
		tagIDs      string
		fillUI      = true
		clickButton = true
		waitMs      = 800
	)
	opt.URL = doudian.DefaultSearchURL
	opt.Limit = 20
	opt.MinSearch = 0
	opt.TagIDs = nil
	opt.ExcludeBrands = false

	searchCmd := &cobra.Command{
		Use:           "search <关键词>",
		Short:         "在商机中心搜索框输入关键词并搜索",
		Args:          cobra.MinimumNArgs(1),
		SilenceUsage:  true,
		SilenceErrors: true,
		Run: func(cmd *cobra.Command, args []string) {
			query := strings.TrimSpace(strings.Join(args, " "))
			if query == "" {
				fail("bad_query", fmt.Errorf("query is required"))
			}
			opt.Query = query
			ids, err := parseOptionalTagIDs(tags, tagIDs)
			if err != nil {
				fail("bad_tags", err)
			}
			opt.TagIDs = ids
			opt.Session = strings.TrimSpace(opt.Session)
			if opt.Session == "" {
				opt.Session = doudian.DefaultSession
			}

			client := browser.NewClient(opt.Session)
			fmt.Fprintf(os.Stderr, "搜索抖店商机：query=%q tags=%v limit=%d min_search>%d\n", opt.Query, opt.TagIDs, opt.Limit, opt.MinSearch)
			res, err := doudian.Search(client, opt, fillUI, clickButton, waitMs)
			if err != nil {
				if strings.Contains(err.Error(), "daemon unreachable") {
					fail("daemon_unreachable", fmt.Errorf("%w (检查 curl -s http://127.0.0.1:10088/health)", err))
				}
				fail("search_failed", err)
			}
			fmt.Fprintf(os.Stderr, "搜索完成：输入框=%q，接口返回 %d 条，扫描 %d 行/%d 页\n",
				res.UI.InputValue, res.Result.CollectedCount, res.Result.RowsScanned, res.Result.PagesScanned)
			output.Success(res)
		},
	}

	searchCmd.Flags().StringVar(&opt.URL, "url", opt.URL, "抖店商机中心 URL")
	searchCmd.Flags().StringVar(&opt.Session, "session", opt.Session, "OpenBridge session 名")
	searchCmd.Flags().BoolVar(&opt.OpenNewTab, "open-new-tab", opt.OpenNewTab, "未找到商机中心标签页时，在新标签页打开")
	searchCmd.Flags().BoolVar(&opt.RequireFindFirst, "require-existing-tab", opt.RequireFindFirst, "必须复用已打开的商机中心标签页，不自动导航")
	searchCmd.Flags().IntVar(&opt.Limit, "limit", opt.Limit, "返回数量")
	searchCmd.Flags().IntVar(&opt.PageSize, "page-size", opt.PageSize, "每页请求数量，最大 100")
	searchCmd.Flags().Int64Var(&opt.MinSearch, "min-search", opt.MinSearch, "搜索次数必须大于该值，0 表示不过滤")
	searchCmd.Flags().StringVar(&tags, "tags", tags, "推荐理由标签名，逗号分隔；默认不限制")
	searchCmd.Flags().StringVar(&tagIDs, "tag-ids", "", "推荐理由标签 ID，逗号分隔；设置后覆盖 --tags")
	searchCmd.Flags().BoolVar(&opt.ExcludeBrands, "exclude-brands", opt.ExcludeBrands, "剔除有品牌字段或命中品牌黑名单的词")
	searchCmd.Flags().StringVar(&opt.SortField, "sort-field", opt.SortField, "排序字段，如 MATCH_DEGREE/TRADING_AMOUNT/PAY_AMOUNT_RATE/DEMAND_SUPPLY_RATE")
	searchCmd.Flags().IntVar(&opt.SortDirection, "sort-direction", opt.SortDirection, "排序方向：1=降序，0=升序")
	searchCmd.Flags().BoolVar(&fillUI, "fill-ui", fillUI, "把关键词填入页面搜索框")
	searchCmd.Flags().BoolVar(&clickButton, "click-button", clickButton, "填入后点击页面搜索按钮")
	searchCmd.Flags().IntVar(&waitMs, "wait-ms", waitMs, "点击后等待页面反应的毫秒数")

	rootCmd.AddCommand(searchCmd)
}

func parseOptionalTagIDs(tags, tagIDs string) ([]int, error) {
	if strings.TrimSpace(tagIDs) == "" && strings.TrimSpace(tags) == "" {
		return nil, nil
	}
	return doudian.ParseTagIDs(tags, tagIDs)
}
