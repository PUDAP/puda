package cli

import (
	"fmt"
	"strings"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

const (
	configKeyNATSServers    = "nats_servers"
	configKeyGatewayServers = "gateway_servers"
	configKeyUserID         = "user.user_id"
	configKeyUsername       = "user.username"
)

var settableConfigKeys = []string{
	configKeyNATSServers,
	configKeyGatewayServers,
	configKeyUserID,
	configKeyUsername,
}

var getConfigKeys = []string{
	configKeyNATSServers,
	configKeyGatewayServers,
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
	Use:   "set <nats_servers|gateway_servers|user.user_id|user.username> <value>",
	Short: "Set a PUDA CLI configuration value",
	Long:  "Set NATS server URLs, gateway remote-cluster URLs, user ID, or username. Login still generates a user ID when none exists; use this command to change identity afterward.",
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
	case configKeyNATSServers:
		fmt.Fprintln(cmd.OutOrStdout(), cfg.NATSServers)
	case configKeyGatewayServers:
		fmt.Fprintln(cmd.OutOrStdout(), cfg.GatewayServers)
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
	case configKeyNATSServers, configKeyGatewayServers, configKeyUserID, configKeyUsername:
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
	case configKeyNATSServers:
		cfg.NATSServers = value
	case configKeyGatewayServers:
		cfg.GatewayServers = value
	case configKeyUserID:
		cfg.User.UserID = value
	case configKeyUsername:
		cfg.User.Username = value
	}

	if err := puda.SaveGlobalConfig(cfg); err != nil {
		return err
	}

	if key == configKeyUserID || key == configKeyUsername {
		if err := syncProjectUser(func(user *puda.ConfigUser) {
			if key == configKeyUserID {
				user.UserID = value
			} else {
				user.Username = value
			}
		}); err != nil {
			return err
		}
	}

	fmt.Fprintf(cmd.OutOrStdout(), "%s=%s\n", key, value)
	return nil
}

func syncProjectUser(update func(*puda.ConfigUser)) error {
	configPath, err := puda.ProjectConfigPath()
	if err != nil {
		return err
	}
	if configPath == "" {
		return nil
	}

	projectCfg, err := puda.LoadProjectConfig()
	if err != nil {
		return err
	}

	update(&projectCfg.User)
	return puda.SaveProjectConfig(projectCfg)
}
