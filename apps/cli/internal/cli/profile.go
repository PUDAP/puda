package cli

import (
	"fmt"
	"sort"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

var profileCmd = &cobra.Command{
	Use:   "profile",
	Short: "Manage connection profiles",
	Long:  "Manage NATS connection profiles. Use subcommands to list or switch profiles.",
}

var profileListCmd = &cobra.Command{
	Use:   "list",
	Short: "List available connection profiles",
	RunE:  runProfileList,
}

var profileSwitchCmd = &cobra.Command{
	Use:   "switch <profile>",
	Short: "Switch the active connection profile",
	Args:  cobra.ExactArgs(1),
	ValidArgsFunction: func(cmd *cobra.Command, args []string, toComplete string) ([]string, cobra.ShellCompDirective) {
		return sortedProfileNames(), cobra.ShellCompDirectiveNoFileComp
	},
	RunE: runProfileSwitch,
}

var profileCurrentCmd = &cobra.Command{
	Use:   "current",
	Short: "Show the current active profile",
	RunE:  runProfileCurrent,
}

func init() {
	profileCmd.AddCommand(profileListCmd)
	profileCmd.AddCommand(profileSwitchCmd)
	profileCmd.AddCommand(profileCurrentCmd)
}

func runProfileList(cmd *cobra.Command, args []string) error {
	cfg, _ := puda.LoadGlobalConfig()

	names := sortedProfileNames()
	for _, name := range names {
		profile := puda.BuiltinProfiles[name]
		active := "  "
		if cfg != nil && cfg.ActiveProfile == name {
			active = "* "
		}
		fmt.Fprintf(cmd.OutOrStdout(), "%s%-8s %s\n", active, name, profile.Description)
	}
	return nil
}

func runProfileSwitch(cmd *cobra.Command, args []string) error {
	name := args[0]

	profile, ok := puda.BuiltinProfiles[name]
	if !ok {
		return fmt.Errorf("unknown profile %q (available: %v)", name, sortedProfileNames())
	}

	cfg, err := puda.LoadGlobalConfig()
	if err != nil {
		return err
	}

	cfg.ActiveProfile = name

	if err := puda.SaveGlobalConfig(cfg); err != nil {
		return err
	}

	fmt.Fprintf(cmd.OutOrStdout(), "Switched to profile %q (%s)\n", name, profile.NATSServers)
	return nil
}

func runProfileCurrent(cmd *cobra.Command, args []string) error {
	cfg, err := puda.LoadGlobalConfig()
	if err != nil {
		return err
	}

	name := cfg.ActiveProfile
	if name == "" {
		name = "bears"
	}

	profile, ok := puda.BuiltinProfiles[name]
	if !ok {
		return fmt.Errorf("active profile %q not found", name)
	}

	const labelW = 15 // widest label: "NATS servers:"
	fmt.Fprintf(cmd.OutOrStdout(), "%-*s %s\n", labelW, "Profile:", name)
	fmt.Fprintf(cmd.OutOrStdout(), "%-*s %s\n", labelW, "Description:", profile.Description)
	fmt.Fprintf(cmd.OutOrStdout(), "%-*s %s\n", labelW, "NATS servers:", profile.NATSServers)
	return nil
}

func sortedProfileNames() []string {
	names := make([]string, 0, len(puda.BuiltinProfiles))
	for name := range puda.BuiltinProfiles {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}
