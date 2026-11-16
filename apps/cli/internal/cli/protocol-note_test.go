package cli

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	"github.com/spf13/cobra"
)

func noteProject(t *testing.T) *db.Store {
	t.Helper()
	dir := t.TempDir()
	t.Chdir(dir)
	config := `{"user":{"user_id":"test","username":"test"},"database":{"path":"puda.db"}}`
	if err := os.WriteFile(filepath.Join(dir, "puda.config"), []byte(config), 0600); err != nil {
		t.Fatal(err)
	}
	store, err := db.Connect()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { store.Disconnect() })
	if _, err := store.ExecSQL(`INSERT INTO protocol(protocol_id) VALUES ('p'); INSERT INTO run(run_id,protocol_id) VALUES ('r','p'), ('standalone',NULL);`); err != nil {
		t.Fatal(err)
	}
	return store
}

func executeNote(t *testing.T, args ...string) (string, error) {
	t.Helper()
	cmd, _, err := protocolCmd.Find([]string{"note"})
	if err != nil || cmd.Name() != "note" {
		t.Fatalf("protocol note command missing: %v", err)
	}
	// Reset flag state because production commands are package-level singletons.
	for _, name := range []string{"run", "text"} {
		f := cmd.Flags().Lookup(name)
		if f == nil {
			t.Fatalf("missing --%s", name)
		}
		f.Value.Set("")
		f.Changed = false
	}
	root := &cobra.Command{Use: "test", SilenceErrors: true, SilenceUsage: true}
	protocolCmd.RemoveCommand(cmd)
	root.AddCommand(cmd)
	defer func() {
		root.RemoveCommand(cmd)
		protocolCmd.AddCommand(cmd)
	}()
	var out bytes.Buffer
	root.SetOut(&out)
	root.SetErr(&out)
	root.SetArgs(append([]string{"note"}, args...))
	err = root.Execute()
	return out.String(), err
}

func TestProtocolNoteAppendsVerbatimAndReturnsReadback(t *testing.T) {
	store := noteProject(t)
	texts := []string{"O'Brien says \"成功\"\n[plot](plots/a b.svg)\n[report](reports/result.md)", "  second line\n測定 Δ 🧪  "}
	previous := ""
	for _, text := range texts {
		out, err := executeNote(t, "--run", "r", "--text", text)
		if err != nil {
			t.Fatal(err)
		}
		var result struct {
			RunID string `json:"run_id"`
			Notes string `json:"notes"`
		}
		if err = json.Unmarshal([]byte(out), &result); err != nil {
			t.Fatalf("%s: %v", out, err)
		}
		rows, err := store.Query("SELECT notes FROM run WHERE run_id='r'")
		if err != nil {
			t.Fatal(err)
		}
		if !rows.Next() {
			t.Fatal("no run")
		}
		var saved string
		if err = rows.Scan(&saved); err != nil {
			t.Fatal(err)
		}
		rows.Close()
		if result.RunID != "r" || result.Notes != saved || !strings.HasSuffix(saved, text) || !strings.HasPrefix(saved, previous) {
			t.Fatalf("incorrect readback: %+v saved=%q", result, saved)
		}
		entry := strings.TrimPrefix(saved, previous)
		entry = strings.TrimPrefix(entry, "\n\n")
		end := strings.Index(entry, "] ")
		if !strings.HasPrefix(entry, "[") || end < 0 {
			t.Fatalf("missing timestamp: %q", entry)
		}
		stamp := entry[1:end]
		parsed, err := time.Parse(time.RFC3339Nano, stamp)
		if err != nil || !strings.HasSuffix(stamp, "Z") || time.Since(parsed) > time.Minute {
			t.Fatalf("not current UTC: %q (%v)", stamp, err)
		}
		previous = saved
	}
}

func TestProtocolNoteRejectsInvalidInput(t *testing.T) {
	store := noteProject(t)
	for _, args := range [][]string{{}, {"--run", "r"}, {"--text", "x"}, {"--run", "r", "--text", " \n\t\u2003"}, {"--run", "missing", "--text", "x"}, {"--run", "standalone", "--text", "x"}, {"--run", "r' OR 1=1 --", "--text", "x"}} {
		if out, err := executeNote(t, args...); err == nil {
			t.Fatalf("accepted %q: %s", args, out)
		}
	}
	rows, err := store.Query("SELECT COUNT(*) FROM run WHERE notes IS NOT NULL")
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	if !rows.Next() {
		t.Fatalf("missing count row: %v", rows.Err())
	}
	var count int
	if err := rows.Scan(&count); err != nil {
		t.Fatal(err)
	}
	if count != 0 {
		t.Fatalf("invalid input changed %d runs", count)
	}
}
