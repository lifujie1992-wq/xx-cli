package cmd

import (
	"encoding/csv"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"woda-aftersale-cli/woda"
)

func exportRefundOnly(result *woda.ListResult, format string, outPath string) (string, error) {
	format = strings.ToLower(strings.TrimSpace(format))
	if format == "markdown" {
		format = "md"
	}
	if format == "" {
		format = "csv"
	}
	if format != "csv" && format != "json" && format != "md" {
		return "", fmt.Errorf("unsupported export format %q; use csv, json, or md", format)
	}
	if strings.TrimSpace(outPath) == "" {
		outPath = filepath.Join("~/Downloads", fmt.Sprintf("woda_refund_only_%s.%s", time.Now().Format("20060102_150405"), format))
	}
	abs, err := filepath.Abs(outPath)
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(filepath.Dir(abs), 0755); err != nil {
		return "", err
	}

	switch format {
	case "csv":
		if err := writeRefundOnlyCSV(abs, result.Orders); err != nil {
			return "", err
		}
	case "json":
		if err := writeRefundOnlyJSON(abs, result); err != nil {
			return "", err
		}
	case "md":
		if err := writeRefundOnlyMarkdown(abs, result); err != nil {
			return "", err
		}
	}
	return abs, nil
}

func writeRefundOnlyCSV(path string, orders []woda.RefundOnlyOrder) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	// UTF-8 BOM for Excel/Numbers Chinese compatibility.
	if _, err := f.Write([]byte{0xEF, 0xBB, 0xBF}); err != nil {
		return err
	}
	w := csv.NewWriter(f)
	header := []string{"序号", "剩余处理时间", "店铺", "售后单号", "订单号", "件数", "商品", "规格", "售后退款金额", "售后类型", "售后状态", "售后原因", "申请说明", "退货物流", "发货物流", "可操作", "申请时间"}
	if err := w.Write(header); err != nil {
		return err
	}
	for _, o := range orders {
		record := []string{o.Index, o.RemainTime, o.Shop, o.AftersaleID, o.OrderID, o.ItemCount, o.Product, o.Sku, o.Amount, o.AftersaleType, o.AftersaleStatus, o.Reason, o.ReasonDetail, o.ReturnLogistics, o.ShippingLogistics, strings.Join(o.AvailableActions, "/"), o.ApplyTime}
		if err := w.Write(record); err != nil {
			return err
		}
	}
	w.Flush()
	return w.Error()
}

func writeRefundOnlyJSON(path string, result *woda.ListResult) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	enc := json.NewEncoder(f)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", "  ")
	return enc.Encode(result)
}

func writeRefundOnlyMarkdown(path string, result *woda.ListResult) error {
	var b strings.Builder
	fmt.Fprintf(&b, "# 我打抖音仅退款订单\n\n")
	fmt.Fprintf(&b, "页面：%s\n\n", result.URL)
	fmt.Fprintf(&b, "仅退款数量：%d\n\n", len(result.Orders))
	b.WriteString("| 序号 | 店铺 | 售后单号 | 订单号 | 金额 | 状态 | 原因 | 申请时间 | 发货物流 |\n")
	b.WriteString("|---|---|---|---|---:|---|---|---|---|\n")
	for _, o := range result.Orders {
		fmt.Fprintf(&b, "| %s | %s | %s | %s | %s | %s/%s | %s %s | %s | %s |\n",
			mdEscape(o.Index), mdEscape(o.Shop), mdEscape(o.AftersaleID), mdEscape(o.OrderID), mdEscape(o.Amount),
			mdEscape(o.AftersaleType), mdEscape(o.AftersaleStatus), mdEscape(o.Reason), mdEscape(o.ReasonDetail), mdEscape(o.ApplyTime), mdEscape(o.ShippingLogistics))
	}
	return os.WriteFile(path, []byte(b.String()), 0644)
}

func mdEscape(s string) string {
	s = strings.ReplaceAll(s, "|", "\\|")
	s = strings.ReplaceAll(s, "\n", " ")
	return s
}
