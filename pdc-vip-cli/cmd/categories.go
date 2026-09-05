package cmd

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"pdc-cli/pdc"
)

func init() {
	var includeDisabled bool
	var asTree bool
	c := &cobra.Command{
		Use:           "categories",
		Short:         "商品分类树（默认剔除停用项；与页面级联选择器一致）",
		SilenceUsage:  true,
		SilenceErrors: true,
		Run: func(cmd *cobra.Command, args []string) {
			api := connect()
			roots, err := api.Categories(includeDisabled)
			if err != nil {
				fail(err)
			}
			if asTree {
				printTree(roots, 0)
				return
			}
			printJSON(roots)
		},
	}
	c.Flags().BoolVar(&includeDisabled, "all", false, "包含停用(status=1)的类目")
	c.Flags().BoolVar(&asTree, "tree", false, "以缩进树形打印(含 categoryId)而非 JSON")
	rootCmd.AddCommand(c)
}

func printTree(cats []pdc.Category, depth int) {
	for _, c := range cats {
		indent := ""
		for i := 0; i < depth; i++ {
			indent += "  "
		}
		flag := ""
		if c.Disabled() {
			flag = " [停用]"
		}
		fmt.Fprintf(os.Stdout, "%s%-8d %s%s\n", indent, c.CategoryID, c.Name, flag)
		printTree(c.Children, depth+1)
	}
}
