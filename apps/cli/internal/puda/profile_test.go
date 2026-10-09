package puda

import "testing"

func TestValidatePlainProfile(t *testing.T) {
	profile := Profile{NATSServers: "nats://bears:4222, nats://bears:4223"}
	if err := profile.Validate(); err != nil {
		t.Fatal(err)
	}
	profile.NATSServers = "tls://bears:4222"
	if err := profile.Validate(); err == nil {
		t.Fatal("expected plaintext profile to reject tls://")
	}
	profile = Profile{NATSServers: "nats://bears:4222", CA: "ca.pem"}
	if err := profile.Validate(); err == nil {
		t.Fatal("expected plaintext profile to reject a CA")
	}
}

func TestValidateEncryptedProfile(t *testing.T) {
	profile := Profile{NATSServers: "tls://imre:4222", E2E: true, CA: "ca.pem", KeyFile: "e2e.key"}
	if err := profile.Validate(); err != nil {
		t.Fatal(err)
	}
	profile.NATSServers = "nats://imre:4222"
	if err := profile.Validate(); err == nil {
		t.Fatal("expected encrypted profile to reject nats://")
	}
	profile.NATSServers = "tls://a:4222, nats://b:4222"
	if err := profile.Validate(); err == nil {
		t.Fatal("expected mixed schemes to be rejected")
	}
	profile = Profile{NATSServers: "tls://imre:4222", E2E: true}
	if err := profile.Validate(); err == nil {
		t.Fatal("expected encrypted profile to require a CA and key")
	}
}

func TestResolveConnectionUsesActiveProfile(t *testing.T) {
	cfg := &GlobalConfig{
		ActiveProfile: "imre",
		Profiles: map[string]Profile{
			"bears": {NATSServers: "nats://bears:4222"},
			"imre":  {NATSServers: "tls://imre:4222", E2E: true, CA: "ca.pem", KeyFile: "e2e.key"},
		},
	}
	conn, err := ResolveConnection(cfg)
	if err != nil {
		t.Fatal(err)
	}
	if conn.Servers != "tls://imre:4222" || !conn.ExplicitE2E || !conn.E2E || conn.CA != "ca.pem" || conn.KeyFile != "e2e.key" {
		t.Fatalf("conn=%+v", conn)
	}
}

func TestResolveConnectionRequiresProfile(t *testing.T) {
	if _, err := ResolveConnection(&GlobalConfig{}); err == nil {
		t.Fatal("expected missing profile to be rejected")
	}
}

func TestValidProfileName(t *testing.T) {
	for _, name := range []string{"bears", "imre", "ntu", "lab_1", "A1"} {
		if !ValidProfileName(name) {
			t.Fatalf("%q should be valid", name)
		}
	}
	for _, name := range []string{"", "has space", "../x", "-bad"} {
		if ValidProfileName(name) {
			t.Fatalf("%q should be invalid", name)
		}
	}
}
