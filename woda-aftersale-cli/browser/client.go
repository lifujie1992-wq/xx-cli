package browser

import (
	"encoding/json"
	"net/http"
	"time"
)

const DefaultDaemonURL = "http://127.0.0.1:10088"

type Client struct {
	baseURL string
	session string
	http    *http.Client
}

func NewClient(session string) *Client {
	return &Client{
		baseURL: openBridgeURL(),
		session: session,
		http:    &http.Client{Timeout: 90 * time.Second},
	}
}

type daemonResponse struct {
	OK    bool            `json:"ok"`
	Data  json.RawMessage `json:"data"`
	Error *struct {
		Code    string `json:"code"`
		Message string `json:"message"`
	} `json:"error"`
}

func (c *Client) Call(action string, args map[string]any) (json.RawMessage, error) {
	return c.callOpenBridge(action, args)
}

func (c *Client) Navigate(url string) error {
	_, err := c.Call("navigate", map[string]any{"url": url, "newTab": false})
	return err
}

// Evaluate runs JS in the active tab. The JS must be an expression (or IIFE)
// that returns a value — OpenBridge wraps the return into {type, value}.
func (c *Client) Evaluate(code string) (json.RawMessage, error) {
	raw, err := c.Call("evaluate", map[string]any{"code": code})
	if err != nil {
		return nil, err
	}
	// Unwrap the {type, value} envelope so callers get the raw JS return value.
	var env struct {
		Type  string          `json:"type"`
		Value json.RawMessage `json:"value"`
	}
	if err := json.Unmarshal(raw, &env); err != nil {
		return raw, nil
	}
	if len(env.Value) == 0 {
		return raw, nil
	}
	return env.Value, nil
}

// Click clicks an element matching the CSS selector in the active tab.
func (c *Client) Click(selector string) error {
	_, err := c.Call("click", map[string]any{"selector": selector})
	return err
}
