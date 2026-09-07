package cli

import (
	"fmt"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

const (
	configKeyNATSServers    = "nats_servers"
	configKeyGatewayServers = "gateway_servers"
)

var settableConfigKeys = []string{
	configKeyNATSServers,
	configKeyGatewayServers,
}

var getConfigKeys = []string{
	configKeyNATSServers,
	configKeyGatewayServers,
	"user.username",
	"user.user_id",
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
	Use:   "set <nats_servers|gateway_servers> <value>",
	Short: "Set NATS or gateway server URLs in the global config",
	Long:  "Set comma-separated NATS server URLs or gateway remote-cluster URLs used by healthcheck and other NATS commands.",
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
	case "user.username":
		fmt.Fprintln(cmd.OutOrStdout(), cfg.User.Username)
	case "user.user_id":
		fmt.Fprintln(cmd.OutOrStdout(), cfg.User.UserID)
	default:
		return fmt.Errorf("unknown config key %q; available keys: %v", key, getConfigKeys)
	}

	return nil
}

func runConfigSet(cmd *cobra.Command, args []string) error {
	key, value := args[0], args[1]
	switch key {
	case configKeyNATSServers, configKeyGatewayServers:
	default:
		return fmt.Errorf("unknown config key %q; settable keys: %v", key, settableConfigKeys)
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
	}

	if err := puda.SaveGlobalConfig(cfg); err != nil {
		return err
	}

	fmt.Fprintf(cmd.OutOrStdout(), "%s=%s\n", key, value)
	return nil
}
