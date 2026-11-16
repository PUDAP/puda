package compatibility

import (
	"strings"
	"testing"
)

func TestInvalidPolicyCannotPartiallyApprove(t *testing.T) {
	data := `{"compatibility":[{"cli":{"min":"0.1.6","max":"0.1.6"},"python_sdk":{"min":"0.0.22","max":"0.0.22"}},1]}`
	p, err := Parse([]byte(data))
	if err == nil {
		t.Fatal("expected parse error")
	}
	if got := p.Evaluate("0.1.6", "0.0.22").Status; got != Unknown {
		t.Fatalf("invalid policy approved %s", got)
	}
	if got := pythonSDKWarning(data, "0.1.6", "oven", "0.0.22"); !strings.Contains(got, "compatibility unknown") {
		t.Fatal(got)
	}
}

func TestWarningIncludesSupportedRange(t *testing.T) {
	got := pythonSDKWarning(`{"compatibility":[{"cli":{"min":"0.1.6","max":"0.1.6"},"python_sdk":{"min":"0.0.23","max":"0.0.24"}}]}`, "0.1.6", "oven", "0.0.22")
	for _, want := range []string{"oven", "0.0.22", "0.0.23", "0.0.24", "upgrade/change"} {
		if !strings.Contains(got, want) {
			t.Errorf("missing %q: %s", want, got)
		}
	}
}
