package puda

import (
	"fmt"
	"regexp"
	"strings"
)

const natsNotConfigured = "NATS servers not configured; run 'puda profile add'"

var profileNamePattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_-]*$`)

// Connection is the NATS target for one command, after applying the active profile.
type Connection struct {
	Servers        string
	GatewayServers string
	Profile        string
	ExplicitE2E    bool
	E2E            bool
	CA             string
	KeyFile        string
}

// ValidProfileName reports whether name can be stored as a profile key.
func ValidProfileName(name string) bool {
	return profileNamePattern.MatchString(name)
}

// ClassifyServers reports whether servers use tls://.
// Every URL must use tls:// or every URL must use nats://.
func ClassifyServers(servers string) (bool, error) {
	tlsURL := false
	plainURL := false
	any := false
	for _, server := range strings.Split(servers, ",") {
		server = strings.TrimSpace(server)
		if server == "" {
			continue
		}
		any = true
		switch {
		case strings.HasPrefix(server, "tls://"):
			tlsURL = true
		case strings.HasPrefix(server, "nats://"):
			plainURL = true
		default:
			return false, fmt.Errorf("unsupported NATS URL %s", server)
		}
	}
	if !any {
		return false, fmt.Errorf("NATS servers cannot be empty")
	}
	if tlsURL && plainURL {
		return false, fmt.Errorf("NATS server URLs must all use tls:// or all use nats://")
	}
	return tlsURL, nil
}

// Validate checks that this profile is a plaintext nats:// connection or a
// tls:// connection with a CA and lab key path. It does not read those files.
func (p Profile) Validate() error {
	tls, err := p.requireScheme(p.NATSServers)
	if err != nil {
		return err
	}
	if p.E2E {
		if strings.TrimSpace(p.CA) == "" || strings.TrimSpace(p.KeyFile) == "" {
			return fmt.Errorf("encrypted profile requires a CA and a lab key")
		}
	} else if strings.TrimSpace(p.CA) != "" || strings.TrimSpace(p.KeyFile) != "" {
		return fmt.Errorf("plaintext profile cannot set a CA or lab key")
	}
	if strings.TrimSpace(p.GatewayServers) != "" {
		gatewayTLS, err := p.requireScheme(p.GatewayServers)
		if err != nil {
			return fmt.Errorf("gateway servers: %w", err)
		}
		if gatewayTLS != tls {
			return fmt.Errorf("gateway server URLs must use the same scheme as nats_servers")
		}
	}
	return nil
}

func (p Profile) requireScheme(servers string) (bool, error) {
	tls, err := ClassifyServers(servers)
	if err != nil {
		return false, err
	}
	if tls != p.E2E {
		scheme := "nats://"
		kind := "plaintext"
		if p.E2E {
			scheme = "tls://"
			kind = "encrypted"
		}
		return tls, fmt.Errorf("URLs must use %s for a %s profile", scheme, kind)
	}
	return tls, nil
}

// ActiveProfileConfig returns the selected profile. The bool is false when none is selected.
func (cfg *GlobalConfig) ActiveProfileConfig() (Profile, bool, error) {
	if cfg.ActiveProfile == "" {
		return Profile{}, false, nil
	}
	profile, ok := cfg.Profiles[cfg.ActiveProfile]
	if !ok {
		return Profile{}, false, fmt.Errorf("active profile %q not found; run 'puda profile list'", cfg.ActiveProfile)
	}
	return profile, true, nil
}

// ResolveConnection returns the active profile's NATS servers, gateway servers, and encryption settings.
func ResolveConnection(cfg *GlobalConfig) (Connection, error) {
	if cfg == nil {
		return Connection{}, fmt.Errorf("failed to load global config (run 'puda login' first)")
	}

	profile, active, err := cfg.ActiveProfileConfig()
	if err != nil {
		return Connection{}, err
	}
	if !active {
		return Connection{}, fmt.Errorf("%s", natsNotConfigured)
	}
	if strings.TrimSpace(profile.NATSServers) == "" {
		return Connection{}, fmt.Errorf("%s", natsNotConfigured)
	}
	return Connection{
		Servers:        profile.NATSServers,
		GatewayServers: profile.GatewayServers,
		Profile:        cfg.ActiveProfile,
		ExplicitE2E:    true,
		E2E:            profile.E2E,
		CA:             profile.CA,
		KeyFile:        profile.KeyFile,
	}, nil
}
