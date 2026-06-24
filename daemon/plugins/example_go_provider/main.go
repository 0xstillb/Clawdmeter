// example_go_provider/main.go — Example Clawdmeter plugin in Go
//
// Demonstrates that the plugin protocol works for non-Python executables.
// Build: cd example_go_provider && go build -o ../example-provider .
//
// Protocol: reads PluginRequest JSON from stdin, writes PluginResponse to stdout.

package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
)

type PluginRequest struct {
	Version     int                    `json:"version"`
	Action      string                 `json:"action"`
	PrevPayload map[string]interface{} `json:"prev_payload,omitempty"`
	LastError   string                 `json:"last_error,omitempty"`
}

type PluginResponse struct {
	Ok      bool                   `json:"ok"`
	Payload map[string]interface{} `json:"payload,omitempty"`
	Error   string                 `json:"error,omitempty"`
	Retry   bool                   `json:"retry"`
}

func main() {
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Scan()
	line := scanner.Text()

	var req PluginRequest
	if err := json.Unmarshal([]byte(line), &req); err != nil {
		resp := PluginResponse{Ok: false, Error: "invalid request JSON", Retry: false}
		json.NewEncoder(os.Stdout).Encode(resp)
		return
	}

	// Example: return a hardcoded payload (50% usage on both windows)
	payload := map[string]interface{}{
		"p":    "example",
		"mode": "window",
		"top": map[string]interface{}{
			"label":      "Current",
			"kind":       "window_short",
			"pct":        50,
			"reset_mins": 300,
			"has_reset":  true,
		},
		"bottom": map[string]interface{}{
			"label":      "Weekly",
			"kind":       "window_long",
			"pct":        25,
			"reset_mins": 7200,
			"has_reset":  true,
		},
		"st": "allowed",
		"ok": true,
		"s":  50,
		"sr": 300,
		"w":  25,
		"wr": 7200,
	}

	resp := PluginResponse{Ok: true, Payload: payload}
	json.NewEncoder(os.Stdout).Encode(resp)
}
