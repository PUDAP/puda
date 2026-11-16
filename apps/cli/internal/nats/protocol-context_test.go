package nats

import (
	"database/sql"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
)

func TestRunProtocolRejectsInvalidStepsBeforeSideEffects(t *testing.T) {
	for _, selector := range []string{"", " ", "0", "5-2", "1-2-3", "1,,3", "two-five"} {
		t.Run(selector, func(t *testing.T) {
			dir := t.TempDir()
			t.Chdir(dir)
			t.Setenv("XDG_CONFIG_HOME", dir)
			if err := os.WriteFile("puda.config", []byte(`{"user":{"user_id":"test","username":"test"},"database":{"path":"puda.db"}}`), 0600); err != nil {
				t.Fatal(err)
			}
			// Missing global config must not mask the selector error. Opening
			// the database would create a file even before a run is inserted.
			err := RunProtocol(&puda.ProtocolFile{}, &selector, nil)
			if err == nil || !strings.Contains(err.Error(), "--steps") {
				t.Errorf("expected selector error before config/network access, got %v", err)
			}
			if _, err := os.Stat("puda.db"); !os.IsNotExist(err) {
				t.Errorf("invalid selector touched database: %v", err)
			}
		})
	}
}

func TestRunProtocolPersistsRequestedStepsBeforeDispatch(t *testing.T) {
	dir := t.TempDir()
	t.Chdir(dir)
	t.Setenv("XDG_CONFIG_HOME", dir)
	ResetSession()
	t.Cleanup(ResetSession)
	if err := os.MkdirAll(filepath.Join(dir, "puda"), 0700); err != nil {
		t.Fatal(err)
	}
	// An invalid loopback port guarantees failure before any network dispatch.
	global := `{"user":{"user_id":"test","username":"test"},"active_profile":"offline","profiles":{"offline":{"nats_servers":"nats://127.0.0.1:invalid","e2e":false}}}`
	if err := os.WriteFile(filepath.Join(dir, "puda", "config.json"), []byte(global), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile("puda.config", []byte(`{"user":{"user_id":"test","username":"test"},"database":{"path":"puda.db"}}`), 0600); err != nil {
		t.Fatal(err)
	}
	store, err := db.Connect()
	if err != nil {
		t.Fatal(err)
	}
	defer store.Disconnect()
	for _, selector := range []string{"", "5-9", "2,4-6", " 2, 4-6 "} {
		protocol := puda.ProtocolFile{ProtocolID: "p" + selector}
		if err := store.InsertProtocol(protocol); err != nil {
			t.Fatal(err)
		}
		var steps *string
		if selector != "" {
			steps = &selector
		}
		err := RunProtocol(&protocol, steps, nil)
		if err == nil || !strings.Contains(err.Error(), "failed to connect to NATS") {
			t.Fatalf("expected offline dispatch failure, got %v", err)
		}
		rows, err := store.Query("SELECT run_id, protocol_id, steps FROM run")
		if err != nil {
			t.Fatal(err)
		}
		found := 0
		for rows.Next() {
			var runID, protocolID string
			var got sql.NullString
			if err := rows.Scan(&runID, &protocolID, &got); err != nil {
				t.Fatal(err)
			}
			if protocolID == protocol.ProtocolID {
				found++
				if runID == "" || got.Valid != (steps != nil) || got.String != selector {
					t.Fatalf("incorrect run context %q %v", runID, got)
				}
			}
		}
		rows.Close()
		if found != 1 {
			t.Fatalf("found %d runs for protocol %q", found, protocol.ProtocolID)
		}
	}
}
