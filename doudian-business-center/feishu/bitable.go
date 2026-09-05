package feishu

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

const (
	DefaultCLIPath  = "feishu-cli"
	DefaultAppToken = "REPLACE_WITH_FEISHU_APP_TOKEN"
)

type Options struct {
	CLIPath   string `json:"cli_path"`
	AppToken  string `json:"app_token"`
	TableName string `json:"table_name"`
	TableID   string `json:"table_id,omitempty"`
	Columns   string `json:"columns"`
	DryRun    bool   `json:"dry_run"`
}

type Result struct {
	AppToken     string   `json:"app_token"`
	TableName    string   `json:"table_name"`
	TableID      string   `json:"table_id"`
	Columns      string   `json:"columns"`
	RecordCount  int      `json:"record_count"`
	DryRun       bool     `json:"dry_run"`
	Commands     []string `json:"commands,omitempty"`
	RecordsFile  string   `json:"records_file,omitempty"`
	CreateOutput any      `json:"create_output,omitempty"`
	AddOutput    any      `json:"add_output,omitempty"`
}

type fieldInfo struct {
	FieldID   string `json:"field_id"`
	FieldName string `json:"field_name"`
	Type      int    `json:"type"`
	IsPrimary bool   `json:"is_primary"`
}

func WriteRecords(opt Options, records []map[string]any, fieldTypes map[string]int) (*Result, error) {
	if opt.CLIPath == "" {
		opt.CLIPath = DefaultCLIPath
	}
	if opt.AppToken == "" {
		opt.AppToken = os.Getenv("DOUDIAN_FEISHU_APP_TOKEN")
	}
	if opt.AppToken == "" {
		opt.AppToken = DefaultAppToken
	}
	if opt.TableName == "" {
		opt.TableName = "抖店商机关键词100"
	}
	if opt.Columns == "" {
		opt.Columns = "compact"
	}
	res := &Result{
		AppToken:    opt.AppToken,
		TableName:   opt.TableName,
		TableID:     opt.TableID,
		Columns:     opt.Columns,
		RecordCount: len(records),
		DryRun:      opt.DryRun,
	}

	if opt.DryRun {
		res.Commands = []string{
			fmt.Sprintf("%s bitable create-table %s -n %q -o json", opt.CLIPath, opt.AppToken, opt.TableName),
			fmt.Sprintf("%s bitable add-records %s <table_id> --data-file <records.json> -o json", opt.CLIPath, opt.AppToken),
		}
		return res, nil
	}

	if _, err := os.Stat(opt.CLIPath); err != nil {
		return nil, fmt.Errorf("feishu cli not found at %s: %w", opt.CLIPath, err)
	}

	if res.TableID == "" {
		out, err := runJSON(opt.CLIPath, "bitable", "create-table", opt.AppToken, "-n", opt.TableName, "-o", "json")
		if err != nil {
			return nil, err
		}
		res.CreateOutput = out
		tableID := findStringKey(out, "table_id")
		if tableID == "" {
			return nil, fmt.Errorf("create-table output did not contain table_id: %v", out)
		}
		res.TableID = tableID
		if err := ensureFields(opt.CLIPath, opt.AppToken, res.TableID, fieldTypes); err != nil {
			return nil, err
		}
	}
	effectiveFieldTypes := fieldTypes
	if fields, err := listFields(opt.CLIPath, opt.AppToken, res.TableID); err == nil {
		effectiveFieldTypes = fieldTypesByName(fields)
	} else if opt.TableID != "" {
		return nil, err
	}
	coerceRecordsForFields(records, effectiveFieldTypes)

	recordsFile, err := writeTempJSON(records)
	if err != nil {
		return nil, err
	}
	res.RecordsFile = recordsFile
	out, err := runJSON(opt.CLIPath, "bitable", "add-records", opt.AppToken, res.TableID, "--data-file", recordsFile, "-o", "json")
	if err != nil {
		return nil, err
	}
	res.AddOutput = out
	return res, nil
}

func ensureFields(cliPath, appToken, tableID string, fieldTypes map[string]int) error {
	fields, err := listFields(cliPath, appToken, tableID)
	if err != nil {
		return err
	}
	existing := map[string]fieldInfo{}
	var primary *fieldInfo
	for i := range fields {
		existing[fields[i].FieldName] = fields[i]
		if fields[i].IsPrimary {
			primary = &fields[i]
		}
	}
	if _, ok := existing["关键词"]; !ok && primary != nil {
		def := map[string]any{"field_name": "关键词", "type": 1}
		b, _ := json.Marshal(def)
		if _, err := runJSON(cliPath, "bitable", "update-field", appToken, tableID, primary.FieldID, "--field", string(b), "-o", "json"); err != nil {
			return err
		}
		existing["关键词"] = *primary
	}
	order := []string{"搜索次数", "搜索次数区间", "类目路径", "标签", "类目", "线索ID", "权益", "用户支付金额", "成交增速30d", "需求热度", "需求热度区间", "供需比", "代发货源平台"}
	for _, name := range order {
		typ, ok := fieldTypes[name]
		if !ok {
			continue
		}
		if _, exists := existing[name]; exists {
			continue
		}
		def := map[string]any{"field_name": name, "type": typ}
		b, _ := json.Marshal(def)
		if _, err := runJSON(cliPath, "bitable", "create-field", appToken, tableID, "--field", string(b), "-o", "json"); err != nil {
			return err
		}
	}
	return nil
}

func listFields(cliPath, appToken, tableID string) ([]fieldInfo, error) {
	out, err := runJSON(cliPath, "bitable", "fields", appToken, tableID, "-o", "json")
	if err != nil {
		return nil, err
	}
	var fields []fieldInfo
	raw, _ := json.Marshal(out)
	if err := json.Unmarshal(raw, &fields); err != nil {
		return nil, fmt.Errorf("decode fields output: %w", err)
	}
	return fields, nil
}

func fieldTypesByName(fields []fieldInfo) map[string]int {
	out := map[string]int{}
	for _, field := range fields {
		out[field.FieldName] = field.Type
	}
	return out
}

func coerceRecordsForFields(records []map[string]any, fieldTypes map[string]int) {
	for _, record := range records {
		for name, typ := range fieldTypes {
			value, ok := record[name]
			if !ok {
				continue
			}
			if typ == 4 {
				switch v := value.(type) {
				case string:
					v = strings.TrimSpace(v)
					if v == "" {
						delete(record, name)
						continue
					}
					record[name] = []string{v}
				case []string:
				case []any:
				default:
					record[name] = []string{fmt.Sprint(v)}
				}
			}
		}
	}
}

func runJSON(name string, args ...string) (any, error) {
	cmd := exec.Command(name, args...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("%s %s failed: %w: %s", name, strings.Join(args, " "), err, stderr.String())
	}
	out := bytes.TrimSpace(stdout.Bytes())
	if len(out) == 0 {
		return map[string]any{}, nil
	}
	var v any
	if err := json.Unmarshal(out, &v); err != nil {
		return nil, fmt.Errorf("decode feishu-cli JSON output: %w: %s", err, string(out))
	}
	return v, nil
}

func writeTempJSON(v any) (string, error) {
	dir := filepath.Join(os.TempDir(), "doudian-business-center-cli")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	path := filepath.Join(dir, fmt.Sprintf("records_%d.json", time.Now().UnixNano()))
	b, err := json.Marshal(v)
	if err != nil {
		return "", err
	}
	if err := os.WriteFile(path, b, 0o600); err != nil {
		return "", err
	}
	return path, nil
}

func findStringKey(v any, key string) string {
	switch x := v.(type) {
	case map[string]any:
		for k, val := range x {
			if k == key {
				if s, ok := val.(string); ok {
					return s
				}
			}
			if s := findStringKey(val, key); s != "" {
				return s
			}
		}
	case []any:
		for _, item := range x {
			if s := findStringKey(item, key); s != "" {
				return s
			}
		}
	}
	return ""
}
