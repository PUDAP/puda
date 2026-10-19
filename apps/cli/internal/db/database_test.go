package db

import (
	"path/filepath"
	"testing"
)

func TestEnsureRunReusesRunAcrossConnections(t *testing.T) {
	path := filepath.Join(t.TempDir(), "puda.db")
	for i := 0; i < 2; i++ {
		store, err := Connect(path)
		if err != nil {
			t.Fatal(err)
		}
		if err := store.EnsureRun("machine-run"); err != nil {
			store.Disconnect()
			t.Fatalf("invocation %d: %v", i+1, err)
		}
		var count int
		if err := store.db.QueryRow("SELECT COUNT(*) FROM run WHERE run_id = ?", "machine-run").Scan(&count); err != nil {
			store.Disconnect()
			t.Fatal(err)
		}
		if err := store.Disconnect(); err != nil {
			t.Fatal(err)
		}
		if count != 1 {
			t.Fatalf("got %d run records, want 1", count)
		}
	}
}

func TestEnsureRunPreservesExistingRun(t *testing.T) {
	store, err := Connect(filepath.Join(t.TempDir(), "puda.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { store.Disconnect() })
	if _, err := store.db.Exec(`
		INSERT INTO protocol (protocol_id) VALUES ('protocol-1');
		INSERT INTO run (run_id, protocol_id, created_at)
		VALUES ('run-1', 'protocol-1', '2026-01-01 00:00:00');
		INSERT INTO command_log (run_id, payload, command_type)
		VALUES ('run-1', '{}', 'queue');
	`); err != nil {
		t.Fatal(err)
	}
	if err := store.EnsureRun("run-1"); err != nil {
		t.Fatal(err)
	}
	var unchanged, logs int
	if err := store.db.QueryRow(`SELECT COUNT(*) FROM run
		WHERE run_id = 'run-1' AND protocol_id = 'protocol-1'
		AND created_at = '2026-01-01 00:00:00'`).Scan(&unchanged); err != nil {
		t.Fatal(err)
	}
	if err := store.db.QueryRow("SELECT COUNT(*) FROM command_log WHERE run_id = 'run-1'").Scan(&logs); err != nil {
		t.Fatal(err)
	}
	if unchanged != 1 || logs != 1 {
		t.Fatalf("existing run or logs changed: matching runs=%d, logs=%d", unchanged, logs)
	}
	if err := store.InsertRun("run-1", nil); err == nil {
		t.Fatal("InsertRun should still reject duplicate run IDs")
	}
}

func TestEnsureRunReportsDatabaseErrors(t *testing.T) {
	store, err := Connect(filepath.Join(t.TempDir(), "puda.db"))
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Disconnect(); err != nil {
		t.Fatal(err)
	}
	if err := store.EnsureRun("run-1"); err == nil {
		t.Fatal("expected an error from the closed database")
	}
}
