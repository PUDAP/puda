package cli

import (
	"fmt"
	"os"
	"strings"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

const (
	projectConfigKeyUserID      = "user.user_id"
	projectConfigKeyUsername    = "user.username"
	projectConfigKeyDatabase    = "database.path"
	projectConfigKeyProjectID   = "project_id"
	projectConfigKeyProjectRoot = "project_root"
)

var projectConfigKeys = []string{
	projectConfigKeyUserID,
	projectConfigKeyUsername,
	projectConfigKeyDatabase,
	projectConfigKeyProjectID,
	projectConfigKeyProjectRoot,
}

var projectConfigCmd = &cobra.Command{
	Use:   "config",
	Short: "Manage project config",
	Long:  "Manage the project file (puda.config) in the current project.",
}

var projectConfigListCmd = &cobra.Command{
	Use:   "list",
	Short: "List project config",
	Args:  cobra.NoArgs,
	RunE:  runProjectConfigList,
}

var projectConfigGetCmd = &cobra.Command{
	Use:   "get <key>",
	Short: "Get a project config value",
	Args:  cobra.ExactArgs(1),
	ValidArgsFunction: func(cmd *cobra.Command, args []string, toComplete string) ([]string, cobra.ShellCompDirective) {
		return projectConfigKeys, cobra.ShellCompDirectiveNoFileComp
	},
	RunE: runProjectConfigGet,
}

var projectConfigSetCmd = &cobra.Command{
	Use:   "set <key> <value>",
	Short: "Set a project config value",
	Args:  cobra.ExactArgs(2),
	ValidArgsFunction: func(cmd *cobra.Command, args []string, toComplete string) ([]string, cobra.ShellCompDirective) {
		if len(args) == 0 {
			return projectConfigKeys, cobra.ShellCompDirectiveNoFileComp
		}
		return nil, cobra.ShellCompDirectiveNoFileComp
	},
	RunE: runProjectConfigSet,
}

var projectConfigEditCmd = &cobra.Command{
	Use:   "edit",
	Short: "Edit project config",
	Long:  "Open puda.config in a terminal editor.",
	Args:  cobra.NoArgs,
	RunE:  runProjectConfigEdit,
}

func init() {
	projectConfigCmd.AddCommand(projectConfigListCmd)
	projectConfigCmd.AddCommand(projectConfigGetCmd)
	projectConfigCmd.AddCommand(projectConfigSetCmd)
	projectConfigCmd.AddCommand(projectConfigEditCmd)
	projectCmd.AddCommand(projectConfigCmd)
}

func runProjectConfigList(cmd *cobra.Command, args []string) error {
	cfg, err := puda.LoadProjectConfig()
	if err != nil {
		return err
	}
	printProjectConfig(cmd, cfg)
	return nil
}

func printProjectConfig(cmd *cobra.Command, cfg *puda.ProjectConfig) {
	fmt.Fprintf(cmd.OutOrStdout(), "user.user_id=%s\n", cfg.User.UserID)
	fmt.Fprintf(cmd.OutOrStdout(), "user.username=%s\n", cfg.User.Username)
	fmt.Fprintf(cmd.OutOrStdout(), "database.path=%s\n", cfg.Database.Path)
	fmt.Fprintf(cmd.OutOrStdout(), "project_id=%s\n", cfg.ProjectID)
	fmt.Fprintf(cmd.OutOrStdout(), "project_root=%s\n", cfg.ProjectRoot)
}

func runProjectConfigGet(cmd *cobra.Command, args []string) error {
	cfg, err := puda.LoadProjectConfig()
	if err != nil {
		return err
	}
	value, err := projectConfigValue(cfg, args[0])
	if err != nil {
		return err
	}
	fmt.Fprintln(cmd.OutOrStdout(), value)
	return nil
}

func runProjectConfigSet(cmd *cobra.Command, args []string) error {
	key, value := args[0], strings.TrimSpace(args[1])
	if value == "" {
		return fmt.Errorf("%s cannot be empty", key)
	}
	cfg, err := puda.LoadProjectConfig()
	if err != nil {
		return err
	}
	if err := setProjectConfigValue(cfg, key, value); err != nil {
		return err
	}
	if err := puda.SaveProjectConfig(cfg); err != nil {
		return err
	}
	fmt.Fprintf(cmd.OutOrStdout(), "%s=%s\n", key, value)
	return nil
}

func runProjectConfigEdit(cmd *cobra.Command, args []string) error {
	configPath, err := puda.ProjectConfigPath()
	if err != nil {
		return err
	}
	if configPath == "" {
		return fmt.Errorf("project puda.config file not found in current directory. Please run 'puda init' to create it first")
	}
	if _, err := os.Stat(configPath); err != nil {
		return fmt.Errorf("failed to stat project config %s: %w", configPath, err)
	}
	fmt.Fprintf(cmd.OutOrStdout(), "Opening %s\n", configPath)
	if err := openInEditor(configPath); err != nil {
		return fmt.Errorf("failed to open editor: %w", err)
	}
	return nil
}

func projectConfigValue(cfg *puda.ProjectConfig, key string) (string, error) {
	switch key {
	case projectConfigKeyUserID:
		return cfg.User.UserID, nil
	case projectConfigKeyUsername:
		return cfg.User.Username, nil
	case projectConfigKeyDatabase:
		return cfg.Database.Path, nil
	case projectConfigKeyProjectID:
		return cfg.ProjectID, nil
	case projectConfigKeyProjectRoot:
		return cfg.ProjectRoot, nil
	default:
		return "", fmt.Errorf("unknown config key %q; available keys: %v", key, projectConfigKeys)
	}
}

func setProjectConfigValue(cfg *puda.ProjectConfig, key, value string) error {
	switch key {
	case projectConfigKeyUserID:
		cfg.User.UserID = value
	case projectConfigKeyUsername:
		cfg.User.Username = value
	case projectConfigKeyDatabase:
		cfg.Database.Path = value
	case projectConfigKeyProjectID:
		cfg.ProjectID = value
	case projectConfigKeyProjectRoot:
		cfg.ProjectRoot = value
	default:
		return fmt.Errorf("unknown config key %q; settable keys: %v", key, projectConfigKeys)
	}
	return nil
}
