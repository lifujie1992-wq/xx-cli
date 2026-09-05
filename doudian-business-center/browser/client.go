package browser

import (
	"encoding/json"
	"fmt"
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
		http:    &http.Client{Timeout: 120 * time.Second},
	}
}

func (c *Client) Call(action string, args map[string]any) (json.RawMessage, error) {
	return c.callOpenBridge(action, args)
}

func (c *Client) FindTab(url string, active bool) error {
	args := map[string]any{"url": url}
	if active {
		args["active"] = true
	}
	_, err := c.Call("find_tab", args)
	return err
}

func (c *Client) Navigate(url string, newTab bool) error {
	_, err := c.Call("navigate", map[string]any{"url": url, "newTab": newTab})
	return err
}

func (c *Client) Fill(selector, value string) error {
	_, err := c.Call("fill", map[string]any{"selector": selector, "value": value})
	return err
}

func (c *Client) Click(selector string) error {
	_, err := c.Call("click", map[string]any{"selector": selector})
	return err
}

func (c *Client) KeyType(text string) error {
	_, err := c.Call("key_type", map[string]any{"text": text})
	return err
}

func (c *Client) SendKeys(keys string) error {
	_, err := c.Call("send_keys", map[string]any{"keys": keys})
	return err
}

func (c *Client) Evaluate(code string) (json.RawMessage, error) {
	return c.Call("evaluate", map[string]any{"code": code})
}

func (c *Client) EvaluateJSON(code string, v any) error {
	raw, err := c.Evaluate(code)
	if err != nil {
		return err
	}
	var env struct {
		Type  string          `json:"type"`
		Value json.RawMessage `json:"value"`
	}
	if err := json.Unmarshal(raw, &env); err != nil {
		return fmt.Errorf("decode evaluate envelope: %w", err)
	}
	if env.Type != "string" {
		return fmt.Errorf("expected evaluate type=string, got %q", env.Type)
	}
	var s string
	if err := json.Unmarshal(env.Value, &s); err != nil {
		return fmt.Errorf("decode evaluate string: %w", err)
	}
	if err := json.Unmarshal([]byte(s), v); err != nil {
		return fmt.Errorf("decode evaluate JSON: %w", err)
	}
	return nil
}
