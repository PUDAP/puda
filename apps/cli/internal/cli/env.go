package cli

import (
	"fmt"
	"sort"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

var envCmd = &cobra.Command{
	Use:   "env",
	Short: "Manage connection environments",
	Long:  "Manage NATS connection environments. Use subcommands to list or switch environments.",
}

var envListCmd = &cobra.Command{
	Use:   "list",
	Short: "List available connection environments",
	RunE:  runEnvList,
}

var envSwitchCmd = &cobra.Command{
	Use:   "switch <env>",
	Short: "Switch the active connection environment",
	Args:  cobra.ExactArgs(1),
	ValidArgsFunction: func(cmd *cobra.Command, args []string, toComplete string) ([]string, cobra.ShellCompDirective) {
		return sortedEnvNames(), cobra.ShellCompDirectiveNoFileComp
	},
	RunE: runEnvSwitch,
}

var envCurrentCmd = &cobra.Command{
	Use:   "current",
	Short: "Show the current active environment",
	RunE:  runEnvCurrent,
}

func init() {
	envCmd.AddCommand(envListCmd)
	envCmd.AddCommand(envSwitchCmd)
	envCmd.AddCommand(envCurrentCmd)
}

func runEnvList(cmd *cobra.Command, args []string) error {
	cfg, _ := puda.LoadGlobalConfig()

	names := sortedEnvNames()
	for _, name := range names {
		env := puda.BuiltinEnvs[name]
		active := "  "
		if cfg != nil && cfg.ActiveEnv == name {
			active = "* "
		}
		fmt.Fprintf(cmd.OutOrStdout(), "%s%-8s %s\n", active, name, env.Description)
	}
	return nil
}

func runEnvSwitch(cmd *cobra.Command, args []string) error {
	name := args[0]

	env, ok := puda.BuiltinEnvs[name]
	if !ok {
		return fmt.Errorf("unknown env %q (available: %v)", name, sortedEnvNames())
	}

	cfg, err := puda.LoadGlobalConfig()
	if err != nil {
		return err
	}

	cfg.ActiveEnv = name

	if err := puda.SaveGlobalConfig(cfg); err != nil {
		return err
	}

	fmt.Fprintf(cmd.OutOrStdout(), "Switched to env %q (%s)\n", name, env.NATSServers)
	return nil
}

func runEnvCurrent(cmd *cobra.Command, args []string) error {
	cfg, err := puda.LoadGlobalConfig()
	if err != nil {
		return err
	}

	name := cfg.ActiveEnv
	if name == "" {
		name = "bears"
	}

	env, ok := puda.BuiltinEnvs[name]
	if !ok {
		return fmt.Errorf("active env %q not found", name)
	}

	const labelW = 15 // widest label: "NATS servers:"
	fmt.Fprintf(cmd.OutOrStdout(), "%-*s %s\n", labelW, "Env:", name)
	fmt.Fprintf(cmd.OutOrStdout(), "%-*s %s\n", labelW, "Description:", env.Description)
	fmt.Fprintf(cmd.OutOrStdout(), "%-*s %s\n", labelW, "NATS servers:", env.NATSServers)
	return nil
}

func sortedEnvNames() []string {
	names := make([]string, 0, len(puda.BuiltinEnvs))
	for name := range puda.BuiltinEnvs {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}
