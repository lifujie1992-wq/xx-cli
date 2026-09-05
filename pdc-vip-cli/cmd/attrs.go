package cmd

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"pdc-cli/pdc"
)

func init() {
	var requiredOnly bool
	var asTable bool
	c := &cobra.Command{
		Use:           "attrs <categoryId>",
		Short:         "拉某叶子类目的属性目录（attributeId + 可选项 optionId，给 agent 映射用）",
		Args:          cobra.ExactArgs(1),
		SilenceUsage:  true,
		SilenceErrors: true,
		Run: func(cmd *cobra.Command, args []string) {
			api := connect()
			defs, err := api.AttributeCatalog(atoiOrFail(args[0]))
			if err != nil {
				fail(err)
			}
			if requiredOnly {
				var f []pdc.AttrDef
				for _, d := range defs {
					if d.Required() {
						f = append(f, d)
					}
				}
				defs = f
			}
			if asTable {
				for _, d := range defs {
					req := " "
					if d.Required() {
						req = "*"
					}
					opts := ""
					for i, o := range d.OptionFormat.AttrOptsList {
						if i >= 6 {
							opts += " …"
							break
						}
						opts += fmt.Sprintf(" %d:%s", o.OptionID, o.Name)
					}
					dt := map[int]string{0: "文本", 2: "枚举", 6: "图片"}[d.DataType]
					fmt.Fprintf(os.Stdout, "%s %-7d %-3s %-16s%s\n", req, d.AttributeID, dt, d.Name, opts)
				}
				return
			}
			printJSON(defs)
		},
	}
	c.Flags().BoolVar(&requiredOnly, "required", false, "只看必填属性")
	c.Flags().BoolVar(&asTable, "table", false, "表格速览（* 标必填，附前几个 optionId）")
	rootCmd.AddCommand(c)
}
