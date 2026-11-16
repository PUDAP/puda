package compatibility

import (
	"strings"
	"testing"
)

func TestEvaluatePythonSDKStates(t *testing.T) {
	for _, tc := range []struct {
		name, metadata, cli, sdk string
		status                   Status
		guidance                 string
	}{
		{"supported", `{"compatibility":[{"cli":{"min":"0.1.6","max":"0.1.6"},"python_sdk":{"min":"0.0.22","max":"0.0.22"}}]}`, "v0.1.6", "0.0.22", Supported, ""},
		{"above-maximum", `{"compatibility":[{"cli":{"min":"0.1.6","max":"0.1.6"},"python_sdk":{"min":"0.0.22","max":"0.0.22"}}]}`, "0.1.6", "0.0.23", Unsupported, "0.0.22"},
		{"unknown-bounds", `{"compatibility":[{"cli":{"min":"0.1.6","max":"0.1.6"},"python_sdk":{"min":null,"max":null}}]}`, "0.1.6", "0.0.22", Unknown, "compatibility unknown"},
		{"missing-bounds", `{"compatibility":[{"cli":{"min":"0.1.6","max":"0.1.6"},"python_sdk":{}}]}`, "0.1.6", "0.0.22", Unknown, "compatibility unknown"},
		{"invalid-bounds", `{"compatibility":[{"cli":{"min":"0.1.6","max":"0.1.6"},"python_sdk":{"min":"dev","max":"0.0.22"}}]}`, "0.1.6", "0.0.22", Unknown, "compatibility unknown"},
		{"dev-edge", `{"compatibility":[{"cli":{"min":"0.1.6","max":"0.1.6"},"python_sdk":{"min":"0.0.22","max":"0.0.22"}}]}`, "0.1.6", "0.0.22.dev1", Unknown, "0.0.22"},
		{"dev-cli", `{"compatibility":[{"cli":{"min":"0.1.6","max":"0.1.6"},"python_sdk":{"min":"0.0.22","max":"0.0.22"}}]}`, "dev", "0.0.22", Unknown, "compatibility unknown"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			p, err := Parse([]byte(tc.metadata))
			if err != nil {
				t.Fatal(err)
			}
			r := p.Evaluate(tc.cli, tc.sdk)
			if r.Status != tc.status {
				t.Fatalf("%+v", r)
			}
			warning := r.Warning(tc.cli, "edge", tc.sdk)
			if tc.status == Supported && warning != "" {
				t.Fatal(warning)
			}
			if tc.guidance != "" && !strings.Contains(warning, tc.guidance) {
				t.Fatal(warning)
			}
		})
	}
}
