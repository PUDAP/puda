// Package compatibility contains pure, advisory CLI / Python SDK policy checks.
package compatibility

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"math/big"
	"regexp"
	"strings"
)

var releaseVersion = regexp.MustCompile(`^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$`)

//go:embed compatibility.json
var policy string

// Range contains inclusive stable-version bounds. Missing/null bounds are unknown.
type Range struct {
	Min string `json:"min"`
	Max string `json:"max"`
}

// Policy is a union of CLI/SDK range rules, with no per-release duplication.
type Policy struct {
	Compatibility []struct {
		CLI       Range `json:"cli"`
		PythonSDK Range `json:"python_sdk"`
	} `json:"compatibility"`
}

// Parse reads bundled or target-release metadata. Missing entries remain unknown.
func Parse(data []byte) (Policy, error) {
	var p Policy
	if err := json.Unmarshal(data, &p); err != nil {
		return Policy{}, err
	}
	return p, nil
}

// Bundled returns the installed CLI's policy, not a future release's policy.
func Bundled() Policy {
	p, _ := Parse([]byte(policy))
	return p
}

type Status string

const (
	Unknown     Status = "unknown"
	Supported   Status = "supported"
	Unsupported Status = "unsupported"
)

// Result carries all applicable SDK ranges (their union, not their envelope).
type Result struct {
	Status Status
	Ranges []Range
}

// compareRelease compares validated stable versions numerically, without
// machine-integer overflow or lexical version ordering.
func compareRelease(a, b string) int {
	aa, bb := strings.Split(a, "."), strings.Split(b, ".")
	for i := range aa {
		var x, y big.Int
		x.SetString(aa[i], 10)
		y.SetString(bb[i], 10)
		if cmp := x.Cmp(&y); cmp != 0 {
			return cmp
		}
	}
	return 0
}

func (r Range) valid() bool {
	return releaseVersion.MatchString(r.Min) && releaseVersion.MatchString(r.Max) && compareRelease(r.Min, r.Max) <= 0
}

func (r Range) contains(v string) bool {
	return compareRelease(r.Min, v) <= 0 && compareRelease(v, r.Max) <= 0
}

// Evaluate requires valid stable versions and complete ordered bounds. Invalid
// rules invalidate the policy rather than permitting partial approval. Valid
// overlapping rules are unioned; gaps between their SDK ranges stay unsupported.
func (p Policy) Evaluate(cliVersion, pythonSDKVersion string) Result {
	cli := strings.TrimPrefix(cliVersion, "v")
	result := Result{Status: Unknown}
	if !releaseVersion.MatchString(cli) {
		return result
	}
	for _, rule := range p.Compatibility {
		if !rule.CLI.valid() || !rule.PythonSDK.valid() {
			return Result{Status: Unknown}
		}
		if rule.CLI.contains(cli) {
			result.Ranges = append(result.Ranges, rule.PythonSDK)
		}
	}
	if len(result.Ranges) == 0 || !releaseVersion.MatchString(pythonSDKVersion) {
		return result
	}
	result.Status = Unsupported
	for _, bounds := range result.Ranges {
		if bounds.contains(pythonSDKVersion) {
			result.Status = Supported
			break
		}
	}
	return result
}

// Warning keeps guidance as a union rather than inventing support in range gaps.
func (r Result) Warning(cliVersion, machineID, pythonSDKVersion string) string {
	ranges := make([]string, 0, len(r.Ranges))
	for _, bounds := range r.Ranges {
		ranges = append(ranges, bounds.Min+" to "+bounds.Max)
	}
	guidance := strings.Join(ranges, " or ")
	switch r.Status {
	case Supported:
		return ""
	case Unsupported:
		return fmt.Sprintf("Warning: machine %q: Python SDK %q is outside the supported range for CLI %q; compatibility is not verified; upgrade/change the edge's Python SDK to a stable version in the declared supported range %s (both bounds inclusive; advisory only).\n", machineID, pythonSDKVersion, cliVersion, guidance)
	default:
		reason := "missing/invalid policy, no matching CLI range, or non-release version"
		if guidance != "" {
			reason += "; declared supported Python SDK range: " + guidance + " (both bounds inclusive)"
		}
		return fmt.Sprintf("Warning: machine %q: Python SDK compatibility unknown (CLI %q, reported Python SDK %q; %s; advisory only).\n", machineID, cliVersion, pythonSDKVersion, reason)
	}
}

// PythonSDKWarning checks the running edge's sdk_version, never local packages.
func PythonSDKWarning(cliVersion, machineID, pythonSDKVersion string) string {
	return Bundled().Evaluate(cliVersion, pythonSDKVersion).Warning(cliVersion, machineID, pythonSDKVersion)
}

func pythonSDKWarning(data, cliVersion, machineID, pythonSDKVersion string) string {
	p, _ := Parse([]byte(data))
	return p.Evaluate(cliVersion, pythonSDKVersion).Warning(cliVersion, machineID, pythonSDKVersion)
}
