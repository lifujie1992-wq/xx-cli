package doudian

import (
	"encoding/csv"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"

	"doudian-business-center-cli/browser"
)

const (
	DefaultURL       = "https://fxg.jinritemai.com/ffa/bu/NewBusinessCenter"
	DefaultSearchURL = "https://fxg.jinritemai.com/ffa/bu/NewBusinessCenter?source=business_center"
	DefaultSession   = "doudian-business-center"
	DefaultPageSize  = 100
)

var TagIDs = map[string]int{
	"全网热卖":   35,
	"热度高":    31,
	"成交增速快":  32,
	"平台缺货":   30,
	"应季爆发":   33,
	"高扶持甄选品": 34,
	"中小商易爆单": 36,
	"投广易爆品":  37,
	"爆款货源":   38,
}

var DefaultBrandBlocklist = []string{
	"耐克", "nike", "阿迪", "adidas", "安踏", "李宁", "特步", "361", "鸿星尔克",
	"乔丹", "匹克", "puma", "new balance", "asics", "vans", "converse", "fila",
	"crocs", "迪卡侬", "skechers", "斯凯奇", "回力", "百丽", "达芙妮", "shoebox",
	"斐乐", "匡威", "亚瑟士", "彪马", "万斯", "nb", "爱威亚", "avia", "matnut",
	"京泰源", "胖东来",
}

type Options struct {
	URL              string   `json:"url"`
	Session          string   `json:"session"`
	Limit            int      `json:"limit"`
	MinSearch        int64    `json:"min_search"`
	PageSize         int      `json:"page_size"`
	MaxPages         int      `json:"max_pages"`
	TagIDs           []int    `json:"tag_ids"`
	Query            string   `json:"query"`
	ExcludeBrands    bool     `json:"exclude_brands"`
	BrandBlocklist   []string `json:"brand_blocklist"`
	SortField        string   `json:"sort_field"`
	SortDirection    int      `json:"sort_direction"`
	IncludeHotSales  bool     `json:"include_hot_sales_products"`
	ShowSupplyLink   bool     `json:"show_new_supply_link"`
	HitClueLabelExt  bool     `json:"hit_clue_label_ext"`
	ClueTypeNew      int      `json:"clue_type_new"`
	TerminalType     int      `json:"terminal_type"`
	Source           string   `json:"source"`
	OpenNewTab       bool     `json:"open_new_tab"`
	RequireFindFirst bool     `json:"require_find_first"`
}

type Keyword struct {
	Keyword                string  `json:"keyword"`
	SearchPVCnt            int64   `json:"search_pv_cnt"`
	SearchPVCntRange       string  `json:"search_pv_cnt_range"`
	CategoryPath           string  `json:"category_path"`
	CategoryName           string  `json:"category_name"`
	ClueID                 string  `json:"clue_id"`
	Labels                 string  `json:"labels"`
	Profits                string  `json:"profits"`
	PayAmountRange         string  `json:"pay_amount_range"`
	PayAmountGrowth30dRate float64 `json:"pay_amount_growth_30d_rate"`
	SearchHeat             int64   `json:"search_heat"`
	DemandHeatRange        string  `json:"demand_heat_range"`
	DemandSupplyRate       float64 `json:"demand_supply_rate"`
	GoodsSupplyPlatforms   string  `json:"goods_supply_platforms"`
	BrandID                string  `json:"brand_id"`
	BrandName              string  `json:"brand_name"`
	BrandNameEN            string  `json:"brand_name_en"`
	Page                   int     `json:"page"`
	RawIndex               int     `json:"raw_index"`
	RejectedBrandMatch     string  `json:"-"`
}

type BrandReject struct {
	Keyword string `json:"keyword"`
	Reason  string `json:"reason"`
}

type Result struct {
	Total              int           `json:"total"`
	PagesScanned       int           `json:"pages_scanned"`
	RowsScanned        int           `json:"rows_scanned"`
	CollectedCount     int           `json:"collected_count"`
	RejectedBrandCount int           `json:"rejected_brand_count"`
	RejectedBrands     []BrandReject `json:"rejected_brands,omitempty"`
	Items              []Keyword     `json:"items"`
}

type RunResult struct {
	Options  Options `json:"options"`
	Result   Result  `json:"result"`
	JSONPath string  `json:"json_path"`
	TSVPath  string  `json:"tsv_path"`
	CSVPath  string  `json:"csv_path"`
}

func DefaultOptions() Options {
	return Options{
		URL:              DefaultURL,
		Session:          DefaultSession,
		Limit:            100,
		MinSearch:        10000,
		PageSize:         DefaultPageSize,
		MaxPages:         0,
		TagIDs:           []int{35, 31, 32},
		ExcludeBrands:    true,
		BrandBlocklist:   append([]string{}, DefaultBrandBlocklist...),
		SortField:        "MATCH_DEGREE",
		SortDirection:    1,
		IncludeHotSales:  true,
		ShowSupplyLink:   true,
		HitClueLabelExt:  true,
		ClueTypeNew:      11,
		TerminalType:     0,
		Source:           "business_center",
		OpenNewTab:       true,
		RequireFindFirst: true,
	}
}

func ParseTagIDs(tagNames, tagIDs string) ([]int, error) {
	if strings.TrimSpace(tagIDs) != "" {
		return parseInts(tagIDs)
	}
	if strings.TrimSpace(tagNames) == "" {
		return []int{35, 31, 32}, nil
	}
	var ids []int
	for _, part := range splitList(tagNames) {
		id, ok := TagIDs[part]
		if !ok {
			return nil, fmt.Errorf("unknown tag %q; use --tag-ids for custom IDs", part)
		}
		ids = append(ids, id)
	}
	return ids, nil
}

func MergeBrandBlocklist(extra string) []string {
	items := append([]string{}, DefaultBrandBlocklist...)
	items = append(items, splitList(extra)...)
	seen := map[string]bool{}
	var out []string
	for _, item := range items {
		item = strings.TrimSpace(item)
		if item == "" {
			continue
		}
		key := strings.ToLower(item)
		if seen[key] {
			continue
		}
		seen[key] = true
		out = append(out, item)
	}
	return out
}

func Collect(c *browser.Client, opt Options) (*Result, error) {
	if opt.URL == "" {
		opt.URL = DefaultURL
	}
	if opt.PageSize <= 0 || opt.PageSize > 100 {
		opt.PageSize = DefaultPageSize
	}
	if opt.Limit <= 0 {
		opt.Limit = 100
	}
	if opt.ClueTypeNew == 0 {
		opt.ClueTypeNew = 11
	}
	if opt.Source == "" {
		opt.Source = "business_center"
	}
	if opt.SortField == "" {
		opt.SortField = "MATCH_DEGREE"
	}

	if err := ensureBusinessCenter(c, opt); err != nil {
		return nil, err
	}

	return collectCurrentPage(c, opt)
}

func Run(c *browser.Client, opt Options, outDir string) (*RunResult, error) {
	res, err := Collect(c, opt)
	if err != nil {
		return nil, err
	}
	jsonPath, tsvPath, csvPath, err := WriteExports(outDir, res.Items)
	if err != nil {
		return nil, err
	}
	return &RunResult{Options: opt, Result: *res, JSONPath: jsonPath, TSVPath: tsvPath, CSVPath: csvPath}, nil
}

func WriteExports(outDir string, items []Keyword) (string, string, string, error) {
	if outDir == "" {
		outDir = "output"
	}
	if err := os.MkdirAll(outDir, 0o755); err != nil {
		return "", "", "", err
	}
	stamp := time.Now().Format("20060102_150405")
	jsonPath := filepath.Join(outDir, "doudian_keywords_"+stamp+".json")
	tsvPath := filepath.Join(outDir, "doudian_keywords_"+stamp+".tsv")
	csvPath := filepath.Join(outDir, "doudian_keywords_"+stamp+".csv")

	j, err := json.MarshalIndent(items, "", "  ")
	if err != nil {
		return "", "", "", err
	}
	if err := os.WriteFile(jsonPath, j, 0o644); err != nil {
		return "", "", "", err
	}
	if err := writeDelimited(tsvPath, items, '\t'); err != nil {
		return "", "", "", err
	}
	if err := writeDelimited(csvPath, items, ','); err != nil {
		return "", "", "", err
	}
	return jsonPath, tsvPath, csvPath, nil
}

func CompactFeishuRecord(item Keyword) map[string]any {
	return map[string]any{
		"关键词":    item.Keyword,
		"搜索次数":   item.SearchPVCnt,
		"搜索次数区间": item.SearchPVCntRange,
		"类目路径":   item.CategoryPath,
		"标签":     item.Labels,
	}
}

func FullFeishuRecord(item Keyword) map[string]any {
	return map[string]any{
		"关键词":     item.Keyword,
		"搜索次数":    item.SearchPVCnt,
		"搜索次数区间":  item.SearchPVCntRange,
		"类目路径":    item.CategoryPath,
		"类目":      item.CategoryName,
		"线索ID":    item.ClueID,
		"标签":      item.Labels,
		"权益":      item.Profits,
		"用户支付金额":  item.PayAmountRange,
		"成交增速30d": item.PayAmountGrowth30dRate,
		"需求热度":    item.SearchHeat,
		"需求热度区间":  item.DemandHeatRange,
		"供需比":     item.DemandSupplyRate,
		"代发货源平台":  item.GoodsSupplyPlatforms,
	}
}

func CompactFieldTypes() map[string]int {
	return map[string]int{"关键词": 1, "搜索次数": 2, "搜索次数区间": 1, "类目路径": 1, "标签": 1}
}

func FullFieldTypes() map[string]int {
	m := CompactFieldTypes()
	for _, name := range []string{"类目", "线索ID", "权益", "用户支付金额", "需求热度区间", "代发货源平台"} {
		m[name] = 1
	}
	for _, name := range []string{"成交增速30d", "需求热度", "供需比"} {
		m[name] = 2
	}
	return m
}

func Records(items []Keyword, columns string) ([]map[string]any, map[string]int, error) {
	var records []map[string]any
	switch columns {
	case "", "compact":
		for _, item := range items {
			records = append(records, CompactFeishuRecord(item))
		}
		return records, CompactFieldTypes(), nil
	case "full":
		for _, item := range items {
			records = append(records, FullFeishuRecord(item))
		}
		return records, FullFieldTypes(), nil
	default:
		return nil, nil, fmt.Errorf("unknown columns mode %q; use compact or full", columns)
	}
}

func ensureBusinessCenter(c *browser.Client, opt Options) error {
	if opt.RequireFindFirst {
		err := c.FindTab("https://fxg.jinritemai.com/ffa/bu/NewBusinessCenter", false)
		if err == nil {
			return nil
		}
		return fmt.Errorf("business center tab not found: %w", err)
	}
	if err := c.Navigate(opt.URL, opt.OpenNewTab); err != nil {
		return err
	}
	time.Sleep(2500 * time.Millisecond)
	return nil
}

func collectScript(opt Options) (string, error) {
	cfg, err := json.Marshal(opt)
	if err != nil {
		return "", err
	}
	return fmt.Sprintf(`(async function(){
  const cfg = %s;
  const endpoint = "/api/commop/business_chance_center/clue/common/real_time_list";
  const num = (v) => {
    if (v === null || v === undefined || v === "") return 0;
    if (typeof v === "number") return Number.isFinite(v) ? v : 0;
    const s = String(v).replace(/,/g, "").trim();
    const n = Number(s);
    return Number.isFinite(n) ? n : 0;
  };
  const text = (v) => {
    if (v === null || v === undefined) return "";
    if (Array.isArray(v)) return v.map(text).filter(Boolean).join("、");
    if (typeof v === "object") return v.label_name || v.profit_name || v.name || v.text || v.value || "";
    return String(v);
  };
  const joinNames = (arr, keys) => {
    if (!Array.isArray(arr)) return "";
    return arr.map(x => {
      for (const k of keys) if (x && x[k] !== undefined && x[k] !== null && String(x[k]).trim() !== "") return String(x[k]).trim();
      return text(x);
    }).filter(Boolean).join("、");
  };
  const categoryPath = (d) => {
    if (Array.isArray(d.category_path)) return d.category_path.filter(Boolean).join(" > ");
    const parts = [d.first_name, d.second_name, d.third_name, d.fourth_name].filter(Boolean);
    return parts.join(" > ");
  };
  const brandList = (cfg.brand_blocklist || []).map(x => String(x).toLowerCase()).filter(Boolean);
  const brandReason = (keyword, d) => {
    const brandID = d.brand_id ?? d.brandID ?? "";
    const brandName = String(d.brand_name || d.brandName || "").trim();
    const brandNameEN = String(d.brand_name_en || d.brandNameEn || "").trim();
    if (brandID !== "" && String(brandID) !== "0") return "brand_id=" + brandID;
    if (brandName) return "brand_name=" + brandName;
    if (brandNameEN) return "brand_name_en=" + brandNameEN;
    const lower = String(keyword || "").toLowerCase();
    const hit = brandList.find(b => lower.includes(b));
    return hit ? "keyword_contains=" + hit : "";
  };
  const out = [];
  const rejected = [];
  let rowsScanned = 0;
  let total = 0;
  let page = 1;
  const maxPages = Number(cfg.max_pages || 0);
  while (out.length < Number(cfg.limit || 100)) {
    if (maxPages > 0 && page > maxPages) break;
    const condition = {
      tag_id_list: cfg.tag_ids || [],
      hit_clue_label_ext: cfg.hit_clue_label_ext !== false,
      show_new_supply_link: cfg.show_new_supply_link !== false,
      include_hot_sales_products: cfg.include_hot_sales_products !== false,
      sort: {sort_direction: cfg.sort_direction ?? 1, sort_field: cfg.sort_field || "MATCH_DEGREE"}
    };
    if (cfg.query) condition.clue_info = cfg.query;
    const payload = {
      condition,
      clue_type: "",
      clue_type_new: cfg.clue_type_new || 11,
      page: {current: page, page_size: cfg.page_size || 100},
      terminal_type: cfg.terminal_type ?? 0,
      source: cfg.source || "business_center"
    };
    const res = await fetch(endpoint, {
      method: "POST",
      credentials: "include",
      headers: {"content-type": "application/json"},
      body: JSON.stringify(payload)
    });
    const json = await res.json();
    if (json.code !== 0) throw new Error("real_time_list code=" + json.code + " msg=" + (json.msg || json.message || ""));
    const list = Array.isArray(json.data) ? json.data : (json.data && (json.data.list || json.data.items || json.data.data)) || [];
    total = Number(json.total ?? (json.data && json.data.total) ?? total ?? 0);
    if (!Array.isArray(list) || list.length === 0) break;
    rowsScanned += list.length;
    for (let i = 0; i < list.length && out.length < Number(cfg.limit || 100); i++) {
      const row = list[i] || {};
      const d = row.clue_detail || row.clueDetail || {};
      const ind = row.clue_indicator || row.clueIndicator || {};
      const card = row.query_clue_card_info || row.queryClueCardInfo || {};
      const keyword = String(d.name || d.clue_name || row.name || "").trim();
      if (!keyword) continue;
      const searchCnt = num(ind.search_pv_cnt ?? ind.searchPvCnt ?? row.search_pv_cnt ?? card.search_pv_cnt ?? 0);
      const minSearch = cfg.min_search ?? 10000;
      if (searchCnt <= Number(minSearch)) continue;
      if (cfg.exclude_brands !== false) {
        const reason = brandReason(keyword, d);
        if (reason) {
          rejected.push({keyword, reason});
          continue;
        }
      }
      const labels = joinNames(d.clue_label_list || d.label_list || row.clue_label_list, ["label_name", "name"]);
      const profits = joinNames(d.profit_info_list || row.profit_info_list, ["profit_name", "name"]);
      const goodsPlatforms = (card.goods_supply_platform_list || row.goods_supply_platform_list || []).map(x => String(x)).join(",");
      out.push({
        keyword,
        search_pv_cnt: Math.trunc(searchCnt),
        search_pv_cnt_range: String(ind.search_pv_cnt_range || ind.searchPvCntRange || row.search_pv_cnt_range || ""),
        category_path: categoryPath(d),
        category_name: String(d.third_name || d.second_name || d.first_name || ""),
        clue_id: String(d.clue_id || d.clueId || ""),
        labels,
        profits,
        pay_amount_range: String(ind.pay_amount_ind_range || ind.payAmountIndRange || ""),
        pay_amount_growth_30d_rate: num(ind.pay_amount_ind_30d_rate ?? ind.payAmountInd30dRate ?? 0),
        search_heat: Math.trunc(num(card.search_popularity ?? card.search_heat ?? 0)),
        demand_heat_range: String(card.search_popularity_range || card.demand_heat_range || ""),
        demand_supply_rate: num(card.demand_supply_rate ?? 0),
        goods_supply_platforms: goodsPlatforms,
        brand_id: String(d.brand_id ?? d.brandID ?? ""),
        brand_name: String(d.brand_name || d.brandName || ""),
        brand_name_en: String(d.brand_name_en || d.brandNameEn || ""),
        page,
        raw_index: i
      });
    }
    page++;
  }
  return JSON.stringify({
    total,
    pages_scanned: page - 1,
    rows_scanned: rowsScanned,
    collected_count: out.length,
    rejected_brand_count: rejected.length,
    rejected_brands: rejected.slice(0, 50),
    items: out
  });
})()`, string(cfg)), nil
}

func writeDelimited(path string, items []Keyword, comma rune) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	w := csv.NewWriter(f)
	w.Comma = comma
	header := []string{"关键词", "搜索次数", "搜索次数区间", "类目路径", "类目", "线索ID", "标签", "权益", "用户支付金额", "成交增速30d", "需求热度", "需求热度区间", "供需比", "代发货源平台", "页码"}
	if err := w.Write(header); err != nil {
		return err
	}
	for _, item := range items {
		row := []string{
			item.Keyword,
			strconv.FormatInt(item.SearchPVCnt, 10),
			item.SearchPVCntRange,
			item.CategoryPath,
			item.CategoryName,
			item.ClueID,
			item.Labels,
			item.Profits,
			item.PayAmountRange,
			strconv.FormatFloat(item.PayAmountGrowth30dRate, 'f', -1, 64),
			strconv.FormatInt(item.SearchHeat, 10),
			item.DemandHeatRange,
			strconv.FormatFloat(item.DemandSupplyRate, 'f', -1, 64),
			item.GoodsSupplyPlatforms,
			strconv.Itoa(item.Page),
		}
		if err := w.Write(row); err != nil {
			return err
		}
	}
	w.Flush()
	return w.Error()
}

func parseInts(raw string) ([]int, error) {
	var out []int
	for _, part := range splitList(raw) {
		v, err := strconv.Atoi(part)
		if err != nil {
			return nil, fmt.Errorf("parse tag id %q: %w", part, err)
		}
		out = append(out, v)
	}
	return out, nil
}

func splitList(raw string) []string {
	re := regexp.MustCompile(`[,\n，、]+`)
	var out []string
	for _, part := range re.Split(raw, -1) {
		part = strings.TrimSpace(part)
		if part != "" {
			out = append(out, part)
		}
	}
	return out
}
