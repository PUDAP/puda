package compatibility

import (
	"strings"
	"testing"
)

func TestBundledPolicyMatchesDeclaredSupport(t *testing.T) {
	for _, tc := range []struct {
		cli, sdk string
		want     Status
	}{
		{"0.0.0", "0.0.15", Supported}, {"0.0.36", "0.0.16", Supported},
		{"0.0.0", "0.0.16", Supported}, {"0.0.36", "0.0.15", Supported},
		{"0.1.0", "0.0.22", Supported}, {"0.1.6", "0.0.17", Supported},
		{"0.0.36", "0.0.17", Unsupported}, {"0.1.0", "0.0.16", Unsupported},
		{"0.1.0", "0.0.17", Supported}, {"0.1.6", "0.0.22", Supported},
		{"0.1.3", "0.0.20", Supported}, {"0.0.0", "0.0.14", Unsupported},
		{"0.0.37", "0.0.16", Unknown}, {"0.1.7", "0.0.22", Unknown},
		{"0.1.0-rc1", "0.0.17", Unknown}, {"0.0.36", "0.0.16rc1", Unknown},
	} {
		if got := Bundled().Evaluate(tc.cli, tc.sdk).Status; got != tc.want {
			t.Errorf("%+v: %s", tc, got)
		}
	}
}

func TestPythonSDKUnknownAndReleasePrefix(t *testing.T) {
	const policy = `{"compatibility":[{"cli":{"min":"0.1.6","max":"0.1.6"},"python_sdk":{"min":"0.0.21","max":"0.0.21"}}]}`
	for _, pair := range [][2]string{{"dev", "0.0.21"}, {"0.1.7", "0.0.21"}, {"0.1.6", ""}, {"0.1.6", "unknown"}, {"0.1.6", "0.0.21.dev1"}, {"0.1.6", "0.0.21+local"}, {"0.1.6", "v0.0.21"}, {"0.1.6", " 0.0.21"}, {"0.1.6", "00.0.21"}, {"0.1.6-dirty", "0.0.21"}} {
		got := pythonSDKWarning(policy, pair[0], "edge", pair[1])
		if !strings.Contains(got, "compatibility unknown") || strings.Contains(got, "outside the supported range") {
			t.Errorf("%q: %s", pair, got)
		}
	}
	if got := pythonSDKWarning(policy, "v0.1.6", "edge", "0.0.21"); got != "" {
		t.Errorf("release tag prefix: %s", got)
	}
	for _, data := range []string{`{`, `{}`, `{"compatibility":[{"cli":{"min":"0.1.6","max":"0.1.6"},"python_sdk":{}}]}`} {
		if got := pythonSDKWarning(data, "0.1.6", "edge", "0.0.21"); !strings.Contains(got, "compatibility unknown") {
			t.Errorf("%s: %s", data, got)
		}
	}
}

func TestPythonSDKWarningSingletonRange(t *testing.T) {
	const policy = `{"compatibility":[{"cli":{"min":"0.1.6","max":"0.1.6"},"python_sdk":{"min":"0.0.21","max":"0.0.21"}}]}`
	if got := pythonSDKWarning(policy, "0.1.6", "edge", "0.0.21"); got != "" {
		t.Fatalf("supported version warned: %s", got)
	}
	got := pythonSDKWarning(policy, "0.1.6", "edge", "0.0.22")
	if !strings.Contains(got, "outside the supported range") || !strings.Contains(got, "edge") || !strings.Contains(got, "0.0.22") {
		t.Fatalf("missing advisory: %s", got)
	}
}
