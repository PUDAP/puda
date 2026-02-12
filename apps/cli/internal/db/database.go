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

// Database wraps a SQLite database connection and provides methods for database operations
type Database struct {
	db *sql.DB
}

// Connect connects to a SQLite database using the path from the project PUDA configuration
// The database file will be automatically created if it doesn't exist
// Requires a project-level puda.config file (run 'puda init' to create it)
func Connect() (*Database, error) {
	// Load project config (required for database operations)
	cfg, err := puda.LoadProjectConfig()
	if err != nil {
		return nil, fmt.Errorf("not in a PUDA project: %w", err)
	}

	// Get database path from config, require it to be set
	dbPath := cfg.Database.Path
	if dbPath == "" {
		return nil, fmt.Errorf("database path is not set in config, please run 'puda config edit' to set database.path")
	}

	// Ensure the directory exists (SQLite creates the file but not parent directories)
	dir := filepath.Dir(dbPath)
	if dir != "." && dir != "" {
		if err := os.MkdirAll(dir, 0755); err != nil {
			return nil, fmt.Errorf("failed to create database directory: %w", err)
		}
	}

	// Open or create the database file (SQLite automatically creates the file if it doesn't exist)
	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		return nil, fmt.Errorf("failed to open database: %w", err)
	}

	// Enable foreign keys
	if _, err := db.Exec("PRAGMA foreign_keys = ON"); err != nil {
		db.Close()
		return nil, fmt.Errorf("failed to enable foreign keys: %w", err)
	}

	database := &Database{db: db}

	// Initialize schema if database is new
	if err := database.initSchema(); err != nil {
		db.Close()
		return nil, fmt.Errorf("failed to initialize schema: %w", err)
	}

	return database, nil
}

// Close closes the database connection
func (d *Database) Close() error {
	if d.db != nil {
		return d.db.Close()
	}
	return nil
}

// initSchema creates all tables if they don't exist
func (d *Database) initSchema() error {
	if _, err := d.db.Exec(initSQL); err != nil {
		return fmt.Errorf("failed to create schema: %w", err)
	}

	return nil
}

// InsertProtocol inserts a new protocol into the protocol table
func (d *Database) InsertProtocol(userID, username, description string, commands interface{}) (string, error) {
	protocolID := uuid.New().String()

	// Serialize commands to JSON
	commandsJSON, err := json.Marshal(commands)
	if err != nil {
		return "", fmt.Errorf("failed to marshal commands: %w", err)
	}

	query := `
		INSERT INTO protocol (protocol_id, user_id, username, description, commands, created_at)
		VALUES (?, ?, ?, ?, ?, ?)
	`

	_, err = d.db.Exec(query, protocolID, userID, username, description, string(commandsJSON), time.Now())
	if err != nil {
		return "", fmt.Errorf("failed to insert protocol: %w", err)
	}

	return protocolID, nil
}

// InsertRun inserts a new run into the run table
func (d *Database) InsertRun(protocolID *string, machineID string, dataPayload interface{}) (string, error) {
	runID := uuid.New().String()

	// Serialize data_payload to JSON
	var payloadJSON string
	if dataPayload != nil {
		payloadBytes, err := json.Marshal(dataPayload)
		if err != nil {
			return "", fmt.Errorf("failed to marshal data_payload: %w", err)
		}
		payloadJSON = string(payloadBytes)
	}

	query := `
		INSERT INTO run (run_id, protocol_id, machine_id, data_payload, created_at)
		VALUES (?, ?, ?, ?, ?)
	`

	_, err := d.db.Exec(query, runID, protocolID, machineID, payloadJSON, time.Now())
	if err != nil {
		return "", fmt.Errorf("failed to insert run: %w", err)
	}

	return runID, nil
}

// InsertSample inserts a new sample into the sample table
func (d *Database) InsertSample(runID string, dataPayload interface{}) (string, error) {
	sampleID := uuid.New().String()

	// Serialize data_payload to JSON
	var payloadJSON string
	if dataPayload != nil {
		payloadBytes, err := json.Marshal(dataPayload)
		if err != nil {
			return "", fmt.Errorf("failed to marshal data_payload: %w", err)
		}
		payloadJSON = string(payloadBytes)
	}

	query := `
		INSERT INTO sample (sample_id, run_id, data_payload, created_at)
		VALUES (?, ?, ?, ?)
	`

	_, err := d.db.Exec(query, sampleID, runID, payloadJSON, time.Now())
	if err != nil {
		return "", fmt.Errorf("failed to insert sample: %w", err)
	}

	return sampleID, nil
}

// InsertMeasurement inserts a new measurement into the measurement table
func (d *Database) InsertMeasurement(sampleID string, dataPayload interface{}) (string, error) {
	measurementID := uuid.New().String()

	// Serialize data_payload to JSON
	var payloadJSON string
	if dataPayload != nil {
		payloadBytes, err := json.Marshal(dataPayload)
		if err != nil {
			return "", fmt.Errorf("failed to marshal data_payload: %w", err)
		}
		payloadJSON = string(payloadBytes)
	}

	query := `
		INSERT INTO measurement (measurement_id, sample_id, data_payload, created_at)
		VALUES (?, ?, ?, ?)
	`

	_, err := d.db.Exec(query, measurementID, sampleID, payloadJSON, time.Now())
	if err != nil {
		return "", fmt.Errorf("failed to insert measurement: %w", err)
	}

	return measurementID, nil
}

// InsertCommandLog inserts a new command log entry into the command_log table
func (d *Database) InsertCommandLog(runID string, stepNumber int, payload interface{}, machineID, commandType string) (int64, error) {
	// Serialize payload to JSON
	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		return 0, fmt.Errorf("failed to marshal payload: %w", err)
	}

	query := `
		INSERT INTO command_log (run_id, step_number, payload, machine_id, command_type, created_at)
		VALUES (?, ?, ?, ?, ?, ?)
	`

	result, err := d.db.Exec(query, runID, stepNumber, string(payloadBytes), machineID, commandType, time.Now())
	if err != nil {
		return 0, fmt.Errorf("failed to insert command_log: %w", err)
	}

	commandLogID, err := result.LastInsertId()
	if err != nil {
		return 0, fmt.Errorf("failed to get last insert id: %w", err)
	}

	return commandLogID, nil
}
