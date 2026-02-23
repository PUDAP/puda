package cli

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

// initCmd initializes a new PUDA project
var initCmd = &cobra.Command{
	Use:   "init [path]",
	Short: "Initialize a new PUDA project",
	Long: `Initialize a new PUDA project.

This command sets up a new PUDA project in the specified directory (or current directory if not specified).
It will:
  - Initialize the database schema
  - Install OpenSkills in the project (puda skills install)
  - Set up project structure (more features coming soon)

The database path must be set in your config before running this command.
Use 'puda config edit' to set the database.path if needed.

Examples:
  puda init              # Initialize in current directory
  puda init .            # Initialize in current directory
  puda init ./my-project # Initialize in ./my-project directory
`,
	RunE:         runInit,
	Args:         cobra.MaximumNArgs(1),
	SilenceUsage: true,
}

// runInit executes the project initialization
func runInit(cmd *cobra.Command, args []string) error {
	// Determine target directory
	var targetDir string
	if len(args) > 0 && args[0] != "" {
		targetDir = args[0]
		// Handle "." as current directory
		if targetDir == "." {
			var err error
			targetDir, err = os.Getwd()
			if err != nil {
				return fmt.Errorf("failed to get current directory: %w", err)
			}
		}
	} else {
		var err error
		targetDir, err = os.Getwd()
		if err != nil {
			return fmt.Errorf("failed to get current directory: %w", err)
		}
	}

	// Validate and resolve the target directory
	targetDir, err := filepath.Abs(targetDir)
	if err != nil {
		return fmt.Errorf("failed to resolve target directory: %w", err)
	}

	// Check if target directory exists
	if info, err := os.Stat(targetDir); err != nil {
		if os.IsNotExist(err) {
			return fmt.Errorf("target directory does not exist: %s", targetDir)
		}
		return fmt.Errorf("failed to access target directory: %w", err)
	} else if !info.IsDir() {
		return fmt.Errorf("target path is not a directory: %s", targetDir)
	}

	// Check if already in a project (check in target directory)
	projectConfigPath := filepath.Join(targetDir, "puda.config")
	isExistingProject := false
	if _, err := os.Stat(projectConfigPath); err == nil {
		isExistingProject = true
	}

	// Check if user is logged in (global config exists)
	globalConfigPath, err := puda.GlobalConfigPath()
	if err != nil {
		return fmt.Errorf("failed to determine global config path: %w", err)
	}

	if _, err := os.Stat(globalConfigPath); os.IsNotExist(err) {
		return fmt.Errorf("user not logged in. Please run 'puda login' first")
	}

	// Load global config to get username and user_id
	globalConfig, err := puda.LoadGlobalConfig()
	if err != nil {
		return fmt.Errorf("failed to load global config: %w", err)
	}

	// Ensure username and user_id are present in global config
	if globalConfig.User.Username == "" {
		return fmt.Errorf("username is missing in global config. Please run 'puda login' first")
	}
	if globalConfig.User.UserID == "" {
		return fmt.Errorf("user ID is missing in global config. Please run 'puda login' first")
	}

	// Create or update project config file using username and user_id from global config
	// Set project-specific defaults (relative to project directory)
	var projectConfig puda.ProjectConfig
	projectConfig.User.Username = globalConfig.User.Username
	projectConfig.User.UserID = globalConfig.User.UserID
	projectConfig.Endpoints.NATS = "nats://100.109.131.12:4222,nats://100.109.131.12:4223,nats://100.109.131.12:4224"
	projectConfig.Database.Path = "puda.db"
	projectConfig.Logs.Dir = "./logs"
	configData, err := json.MarshalIndent(projectConfig, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal config: %w", err)
	}

	if err := os.WriteFile(projectConfigPath, configData, 0644); err != nil {
		return fmt.Errorf("failed to write project config file: %w", err)
	}

	// Change to target directory for database initialization
	originalDir, err := os.Getwd()
	if err != nil {
		return fmt.Errorf("failed to get current directory: %w", err)
	}
	defer os.Chdir(originalDir) // Restore original directory

	if err := os.Chdir(targetDir); err != nil {
		return fmt.Errorf("failed to change to target directory: %w", err)
	}

	// Initialize database
	store, err := db.Connect()
	if err != nil {
		return fmt.Errorf("failed to initialize database: %w", err)
	}
	defer store.Disconnect()

	// Install skills in the project directory (runs in targetDir via Chdir above)
	if err := installSkillsInCwd(); err != nil {
		return fmt.Errorf("failed to install skills: %w", err)
	}

	// TODO: Add more initialization steps here
	// - Create project directory structure
	// - Set up templates, etc.

	if isExistingProject {
		fmt.Fprintf(cmd.OutOrStdout(), "Reinitialized puda project in %s\n", targetDir)
	} else {
		fmt.Fprintf(cmd.OutOrStdout(), "Initialized new puda project in %s\n", targetDir)
	}
	return nil
}
