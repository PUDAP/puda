package db

import (
	"database/sql"
	_ "embed"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
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

// Connect initializes the database connection using the path from the PUDA project configuration.
// The database file will be automatically created if it doesn't exist.
// Requires a project-level puda.config file (run 'puda init' to create it).
func Connect() (*Store, error) {
	cfg, err := puda.LoadProjectConfig()
	if err != nil {
		return nil, err
	}

	dbPath := cfg.Database.Path
	if dbPath == "" {
		return nil, fmt.Errorf("database path is not set in config, please run 'puda config edit' to set database.path")
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

// initSchema creates all tables if they don't exist.
func (s *Store) initSchema() error {
	if _, err := s.db.Exec(initSQL); err != nil {
		return fmt.Errorf("failed to create schema: %w", err)
	}
	return nil
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

// InsertRun inserts a new run into the run table.
func (s *Store) InsertRun(runID string, protocolID *string) error {
	query := `
		INSERT INTO run (run_id, protocol_id, created_at)
		VALUES (?, ?, ?)
	`

	_, err := s.db.Exec(query, runID, protocolID, time.Now())
	if err != nil {
		return fmt.Errorf("failed to insert run: %w", err)
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
