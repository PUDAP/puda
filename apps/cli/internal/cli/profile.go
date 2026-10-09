package cli

import (
	"fmt"
	"io"
	"os"
	"sort"
	"strings"

	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

var profileHuman bool

var profilesCmd = &cobra.Command{
	Use:   "profile",
	Short: "Switch between NATS servers",
	Long: `Manage named NATS connections. A profile is either a plaintext nats:// broker or a tls:// broker with payload encryption.

Output is a JSON object by default. Use --human for a text summary.`,
}

var profilesAddCmd = &cobra.Command{
	Use:   "add <name>",
	Short: "Save a NATS profile",
	Long: `Save a named NATS connection.

Pass --servers with nats:// URLs for a plaintext broker.
Pass --servers with tls:// URLs plus --ca and --key for a broker with payload encryption.
--ca and --key must be given together. The lab key stays in its own file; the profile stores the path.

The new profile becomes active when none is selected.

Output is a JSON object by default. Use --human for a text summary.`,
	Args: cobra.ExactArgs(1),
	RunE: runProfilesAdd,
}

var profilesListCmd = &cobra.Command{
	Use:   "list",
	Short: "List NATS profiles",
	Long:  "List NATS profiles. Output is a JSON object by default. Use --human for a text summary.",
	Args:  cobra.NoArgs,
	RunE: func(cmd *cobra.Command, args []string) error {
		return listProfiles(cmd.OutOrStdout(), profileHuman)
	},
}

var profilesCurrentCmd = &cobra.Command{
	Use:   "current",
	Short: "Show the active NATS profile",
	Long:  "Show the active NATS profile. Output is a JSON object by default. Use --human for a text summary.",
	Args:  cobra.NoArgs,
	RunE: func(cmd *cobra.Command, args []string) error {
		return printCurrentProfile(cmd.OutOrStdout(), profileHuman)
	},
}

var profileSetKeys = []string{"nats_servers", "gateway_servers", "ca", "key"}

var profilesSetCmd = &cobra.Command{
	Use:   "set <nats_servers|gateway_servers|ca|key> <value>",
	Short: "Change a field on the active profile",
	Long: `Change nats_servers, gateway_servers, ca, or key on the active profile.

This does not select a different profile. Use 'puda profile switch' for that.
ca and key can only be changed when the active profile has e2ee enabled.

Output is a JSON object by default. Use --human for a text summary.`,
	Args: cobra.ExactArgs(2),
	ValidArgsFunction: func(cmd *cobra.Command, args []string, toComplete string) ([]string, cobra.ShellCompDirective) {
		if len(args) == 0 {
			return profileSetKeys, cobra.ShellCompDirectiveNoFileComp
		}
		return nil, cobra.ShellCompDirectiveNoFileComp
	},
	RunE: func(cmd *cobra.Command, args []string) error {
		if err := setActiveProfileField(args[0], args[1]); err != nil {
			return err
		}
		return printCurrentProfile(cmd.OutOrStdout(), profileHuman)
	},
}

var profilesSwitchCmd = &cobra.Command{
	Use:               "switch <name>",
	Short:             "Select the active NATS profile",
	Args:              cobra.ExactArgs(1),
	ValidArgsFunction: completeProfileNames,
	Long:              "Select the active NATS profile. Output is a JSON object by default. Use --human for a text summary.",
	RunE: func(cmd *cobra.Command, args []string) error {
		if err := switchProfile(args[0]); err != nil {
			return err
		}
		return writeProfileAction(cmd.OutOrStdout(), profileHuman, fmt.Sprintf("active profile: %s\n", args[0]), profileAction{
			Active: args[0],
		})
	},
}

var profilesRemoveCmd = &cobra.Command{
	Use:               "remove <name>",
	Short:             "Delete a NATS profile",
	Args:              cobra.ExactArgs(1),
	ValidArgsFunction: completeProfileNames,
	Long:              "Delete a NATS profile. Output is a JSON object by default. Use --human for a text summary.",
	RunE: func(cmd *cobra.Command, args []string) error {
		if err := removeProfile(args[0]); err != nil {
			return err
		}
		cfg, err := puda.LoadGlobalConfig()
		if err != nil {
			return err
		}
		return writeProfileAction(cmd.OutOrStdout(), profileHuman, fmt.Sprintf("removed profile %s\n", args[0]), profileAction{
			Removed: args[0],
			Active:  cfg.ActiveProfile,
		})
	},
}

func init() {
	profilesCmd.PersistentFlags().BoolVar(&profileHuman, "human", false, "Output as human-readable text instead of JSON")
	profilesAddCmd.Flags().String("servers", "", "Comma-separated NATS server URLs")
	profilesAddCmd.Flags().String("gateway-servers", "", "Comma-separated remote cluster URLs")
	profilesAddCmd.Flags().String("ca", "", "Path to the NATS server CA file (ca.pem)")
	profilesAddCmd.Flags().String("key", "", "Path to the lab key file (e2e.key)")
	_ = profilesAddCmd.MarkFlagRequired("servers")
	profilesCmd.AddCommand(profilesAddCmd)
	profilesCmd.AddCommand(profilesListCmd)
	profilesCmd.AddCommand(profilesCurrentCmd)
	profilesCmd.AddCommand(profilesSetCmd)
	profilesCmd.AddCommand(profilesSwitchCmd)
	profilesCmd.AddCommand(profilesRemoveCmd)
	rootCmd.AddCommand(profilesCmd)
}

func runProfilesAdd(cmd *cobra.Command, args []string) error {
	servers, _ := cmd.Flags().GetString("servers")
	gateways, _ := cmd.Flags().GetString("gateway-servers")
	ca, _ := cmd.Flags().GetString("ca")
	key, _ := cmd.Flags().GetString("key")
	activated, err := addProfile(args[0], servers, gateways, ca, key)
	if err != nil {
		return err
	}
	cfg, err := puda.LoadGlobalConfig()
	if err != nil {
		return err
	}
	text := fmt.Sprintf("added profile %s\n", args[0])
	if activated {
		text += fmt.Sprintf("active profile: %s\n", args[0])
	}
	return writeProfileAction(cmd.OutOrStdout(), profileHuman, text, profileAction{
		Name:      args[0],
		Activated: activated,
		Active:    cfg.ActiveProfile,
	})
}

func addProfile(name, servers, gateways, ca, key string) (bool, error) {
	name = strings.TrimSpace(name)
	if !puda.ValidProfileName(name) {
		return false, fmt.Errorf("invalid profile name %q", name)
	}
	ca = strings.TrimSpace(ca)
	key = strings.TrimSpace(key)
	if (ca == "") != (key == "") {
		return false, fmt.Errorf("encrypted profile requires both --ca and --key")
	}
	profile := puda.Profile{
		NATSServers:    strings.TrimSpace(servers),
		GatewayServers: strings.TrimSpace(gateways),
		E2E:            ca != "",
		CA:             ca,
		KeyFile:        key,
	}
	if err := profile.Validate(); err != nil {
		return false, err
	}
	if err := validateProfileFiles(profile); err != nil {
		return false, err
	}

	cfg, err := puda.LoadGlobalConfig()
	if err != nil {
		return false, err
	}
	if cfg.Profiles == nil {
		cfg.Profiles = map[string]puda.Profile{}
	}
	if _, exists := cfg.Profiles[name]; exists {
		return false, fmt.Errorf("profile %q already exists", name)
	}
	cfg.Profiles[name] = profile
	activated := cfg.ActiveProfile == ""
	if activated {
		cfg.ActiveProfile = name
	}
	if err := puda.SaveGlobalConfig(cfg); err != nil {
		return false, err
	}
	return activated, nil
}

type profileView struct {
	Name           string `json:"name"`
	Active         bool   `json:"active"`
	NATSServers    string `json:"nats_servers"`
	GatewayServers string `json:"gateway_servers"`
	E2E            bool   `json:"e2e"`
	CA             string `json:"ca,omitempty"`
	KeyFile        string `json:"key_file,omitempty"`
}

type profileList struct {
	Active   string        `json:"active"`
	Profiles []profileView `json:"profiles"`
}

type profileAction struct {
	Name      string `json:"name,omitempty"`
	Activated bool   `json:"activated,omitempty"`
	Removed   string `json:"removed,omitempty"`
	Active    string `json:"active"`
}

func profileViews(cfg *puda.GlobalConfig) []profileView {
	names := make([]string, 0, len(cfg.Profiles))
	for name := range cfg.Profiles {
		names = append(names, name)
	}
	sort.Strings(names)
	views := make([]profileView, 0, len(names))
	for _, name := range names {
		profile := cfg.Profiles[name]
		views = append(views, profileView{
			Name:           name,
			Active:         name == cfg.ActiveProfile,
			NATSServers:    profile.NATSServers,
			GatewayServers: profile.GatewayServers,
			E2E:            profile.E2E,
			CA:             profile.CA,
			KeyFile:        profile.KeyFile,
		})
	}
	return views
}

func writeProfileAction(w io.Writer, human bool, text string, action profileAction) error {
	if human {
		fmt.Fprint(w, text)
		return nil
	}
	return writeJSON(w, action)
}

func listProfiles(w io.Writer, human bool) error {
	cfg, err := puda.LoadGlobalConfig()
	if err != nil {
		return err
	}
	views := profileViews(cfg)
	if human {
		if len(views) == 0 {
			fmt.Fprintln(w, "no profiles")
			return nil
		}
		for _, view := range views {
			mark := " "
			if view.Active {
				mark = "*"
			}
			mode := "plain"
			if view.E2E {
				mode = "e2e"
			}
			fmt.Fprintf(w, "%s %s %s %s\n", mark, view.Name, view.NATSServers, mode)
		}
		return nil
	}
	return writeJSON(w, profileList{Active: cfg.ActiveProfile, Profiles: views})
}

func printCurrentProfile(w io.Writer, human bool) error {
	cfg, err := puda.LoadGlobalConfig()
	if err != nil {
		return err
	}
	profile, active, err := cfg.ActiveProfileConfig()
	if err != nil {
		return err
	}
	if !active {
		return fmt.Errorf("no active profile; run 'puda profile add' or 'puda profile switch'")
	}
	view := profileView{
		Name:           cfg.ActiveProfile,
		Active:         true,
		NATSServers:    profile.NATSServers,
		GatewayServers: profile.GatewayServers,
		E2E:            profile.E2E,
		CA:             profile.CA,
		KeyFile:        profile.KeyFile,
	}
	if human {
		fmt.Fprintf(w, "name=%s\n", view.Name)
		fmt.Fprintf(w, "nats_servers=%s\n", view.NATSServers)
		fmt.Fprintf(w, "gateway_servers=%s\n", view.GatewayServers)
		fmt.Fprintf(w, "e2e=%t\n", view.E2E)
		if view.E2E {
			fmt.Fprintf(w, "ca=%s\n", view.CA)
			fmt.Fprintf(w, "key_file=%s\n", view.KeyFile)
		}
		return nil
	}
	return writeJSON(w, view)
}

func setActiveProfileField(key, value string) error {
	key = strings.TrimSpace(key)
	value = strings.TrimSpace(value)
	switch key {
	case "nats_servers", "gateway_servers", "ca", "key":
	default:
		return fmt.Errorf("unknown profile field %q; settable fields: %v", key, profileSetKeys)
	}

	cfg, err := puda.LoadGlobalConfig()
	if err != nil {
		return err
	}
	profile, active, err := cfg.ActiveProfileConfig()
	if err != nil {
		return err
	}
	if !active {
		return fmt.Errorf("no active profile; run 'puda profile switch <name>'")
	}
	if (key == "ca" || key == "key") && !profile.E2E {
		return fmt.Errorf("profile %q does not have e2ee enabled", cfg.ActiveProfile)
	}
	switch key {
	case "nats_servers":
		profile.NATSServers = value
	case "gateway_servers":
		profile.GatewayServers = value
	case "ca":
		profile.CA = value
	case "key":
		profile.KeyFile = value
	}
	if err := profile.Validate(); err != nil {
		return err
	}
	if err := validateProfileFiles(profile); err != nil {
		return err
	}
	cfg.Profiles[cfg.ActiveProfile] = profile
	return puda.SaveGlobalConfig(cfg)
}

func switchProfile(name string) error {
	name = strings.TrimSpace(name)
	cfg, err := puda.LoadGlobalConfig()
	if err != nil {
		return err
	}
	profile, ok := cfg.Profiles[name]
	if !ok {
		return fmt.Errorf("profile %q not found", name)
	}
	if err := profile.Validate(); err != nil {
		return err
	}
	if err := validateProfileFiles(profile); err != nil {
		return err
	}
	cfg.ActiveProfile = name
	return puda.SaveGlobalConfig(cfg)
}

func removeProfile(name string) error {
	name = strings.TrimSpace(name)
	cfg, err := puda.LoadGlobalConfig()
	if err != nil {
		return err
	}
	if _, ok := cfg.Profiles[name]; !ok {
		return fmt.Errorf("profile %q not found", name)
	}
	delete(cfg.Profiles, name)
	if cfg.ActiveProfile == name {
		cfg.ActiveProfile = ""
	}
	return puda.SaveGlobalConfig(cfg)
}

func validateProfileFiles(profile puda.Profile) error {
	if !profile.E2E {
		return nil
	}
	info, err := os.Stat(profile.CA)
	if err != nil {
		return fmt.Errorf("CA file: %w", err)
	}
	if info.IsDir() {
		return fmt.Errorf("CA file %s is a directory", profile.CA)
	}
	if err := pudanats.ValidateKeyFile(profile.KeyFile); err != nil {
		return err
	}
	return nil
}

func completeProfileNames(cmd *cobra.Command, args []string, toComplete string) ([]string, cobra.ShellCompDirective) {
	cfg, err := puda.LoadGlobalConfig()
	if err != nil {
		return nil, cobra.ShellCompDirectiveNoFileComp
	}
	names := make([]string, 0, len(cfg.Profiles))
	for name := range cfg.Profiles {
		names = append(names, name)
	}
	sort.Strings(names)
	return names, cobra.ShellCompDirectiveNoFileComp
}
