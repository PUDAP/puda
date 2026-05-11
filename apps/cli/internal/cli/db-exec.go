package cli

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"regexp"
	"strings"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	"github.com/spf13/cobra"
)

// dbExecCmd executes SQL commands on the database
var dbExecCmd = &cobra.Command{
	Use:   "exec [sql-command]",
	Short: "Execute SQL commands on the database",
	Long: `Execute SQL commands on the PUDA database.

The SQL command can be provided as an argument or read from stdin.
Results are displayed in JSON format.

Examples:
  puda db exec "SELECT * FROM protocol LIMIT 5"
  puda db exec "SELECT COUNT(*) FROM run"
  echo "SELECT * FROM sample" | puda db exec`,
	RunE: runDbExec,
}

// validateQuery validates that the SQL command is a query-only operation (DQL).
// Only allows SELECT, WITH (CTEs), and EXPLAIN QUERY PLAN statements.
// Blocks all data modification and schema operations (INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, etc.).
func validateQuery(sqlQuery string) error {
	// Remove leading/trailing whitespace
	sqlQuery = strings.TrimSpace(sqlQuery)
	if sqlQuery == "" {
		return fmt.Errorf("empty SQL query")
	}

	// Remove SQL comments (-- style and /* */ style)
	// First remove /* */ comments
	blockCommentRegex := regexp.MustCompile(`/\*.*?\*/`)
	sqlQuery = blockCommentRegex.ReplaceAllString(sqlQuery, " ")

	// Then remove -- comments (line comments)
	lines := strings.Split(sqlQuery, "\n")
	var cleanedLines []string
	for _, line := range lines {
		if idx := strings.Index(line, "--"); idx != -1 {
			line = line[:idx]
		}
		cleanedLines = append(cleanedLines, line)
	}
	sqlQuery = strings.Join(cleanedLines, " ")
	sqlQuery = strings.TrimSpace(sqlQuery)

	// Convert to uppercase for keyword matching
	upperSQL := strings.ToUpper(sqlQuery)

	// Handle EXPLAIN QUERY PLAN - strip it and check what follows
	explainPattern := regexp.MustCompile(`^\s*EXPLAIN\s+QUERY\s+PLAN\s+`)
	if explainPattern.MatchString(upperSQL) {
		// Remove EXPLAIN QUERY PLAN prefix to check the underlying query
		upperSQL = explainPattern.ReplaceAllString(upperSQL, "")
		upperSQL = strings.TrimSpace(upperSQL)
	}

	// Check for allowed query operations at the start
	// Allow: SELECT, WITH (CTE)
	allowedPatterns := []*regexp.Regexp{
		regexp.MustCompile(`^\s*SELECT\s+`), // SELECT statements
		regexp.MustCompile(`^\s*WITH\s+`),   // Common Table Expressions
	}

	// Check if query starts with an allowed pattern
	isAllowed := false
	for _, pattern := range allowedPatterns {
		if pattern.MatchString(upperSQL) {
			isAllowed = true
			break
		}
	}

	if !isAllowed {
		return fmt.Errorf("only query operations (SELECT, WITH, EXPLAIN QUERY PLAN) are allowed. Data modification and schema operations are not permitted")
	}

	// Block dangerous keywords that appear as standalone statements
	// These should not appear at statement boundaries (start of query or after semicolon)
	blockedKeywords := []string{
		"INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER",
		"TRUNCATE", "REPLACE", "MERGE", "GRANT", "REVOKE",
	}

	// Check for blocked keywords at statement boundaries
	// Look for keywords at the start of the query or after semicolons
	for _, keyword := range blockedKeywords {
		// Pattern matches keyword at start of string or after semicolon/whitespace
		// This catches standalone statements but allows keywords in string literals or comments
		pattern := regexp.MustCompile(`(?:^|;)\s*` + keyword + `\s+`)
		if pattern.MatchString(upperSQL) {
			return fmt.Errorf("data modification operations (%s) are not allowed. Only query operations (SELECT, WITH, EXPLAIN QUERY PLAN) are permitted", keyword)
		}
	}

	return nil
}

// runDbExec executes the SQL command
func runDbExec(cmd *cobra.Command, args []string) error {
	var sqlQuery string

	// Get SQL from argument or stdin
	if len(args) > 0 {
		sqlQuery = strings.Join(args, " ")
	} else {
		// Read from stdin
		stdin, err := io.ReadAll(os.Stdin)
		if err != nil {
			return fmt.Errorf("failed to read from stdin: %w", err)
		}
		sqlQuery = strings.TrimSpace(string(stdin))
	}

	if sqlQuery == "" {
		return fmt.Errorf("no SQL command provided")
	}

	// Validate query - only allow query operations
	if err := validateQuery(sqlQuery); err != nil {
		return err
	}

	// Connect to database
	store, err := db.Connect()
	if err != nil {
		return fmt.Errorf("failed to connect to database: %w", err)
	}
	defer store.Disconnect()

	// Execute as a query (only SELECT, WITH, EXPLAIN QUERY PLAN are allowed)
	rows, err := store.Query(sqlQuery)
	if err != nil {
		return fmt.Errorf("failed to execute SQL query: %w", err)
	}
	defer rows.Close()

	// Check if this is a SELECT query (has result rows)
	columns, err := rows.Columns()
	if err != nil {
		return fmt.Errorf("failed to get columns: %w", err)
	}

	// It's a SELECT query, collect results
	// Prepare for scanning
	values := make([]interface{}, len(columns))
	valuePtrs := make([]interface{}, len(columns))
	for i := range values {
		valuePtrs[i] = &values[i]
	}

	// Collect all rows
	var data []map[string]interface{}
	for rows.Next() {
		if err := rows.Scan(valuePtrs...); err != nil {
			return fmt.Errorf("failed to scan row: %w", err)
		}

		// Create a map for this row
		rowMap := make(map[string]interface{})
		for i, col := range columns {
			val := values[i]
			if val == nil {
				rowMap[col] = nil
			} else {
				// Convert []byte to string for JSON compatibility
				if b, ok := val.([]byte); ok {
					rowMap[col] = string(b)
				} else {
					rowMap[col] = val
				}
			}
		}
		data = append(data, rowMap)
	}

	if err := rows.Err(); err != nil {
		return fmt.Errorf("error iterating rows: %w", err)
	}

	// Build JSON response
	response := map[string]interface{}{
		"status":    "success",
		"row_count": len(data),
		"columns":   columns,
		"data":      data,
	}

	jsonOutput, err := json.MarshalIndent(response, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal JSON: %w", err)
	}
	fmt.Println(string(jsonOutput))

	return nil
}
