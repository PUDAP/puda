package compatibility

import (
	"strings"
	"testing"
)

func TestInclusiveNumericRange(t *testing.T) {
	p, err := Parse([]byte(`{"compatibility":[{"cli":{"min":"0.1.6","max":"0.1.6"},"python_sdk":{"min":"0.0.9","max":"0.0.22"}}]}`))
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		sdk  string
		want Status
	}{
		{"0.0.9", Supported}, {"0.0.10", Supported}, {"0.0.20", Supported}, {"0.0.22", Supported},
		{"0.0.8", Unsupported}, {"0.0.23", Unsupported}, {"0.1.0", Unsupported}, {"1.0.0", Unsupported},
		{"0.0.20-rc1", Unknown}, {"0.0.20.dev1", Unknown}, {"0.0.20+local", Unknown},
	} {
		if got := p.Evaluate("v0.1.6", tc.sdk).Status; got != tc.want {
			t.Errorf("%s: got %s, want %s", tc.sdk, got, tc.want)
		}
	}
}

func TestUnknownRangeBounds(t *testing.T) {
	for _, bounds := range []string{
		`{}`, `{"min":null,"max":null}`, `{"min":"0.0.17"}`, `{"max":"0.0.22"}`,
		`{"min":null,"max":"0.0.22"}`, `{"min":"0.0.17","max":null}`,
		`{"min":"0.0.23","max":"0.0.22"}`, `{"min":"0.00.17","max":"0.0.22"}`,
		`{"min":"0.0.17","max":"0.0.22-rc1"}`, `{"min":"dev","max":"0.0.22"}`,
		`{"min":"0.0.17","max":" 0.0.22"}`, `{"min":"0.0.17","max":22}`,
	} {
		p, _ := Parse([]byte(`{"compatibility":[{"cli":{"min":"0.1.6","max":"0.1.6"},"python_sdk":` + bounds + `}]}`))
		if got := p.Evaluate("0.1.6", "0.0.20"); got.Status != Unknown {
			t.Errorf("%s: %+v", bounds, got)
		}
	}
}

func TestNumericRangeComponents(t *testing.T) {
	for _, tc := range []struct {
		min, max, sdk string
		want          Status
	}{
		{"0.9.0", "0.10.0", "0.10.0", Supported},
		{"9.0.0", "10.0.0", "10.0.0", Supported},
		{"0.0.999999999999999999999999", "0.0.1000000000000000000000000", "0.0.1000000000000000000000000", Supported},
		{"0.10.0", "0.9.0", "0.10.0", Unknown},
	} {
		p, err := Parse([]byte(`{"compatibility":[{"cli":{"min":"0.1.6","max":"0.1.6"},"python_sdk":{"min":"` + tc.min + `","max":"` + tc.max + `"}}]}`))
		if err != nil {
			t.Fatal(err)
		}
		if got := p.Evaluate("0.1.6", tc.sdk).Status; got != tc.want {
			t.Errorf("%+v: %s", tc, got)
		}
	}
}

func TestOverlappingRulesUnionAndInvalidPolicy(t *testing.T) {
	const valid = `{"compatibility":[
 {"cli":{"min":"0.1.0","max":"0.1.6"},"python_sdk":{"min":"0.0.17","max":"0.0.19"}},
 {"cli":{"min":"0.1.4","max":"0.1.8"},"python_sdk":{"min":"0.0.21","max":"0.0.22"}}]}`
	p, err := Parse([]byte(valid))
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		cli, sdk string
		want     Status
	}{
		{"0.1.5", "0.0.17", Supported}, {"0.1.5", "0.0.22", Supported},
		{"0.1.5", "0.0.20", Unsupported}, {"0.1.3", "0.0.21", Unsupported},
		{"0.1.8", "0.0.21", Supported}, {"0.1.9", "0.0.21", Unknown},
	} {
		if got := p.Evaluate(tc.cli, tc.sdk).Status; got != tc.want {
			t.Errorf("%+v: %s", tc, got)
		}
	}
	if got := p.Evaluate("0.1.5", "0.0.20").Warning("0.1.5", "edge", "0.0.20"); !strings.Contains(got, "0.0.17 to 0.0.19 or 0.0.21 to 0.0.22") {
		t.Fatal(got)
	}
	for _, invalid := range []string{
		`{"cli":{"min":"0.2.0"},"python_sdk":{"min":"0.0.17","max":"0.0.22"}}`,
		`{"cli":{"min":"0.1.6","max":"0.1.0"},"python_sdk":{"min":"0.0.17","max":"0.0.22"}}`,
		`{"cli":{"min":"0.1.0-rc1","max":"0.1.6"},"python_sdk":{"min":"0.0.17","max":"0.0.22"}}`,
		`{"cli":{"min":"0.1.0","max":"0.1.6"},"python_sdk":{"min":null,"max":null}}`,
	} {
		data := strings.TrimSuffix(valid, "]}") + "," + invalid + "]}"
		p, err := Parse([]byte(data))
		if err != nil {
			t.Fatal(err)
		}
		if got := p.Evaluate("0.1.5", "0.0.17"); got.Status != Unknown || len(got.Ranges) != 0 {
			t.Fatalf("invalid policy approved: %+v", got)
		}
	}
}
