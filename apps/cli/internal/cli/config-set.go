package cli

import (
	"fmt"
	"strings"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

const (
	configKeyUserID   = "user.user_id"
	configKeyUsername = "user.username"
)

var settableConfigKeys = []string{
	configKeyUserID,
	configKeyUsername,
}

var getConfigKeys = []string{
	configKeyUsername,
	configKeyUserID,
}

var configGetCmd = &cobra.Command{
	Use:   "get <key>",
	Short: "Get a PUDA CLI configuration value",
	Args:  cobra.ExactArgs(1),
	ValidArgsFunction: func(cmd *cobra.Command, args []string, toComplete string) ([]string, cobra.ShellCompDirective) {
		return getConfigKeys, cobra.ShellCompDirectiveNoFileComp
	},
	RunE: runConfigGet,
}

var configSetCmd = &cobra.Command{
	Use:   "set <user.user_id|user.username> <value>",
	Short: "Set the logged-in user",
	Long:  "Set the user ID or username. Login still generates a user ID when none exists.",
	Args:  cobra.ExactArgs(2),
	ValidArgsFunction: func(cmd *cobra.Command, args []string, toComplete string) ([]string, cobra.ShellCompDirective) {
		if len(args) == 0 {
			return settableConfigKeys, cobra.ShellCompDirectiveNoFileComp
		}
		return nil, cobra.ShellCompDirectiveNoFileComp
	},
	RunE: runConfigSet,
}

func runConfigGet(cmd *cobra.Command, args []string) error {
	key := args[0]

	cfg, err := puda.LoadGlobalConfig()
	if err != nil {
		return err
	}

	switch key {
	case configKeyUsername:
		fmt.Fprintln(cmd.OutOrStdout(), cfg.User.Username)
	case configKeyUserID:
		fmt.Fprintln(cmd.OutOrStdout(), cfg.User.UserID)
	default:
		return fmt.Errorf("unknown config key %q; available keys: %v", key, getConfigKeys)
	}

	return nil
}

func runConfigSet(cmd *cobra.Command, args []string) error {
	key, value := args[0], strings.TrimSpace(args[1])
	switch key {
	case configKeyUserID, configKeyUsername:
	default:
		return fmt.Errorf("unknown config key %q; settable keys: %v", key, settableConfigKeys)
	}

	if (key == configKeyUserID || key == configKeyUsername) && value == "" {
		return fmt.Errorf("%s cannot be empty", key)
	}

	cfg, err := puda.LoadGlobalConfig()
	if err != nil {
		return err
	}

	switch key {
	case configKeyUserID:
		cfg.User.UserID = value
	case configKeyUsername:
		cfg.User.Username = value
	}

	if err := puda.SaveGlobalConfig(cfg); err != nil {
		return err
	}

	fmt.Fprintf(cmd.OutOrStdout(), "%s=%s\n", key, value)
	return nil
}
