package doudian

import (
	"fmt"
	"strings"
	"time"

	"doudian-business-center-cli/browser"
)

const (
	SearchInputSelector  = ".auxo-input-search input.auxo-input"
	SearchButtonSelector = ".auxo-input-search-button"
)

type SearchUIResult struct {
	Filled         bool   `json:"filled"`
	Clicked        bool   `json:"clicked"`
	InputSelector  string `json:"input_selector"`
	ButtonSelector string `json:"button_selector"`
	InputValue     string `json:"input_value"`
	PageURL        string `json:"page_url"`
	PageTitle      string `json:"page_title"`
	ListPreview    string `json:"list_preview,omitempty"`
}

type SearchRunResult struct {
	Query  string         `json:"query"`
	UI     SearchUIResult `json:"ui"`
	Result Result         `json:"result"`
}

func Search(c *browser.Client, opt Options, fillUI bool, clickButton bool, waitMs int) (*SearchRunResult, error) {
	opt.Query = strings.TrimSpace(opt.Query)
	if opt.Query == "" {
		return nil, fmt.Errorf("query is required")
	}
	if opt.URL == "" {
		opt.URL = DefaultSearchURL
	}
	if opt.PageSize <= 0 || opt.PageSize > 100 {
		opt.PageSize = DefaultPageSize
	}
	if opt.Limit <= 0 {
		opt.Limit = 20
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
	if waitMs < 0 {
		waitMs = 0
	}

	if err := ensureBusinessCenter(c, opt); err != nil {
		return nil, err
	}

	var ui SearchUIResult
	if fillUI {
		var err error
		ui, err = FillSearchBox(c, opt.Query, clickButton, waitMs)
		if err != nil {
			return nil, err
		}
	}

	res, err := collectCurrentPage(c, opt)
	if err != nil {
		return nil, err
	}
	return &SearchRunResult{Query: opt.Query, UI: ui, Result: *res}, nil
}

func FillSearchBox(c *browser.Client, query string, clickButton bool, waitMs int) (SearchUIResult, error) {
	query = strings.TrimSpace(query)
	if query == "" {
		return SearchUIResult{}, fmt.Errorf("query is required")
	}
	if err := c.Fill(SearchInputSelector, query); err != nil {
		return SearchUIResult{}, fmt.Errorf("fill search input: %w", err)
	}
	clicked := false
	if clickButton {
		if err := c.Click(SearchButtonSelector); err != nil {
			return SearchUIResult{}, fmt.Errorf("click search button: %w", err)
		}
		clicked = true
	}
	if waitMs > 0 {
		time.Sleep(time.Duration(waitMs) * time.Millisecond)
	}
	ui, err := readSearchUI(c)
	if err != nil {
		return SearchUIResult{}, err
	}
	ui.Filled = true
	ui.Clicked = clicked
	ui.InputSelector = SearchInputSelector
	ui.ButtonSelector = SearchButtonSelector
	return ui, nil
}

func readSearchUI(c *browser.Client) (SearchUIResult, error) {
	code := `(function(){
  const input = document.querySelector(".auxo-input-search input.auxo-input");
  const list = document.querySelector("#clue-list-container") || document.body;
  const preview = (list && list.innerText || "").replace(/\s+/g, " ").slice(0, 800);
  return JSON.stringify({
    input_value: input ? input.value : "",
    page_url: location.href,
    page_title: document.title,
    list_preview: preview
  });
})()`
	var ui SearchUIResult
	if err := c.EvaluateJSON(code, &ui); err != nil {
		return SearchUIResult{}, err
	}
	return ui, nil
}

func collectCurrentPage(c *browser.Client, opt Options) (*Result, error) {
	var result Result
	code, err := collectScript(opt)
	if err != nil {
		return nil, err
	}
	if err := c.EvaluateJSON(code, &result); err != nil {
		return nil, err
	}
	result.CollectedCount = len(result.Items)
	return &result, nil
}
