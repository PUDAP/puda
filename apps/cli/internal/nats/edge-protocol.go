package nats

import (
	"strconv"
	"strings"
)

// ProtocolVersion is the Edge Protocol version (MAJOR.MINOR) this CLI speaks.
// It is sent as header.protocol_version in every command; edges refuse a
// missing value or another major.
const ProtocolVersion = "1.0"

// SupportedProtocolMajor is ProtocolVersion's major. Minor versions only add
// fields or verbs, so any 1.x edge is supported; a new major is a breaking
// release of both the CLI and the edge SDKs.
const SupportedProtocolMajor = 1

// SupportedProtocol is SupportedProtocolMajor as reported to agents.
var SupportedProtocol = strconv.Itoa(SupportedProtocolMajor) + ".x"

// Edge protocol support states reported per edge.
const (
	ProtocolSupported   = "supported"
	ProtocolUnsupported = "unsupported"
)

// ClassifyProtocol judges a pong's protocol_version ("MAJOR.MINOR"). Missing
// (an edge predating Edge Protocol 1.0, i.e. Python SDK before 0.1.0),
// malformed or another major is unsupported.
func ClassifyProtocol(version string) string {
	major, minor, ok := strings.Cut(version, ".")
	if !ok || !isDecimal(major) || !isDecimal(minor) {
		return ProtocolUnsupported
	}
	if n, err := strconv.Atoi(major); err != nil || n != SupportedProtocolMajor {
		return ProtocolUnsupported
	}
	return ProtocolSupported
}

// ProtocolLabel names a pong's protocol_version in messages ("none" if absent).
func ProtocolLabel(version string) string {
	if version == "" {
		return "none"
	}
	return version
}

func isDecimal(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}
