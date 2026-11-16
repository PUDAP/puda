package db

import (
	"context"
	"database/sql"
	_ "embed"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/google/uuid"
	_ "modernc.org/sqlite"
)

//go:embed init.sql
var initSQL string

// Store wraps a SQLite database connection and provides methods for database operations.
type Store struct {
	db *sql.DB
}

// Connect initializes the database connection using an explicit SQLite path when
// provided, or falls back to the PUDA project configuration.
// Relative paths are resolved from the current working directory.
func Connect(dbPathOverride ...string) (*Store, error) {
	dbPath := ""
	if len(dbPathOverride) > 0 && strings.TrimSpace(dbPathOverride[0]) != "" {
		dbPath = dbPathOverride[0]
	} else {
		cfg, err := puda.LoadProjectConfig()
		if err != nil {
			return nil, err
		}
		dbPath = cfg.Database.Path
	}

	if dbPath == "" {
		return nil, fmt.Errorf("database path is required")
	}

	// Ensure the directory exists (SQLite creates the file but not parent directories)
	if dir := filepath.Dir(dbPath); dir != "." && dir != "" {
		if err := os.MkdirAll(dir, 0755); err != nil {
			return nil, fmt.Errorf("failed to create database directory: %w", err)
		}
	}

	// Open or create the database file
	conn, err := sql.Open("sqlite", dbPath)
	if err != nil {
		return nil, fmt.Errorf("failed to open database: %w", err)
	}

	// Keep connection-local pragmas effective for every operation and allow
	// separate CLI processes to wait for concurrent SQLite writers.
	conn.SetMaxOpenConns(1)
	if _, err := conn.Exec("PRAGMA busy_timeout = 5000"); err != nil {
		conn.Close()
		return nil, fmt.Errorf("failed to set busy timeout: %w", err)
	}

	// Enable foreign keys
	if _, err := conn.Exec("PRAGMA foreign_keys = ON"); err != nil {
		conn.Close()
		return nil, fmt.Errorf("failed to enable foreign keys: %w", err)
	}

	store := &Store{db: conn}

	// Initialize schema if database is new
	if err := store.initSchema(); err != nil {
		conn.Close()
		return nil, fmt.Errorf("failed to initialize schema: %w", err)
	}

	return store, nil
}

// Disconnect closes the database connection.
func (s *Store) Disconnect() error {
	if s.db != nil {
		return s.db.Close()
	}
	return nil
}

// initSchema creates tables and repeat-safely upgrades existing run rows.
func (s *Store) initSchema() error {
	ctx := context.Background()
	conn, err := s.db.Conn(ctx)
	if err != nil {
		return err
	}
	defer conn.Close()
	// Serialize schema inspection and ALTER across concurrent CLI invocations.
	if _, err := conn.ExecContext(ctx, "BEGIN IMMEDIATE"); err != nil {
		return err
	}
	defer conn.ExecContext(ctx, "ROLLBACK")
	if _, err := conn.ExecContext(ctx, initSQL); err != nil {
		return fmt.Errorf("failed to create schema: %w", err)
	}
	for _, column := range []string{"steps", "notes"} {
		var count int
		if err := conn.QueryRowContext(ctx, "SELECT COUNT(*) FROM pragma_table_info('run') WHERE name = ?", column).Scan(&count); err != nil {
			return err
		}
		if count == 0 {
			// column is exclusively from the fixed list above, never user input.
			if _, err := conn.ExecContext(ctx, "ALTER TABLE run ADD COLUMN "+column+" TEXT"); err != nil {
				return fmt.Errorf("failed to add run.%s: %w", column, err)
			}
		}
	}
	_, err = conn.ExecContext(ctx, "COMMIT")
	return err
}

// marshalJSON safely marshals a value to JSON string, handling nil values.
func marshalJSON(v interface{}) (string, error) {
	if v == nil {
		return "", nil
	}
	bytes, err := json.Marshal(v)
	if err != nil {
		return "", fmt.Errorf("failed to marshal JSON: %w", err)
	}
	return string(bytes), nil
}

// InsertProject inserts a new project into the project table.
func (s *Store) InsertProject(projectID, name, description string) error {
	query := `
		INSERT INTO project (project_id, name, description, created_at)
		VALUES (?, ?, ?, ?)
	`

	_, err := s.db.Exec(query, projectID, name, description, time.Now())
	if err != nil {
		return fmt.Errorf("failed to insert project: %w", err)
	}

	return nil
}

// InsertProtocol inserts a new protocol into the protocol table.
func (s *Store) InsertProtocol(protocolFile puda.ProtocolFile) error {
	commandsJSON, err := marshalJSON(protocolFile.Commands)
	if err != nil {
		return fmt.Errorf("failed to marshal commands: %w", err)
	}

	query := `
		INSERT OR IGNORE INTO protocol (protocol_id, user_id, username, description, commands, created_at)
		VALUES (?, ?, ?, ?, ?, ?)
	`

	_, err = s.db.Exec(query,
		protocolFile.ProtocolID,
		protocolFile.UserID,
		protocolFile.Username,
		protocolFile.Description,
		commandsJSON,
		time.Now(),
	)
	if err != nil {
		return fmt.Errorf("failed to insert protocol: %w", err)
	}

	return nil
}

// InsertRun inserts a new run; nil steps means the full protocol.
func (s *Store) InsertRun(runID string, protocolID *string, stepsExpr ...*string) error {
	var steps *string
	if len(stepsExpr) > 0 {
		steps = stepsExpr[0]
	}
	query := `
		INSERT INTO run (run_id, protocol_id, created_at, steps)
		VALUES (?, ?, ?, ?)
	`

	_, err := s.db.Exec(query, runID, protocolID, time.Now(), steps)
	if err != nil {
		return fmt.Errorf("failed to insert run: %w", err)
	}

	return nil
}

// AppendProtocolNote atomically appends verbatim text to an existing protocol run.
// The returned notes are read back in the same transaction as the append.
func (s *Store) AppendProtocolNote(runID, text string) (string, error) {
	if strings.TrimSpace(text) == "" {
		return "", fmt.Errorf("note text cannot be blank")
	}
	entry := "[" + time.Now().UTC().Format(time.RFC3339Nano) + "] " + text
	tx, err := s.db.Begin()
	if err != nil {
		return "", err
	}
	defer tx.Rollback()
	result, err := tx.Exec(`UPDATE run
		SET notes = CASE WHEN notes IS NULL OR notes = '' THEN ? ELSE notes || char(10) || char(10) || ? END
		WHERE run_id = ? AND EXISTS (SELECT 1 FROM protocol WHERE protocol.protocol_id = run.protocol_id)`, entry, entry, runID)
	if err != nil {
		return "", fmt.Errorf("failed to append note: %w", err)
	}
	count, err := result.RowsAffected()
	if err != nil {
		return "", err
	}
	if count != 1 {
		return "", fmt.Errorf("run %q does not exist or is not associated with a protocol", runID)
	}
	var notes string
	if err := tx.QueryRow("SELECT notes FROM run WHERE run_id = ?", runID).Scan(&notes); err != nil {
		return "", fmt.Errorf("failed to read saved notes: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return "", err
	}
	return notes, nil
}

// EnsureRun creates a standalone machine run if it does not already exist.
// Existing run metadata and associated records are preserved.
func (s *Store) EnsureRun(runID string) error {
	_, err := s.db.Exec(`
		INSERT INTO run (run_id, protocol_id, created_at)
		VALUES (?, NULL, ?)
		ON CONFLICT(run_id) DO NOTHING
	`, runID, time.Now())
	if err != nil {
		return fmt.Errorf("failed to ensure run: %w", err)
	}
	return nil
}

// InsertSample inserts a new sample into the sample table.
func (s *Store) InsertSample(runID string, dataPayload interface{}) (string, error) {
	sampleID := uuid.New().String()

	payloadJSON, err := marshalJSON(dataPayload)
	if err != nil {
		return "", fmt.Errorf("failed to marshal data_payload: %w", err)
	}

	query := `
		INSERT INTO sample (sample_id, run_id, data_payload, created_at)
		VALUES (?, ?, ?, ?)
	`

	_, err = s.db.Exec(query, sampleID, runID, payloadJSON, time.Now())
	if err != nil {
		return "", fmt.Errorf("failed to insert sample: %w", err)
	}

	return sampleID, nil
}

// InsertMeasurement inserts a new measurement into the measurement table.
func (s *Store) InsertMeasurement(sampleID string, dataPayload interface{}) (string, error) {
	measurementID := uuid.New().String()

	payloadJSON, err := marshalJSON(dataPayload)
	if err != nil {
		return "", fmt.Errorf("failed to marshal data_payload: %w", err)
	}

	query := `
		INSERT INTO measurement (measurement_id, sample_id, data_payload, created_at)
		VALUES (?, ?, ?, ?)
	`

	_, err = s.db.Exec(query, measurementID, sampleID, payloadJSON, time.Now())
	if err != nil {
		return "", fmt.Errorf("failed to insert measurement: %w", err)
	}

	return measurementID, nil
}

// InsertCommandLog inserts a new command log entry into the command_log table.
func (s *Store) InsertCommandLog(message *puda.NATSMessage, commandType string) error {
	var runID interface{}
	if message.Header.RunID != nil && *message.Header.RunID != "" {
		runID = *message.Header.RunID
	} else {
		runID = nil
	}
	machineID := message.Header.MachineID

	var stepNumber *int
	var commandName *string
	if message.Command != nil {
		stepNumber = &message.Command.StepNumber
		commandName = &message.Command.Name
	}

	payloadJSON, err := marshalJSON(message)
	if err != nil {
		return fmt.Errorf("failed to marshal message: %w", err)
	}

	query := `
		INSERT OR IGNORE INTO command_log (run_id, step_number, command_name, payload, machine_id, command_type, created_at)
		VALUES (?, ?, ?, ?, ?, ?, ?)
	`

	_, err = s.db.Exec(query, runID, stepNumber, commandName, payloadJSON, machineID, commandType, time.Now())
	if err != nil {
		return fmt.Errorf("failed to insert command_log: %w", err)
	}

	return nil
}

// Query executes a SQL query that returns rows (e.g., SELECT).
func (s *Store) Query(query string) (*sql.Rows, error) {
	return s.db.Query(query)
}

// ExecSQL executes a SQL command that doesn't return rows (e.g., INSERT, UPDATE, DELETE).
func (s *Store) ExecSQL(query string) (sql.Result, error) {
	return s.db.Exec(query)
}

// GetInitSQL returns the initialization SQL schema.
func GetInitSQL() string {
	return initSQL
}
