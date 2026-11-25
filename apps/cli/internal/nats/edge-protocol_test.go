package nats

import (
	"strconv"
	"strings"
	"testing"
)

func TestClassifyEdgeProtocol(t *testing.T) {
	for version, want := range map[string]string{
		"1.0":    ProtocolSupported,
		"1.7":    ProtocolSupported,
		"":       ProtocolUnsupported, // edge predates Edge Protocol 1.0
		"2.0":    ProtocolUnsupported,
		"0.9":    ProtocolUnsupported,
		"1":      ProtocolUnsupported,
		"1.0.0":  ProtocolUnsupported,
		"v1.0":   ProtocolUnsupported,
		"1.x":    ProtocolUnsupported,
		"banana": ProtocolUnsupported,
	} {
		if got := ClassifyProtocol(version); got != want {
			t.Errorf("ClassifyProtocol(%q)=%s want %s", version, got, want)
		}
	}
	if ClassifyProtocol(ProtocolVersion) != ProtocolSupported || ProtocolVersion[:strings.Index(ProtocolVersion, ".")] != strconv.Itoa(SupportedProtocolMajor) {
		t.Fatalf("ProtocolVersion %s disagrees with SupportedProtocolMajor %d", ProtocolVersion, SupportedProtocolMajor)
	}
	if ProtocolLabel("") != "none" || ProtocolLabel("1.0") != "1.0" {
		t.Fatal("protocol label")
	}
}
