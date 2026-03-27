package cli

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/google/uuid"
	"github.com/spf13/cobra"
)

var (
	projectName        string
	projectDescription string
)

// initCmd initializes a new PUDA project
var initCmd = &cobra.Command{
	Use:   "init [path]",
	Short: "Initialize a new PUDA project",
	Long: `Initialize a new PUDA project.

This command has the same behavior as "puda project create".
It initializes the workspace config and database, creates a new project UUID,
and scaffolds the project root with config.json, puda.db, and project.md.

Examples:
  puda init --name "Test Project"
  puda init ./my-project --name "Test Project" --description "Initial project"
`,
	RunE: runProjectCreate,
	Args: cobra.MaximumNArgs(1),
}

func init() {
	initCmd.Flags().StringVar(&projectName, "name", "", "Project name (required)")
	initCmd.Flags().StringVar(&projectDescription, "description", "", "Project description")
	initCmd.MarkFlagRequired("name")
}

func runProjectCreate(cmd *cobra.Command, args []string) error {
	targetDir, err := resolveProjectTargetDir(args)
	if err != nil {
		return err
	}

	cfg, err := loadOrCreateProjectConfig(puda.ProjectConfigPathForDir(targetDir), targetDir)
	if err != nil {
		return err
	}

	projectID := uuid.NewString()
	cfg.ProjectID = projectID
	if err := writeProjectConfig(targetDir, cfg); err != nil {
		return fmt.Errorf("failed to write project config file: %w", err)
	}

	originalDir, err := os.Getwd()
	if err != nil {
		return fmt.Errorf("failed to get current directory: %w", err)
	}
	defer os.Chdir(originalDir)

	if err := os.Chdir(targetDir); err != nil {
		return fmt.Errorf("failed to change to target directory: %w", err)
	}

	store, err := db.Connect()
	if err != nil {
		return fmt.Errorf("failed to initialize database: %w", err)
	}
	defer store.Disconnect()

	projectMarkdownPath := filepath.Join(targetDir, "project.md")
	projectMarkdown := fmt.Sprintf(`# Project


project_id: %s

name: %s

description: %s


## Protocols


## History


## Logs


`, projectID, projectName, projectDescription)

	if err := os.WriteFile(projectMarkdownPath, []byte(projectMarkdown), 0o644); err != nil {
		return fmt.Errorf("failed to write project markdown: %w", err)
	}

	if err := store.InsertProject(projectID, projectName, projectDescription); err != nil {
		return err
	}

	fmt.Fprintf(cmd.OutOrStdout(), "Project created: %s\n", projectID)
	return nil
}

func resolveProjectTargetDir(args []string) (string, error) {
	var targetDir string
	if len(args) > 0 && args[0] != "" {
		targetDir = args[0]
		if targetDir == "." {
			var err error
			targetDir, err = os.Getwd()
			if err != nil {
				return "", fmt.Errorf("failed to get current directory: %w", err)
			}
		}
	} else {
		var err error
		targetDir, err = os.Getwd()
		if err != nil {
			return "", fmt.Errorf("failed to get current directory: %w", err)
		}
	}

	targetDir, err := filepath.Abs(targetDir)
	if err != nil {
		return "", fmt.Errorf("failed to resolve target directory: %w", err)
	}

	if info, err := os.Stat(targetDir); err != nil {
		if os.IsNotExist(err) {
			return "", fmt.Errorf("target directory does not exist: %s", targetDir)
		}
		return "", fmt.Errorf("failed to access target directory: %w", err)
	} else if !info.IsDir() {
		return "", fmt.Errorf("target path is not a directory: %s", targetDir)
	}

	return targetDir, nil
}

func loadOrCreateProjectConfig(projectConfigPath, targetDir string) (*puda.ProjectConfig, error) {
	// check if the project config file exists
	configPaths := []string{projectConfigPath, filepath.Join(targetDir, puda.LegacyProjectConfigFileName)}
	for _, configPath := range configPaths {
		if _, err := os.Stat(configPath); err == nil {
			data, err := os.ReadFile(configPath)
			if err != nil {
				return nil, fmt.Errorf("failed to read project config file: %w", err)
			}

			var cfg puda.ProjectConfig
			if err := json.Unmarshal(data, &cfg); err != nil {
				return nil, fmt.Errorf("failed to parse project config file: %w", err)
			}

			if cfg.ProjectRoot == "" {
				cfg.ProjectRoot = targetDir
			}
			if cfg.Database.Path == "" {
				cfg.Database.Path = "puda.db"
			}
			if cfg.Endpoints.NATS == "" {
				cfg.Endpoints.NATS = "nats://100.109.131.12:4222,nats://100.109.131.12:4223,nats://100.109.131.12:4224"
			}

			return &cfg, nil
		} else if !os.IsNotExist(err) {
			return nil, fmt.Errorf("failed to access project config file: %w", err)
		}
	}

	// create a new project config
	globalConfigPath, err := puda.GlobalConfigPath()
	if err != nil {
		return nil, fmt.Errorf("failed to determine global config path: %w", err)
	}

	if _, err := os.Stat(globalConfigPath); os.IsNotExist(err) {
		return nil, fmt.Errorf("user not logged in. Please run 'puda login' first")
	}

	globalConfig, err := puda.LoadGlobalConfig()
	if err != nil {
		return nil, fmt.Errorf("failed to load global config: %w", err)
	}

	if globalConfig.User.Username == "" {
		return nil, fmt.Errorf("username is missing in global config. Please run 'puda login' first")
	}
	if globalConfig.User.UserID == "" {
		return nil, fmt.Errorf("user ID is missing in global config. Please run 'puda login' first")
	}

	var cfg puda.ProjectConfig
	cfg.User.Username = globalConfig.User.Username
	cfg.User.UserID = globalConfig.User.UserID
	cfg.Endpoints.NATS = "nats://100.109.131.12:4222,nats://100.109.131.12:4223,nats://100.109.131.12:4224"
	cfg.Database.Path = "puda.db"
	cfg.ProjectRoot = targetDir

	return &cfg, nil
}

func writeProjectConfig(targetDir string, cfg *puda.ProjectConfig) error {
	cfg.ProjectRoot = targetDir

	configData, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal config: %w", err)
	}

	projectConfigPath := puda.ProjectConfigPathForDir(targetDir)
	if err := os.WriteFile(projectConfigPath, configData, 0o644); err != nil {
		return err
	}

	return nil
}
