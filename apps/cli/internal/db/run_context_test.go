package db

import (
	"database/sql"
	"fmt"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

func TestConcurrentProtocolNotes(t *testing.T) {
	path := filepath.Join(t.TempDir(), "puda.db")
	store, err := Connect(path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Disconnect()
	if _, err := store.db.Exec(`INSERT INTO protocol(protocol_id) VALUES ('p'); INSERT INTO run(run_id,protocol_id,steps,notes) VALUES ('r','p','2,4-6','original [plot](plots/原.svg)');`); err != nil {
		t.Fatal(err)
	}
	const writers = 16
	start := make(chan struct{})
	errs := make(chan error, writers)
	var wg sync.WaitGroup
	for i := 0; i < writers; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			<-start
			other, err := Connect(path)
			if err != nil {
				errs <- err
				return
			}
			defer other.Disconnect()
			text := fmt.Sprintf("note-%02d 'quoted'\n測定 [data](exports/a.csv)", i)
			saved, err := other.AppendProtocolNote("r", text)
			if err == nil && (!strings.HasPrefix(saved, "original [plot](plots/原.svg)") || !strings.HasSuffix(saved, text)) {
				err = fmt.Errorf("incorrect writer readback: %q", saved)
			}
			errs <- err
		}(i)
	}
	close(start)
	wg.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Error(err)
		}
	}
	var notes, steps string
	if err := store.db.QueryRow("SELECT notes,steps FROM run WHERE run_id='r'").Scan(&notes, &steps); err != nil {
		t.Fatal(err)
	}
	if steps != "2,4-6" || !strings.HasPrefix(notes, "original [plot](plots/原.svg)") {
		t.Fatal("original metadata lost")
	}
	for i := 0; i < writers; i++ {
		text := fmt.Sprintf("note-%02d 'quoted'\n測定 [data](exports/a.csv)", i)
		if strings.Count(notes, text) != 1 {
			t.Fatalf("lost or repeated note %d: %q", i, notes)
		}
	}
}

func TestPartialRunMigrationPreservesContext(t *testing.T) {
	for _, column := range []string{"steps", "notes"} {
		t.Run(column, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "puda.db")
			conn, err := sql.Open("sqlite", path)
			if err != nil {
				t.Fatal(err)
			}
			_, err = conn.Exec("CREATE TABLE run(run_id TEXT PRIMARY KEY, protocol_id TEXT, created_at TIMESTAMP, " + column + " TEXT); INSERT INTO run(run_id," + column + ") VALUES ('r','keep me');")
			conn.Close()
			if err != nil {
				t.Fatal(err)
			}
			for i := 0; i < 3; i++ {
				store, err := Connect(path)
				if err != nil {
					t.Fatal(err)
				}
				var steps, notes sql.NullString
				err = store.db.QueryRow("SELECT steps,notes FROM run WHERE run_id='r'").Scan(&steps, &notes)
				store.Disconnect()
				if err != nil {
					t.Fatal(err)
				}
				if column == "steps" && (steps.String != "keep me" || notes.Valid) {
					t.Fatalf("context lost: %v %v", steps, notes)
				}
				if column == "notes" && (notes.String != "keep me" || steps.Valid) {
					t.Fatalf("context lost: %v %v", steps, notes)
				}
			}
		})
	}
}

func TestAppendProtocolNoteValidationAndErrors(t *testing.T) {
	store, err := Connect(filepath.Join(t.TempDir(), "puda.db"))
	if err != nil {
		t.Fatal(err)
	}
	if err := store.EnsureRun("standalone"); err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct{ run, text string }{{"missing", "x"}, {"standalone", "x"}, {"standalone", " \t\n\u2003"}} {
		if _, err := store.AppendProtocolNote(tc.run, tc.text); err == nil {
			t.Fatalf("accepted %+v", tc)
		}
	}
	if _, err := store.db.Exec(`INSERT INTO protocol(protocol_id) VALUES ('p'); INSERT INTO run(run_id,protocol_id) VALUES ('O''Brien','p');`); err != nil {
		t.Fatal(err)
	}
	text := "'; DROP TABLE run; --\n[log](logs/run.txt)"
	if saved, err := store.AppendProtocolNote("O'Brien", text); err != nil || !strings.HasSuffix(saved, text) {
		t.Fatalf("parameterized append: %q %v", saved, err)
	}
	if err := store.Disconnect(); err != nil {
		t.Fatal(err)
	}
	if _, err := store.AppendProtocolNote("O'Brien", "x"); err == nil {
		t.Fatal("closed database accepted note")
	}
}

func TestInsertRunSteps(t *testing.T) {
	store, err := Connect(filepath.Join(t.TempDir(), "puda.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Disconnect()
	if _, err = store.db.Exec("INSERT INTO protocol(protocol_id) VALUES ('p')"); err != nil {
		t.Fatal(err)
	}
	protocol := "p"
	for _, selector := range []string{"", "5-9", "2,4-6", " 2, 4-6 "} {
		var steps *string
		if selector != "" {
			steps = &selector
		}
		if err := store.InsertRun("run"+selector, &protocol, steps); err != nil {
			t.Fatal(err)
		}
		var got sql.NullString
		if err := store.db.QueryRow("SELECT steps FROM run WHERE run_id=?", "run"+selector).Scan(&got); err != nil {
			t.Fatal(err)
		}
		if got.Valid != (steps != nil) || got.String != selector {
			t.Fatalf("got %v for %q", got, selector)
		}
	}
}

func TestRunContextMigration(t *testing.T) {
	for _, old := range []bool{false, true} {
		t.Run(map[bool]string{false: "new", true: "legacy"}[old], func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "puda.db")
			if old {
				conn, err := sql.Open("sqlite", path)
				if err != nil {
					t.Fatal(err)
				}
				_, err = conn.Exec(`CREATE TABLE run (run_id TEXT PRIMARY KEY, protocol_id TEXT, created_at TIMESTAMP); INSERT INTO run VALUES ('legacy', NULL, '2020-01-02');`)
				conn.Close()
				if err != nil {
					t.Fatal(err)
				}
			}
			for i := 0; i < 3; i++ {
				store, err := Connect(path)
				if err != nil {
					t.Fatal(err)
				}
				rows, err := store.Query("SELECT steps, notes FROM run")
				if err != nil {
					store.Disconnect()
					t.Fatal(err)
				}
				rows.Close()
				if old {
					var created string
					var steps, notes sql.NullString
					err = store.db.QueryRow("SELECT CAST(created_at AS TEXT), steps, notes FROM run WHERE run_id='legacy'").Scan(&created, &steps, &notes)
					if err != nil || created != "2020-01-02" || steps.Valid || notes.Valid {
						t.Fatalf("legacy row changed: %q %v %v %v", created, steps, notes, err)
					}
				}
				store.Disconnect()
			}
		})
	}
}
