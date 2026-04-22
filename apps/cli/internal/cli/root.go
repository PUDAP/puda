package cli

import (
	"fmt"
	"os"
	"runtime"
	"runtime/debug"

	"github.com/spf13/cobra"
)

// Version, Commit and BuildDate may be overridden at build time via ldflags.
// Example:
//
//	go build -ldflags "\
//	  -X github.com/PUDAP/puda/apps/cli/internal/cli.Version=v1.0.0 \
//	  -X github.com/PUDAP/puda/apps/cli/internal/cli.Commit=abc1234 \
//	  -X github.com/PUDAP/puda/apps/cli/internal/cli.BuildDate=2026-04-22T00:00:00Z"
//
// When a value is not provided via -ldflags, it is resolved at startup from
// the Go build info embedded in the binary. Each var must keep a simple string
// literal initializer so the linker's -X flag can patch it.
var (
	Version   = "dev"
	Commit    = ""
	BuildDate = ""
)

// resolveBuildInfo inspects the binary's embedded build info and returns
// (version, commit, dirty) derived from it.
//
// Version precedence:
//  1. Main module version when it looks like a real release (e.g. v1.2.3).
//  2. "dev-<shortsha>" (suffixed with "-dirty" if the working tree was dirty)
//     when VCS info is embedded.
//  3. "dev" as a last resort.
func resolveBuildInfo() (version, commit string, dirty bool) {
	version = "dev"
	info, ok := debug.ReadBuildInfo()
	if !ok {
		return
	}

	if v := info.Main.Version; v != "" && v != "(devel)" {
		version = v
	}

	var modified string
	for _, s := range info.Settings {
		switch s.Key {
		case "vcs.revision":
			commit = s.Value
		case "vcs.modified":
			modified = s.Value
		}
	}
	dirty = modified == "true"

	if version == "dev" && commit != "" {
		short := commit
		if len(short) > 7 {
			short = short[:7]
		}
		if dirty {
			version = "dev-" + short + "-dirty"
		} else {
			version = "dev-" + short
		}
	}
	return
}

// versionString returns the multi-line string rendered by `puda --version`.
func versionString() string {
	commit := Commit
	if commit == "" {
		commit = "unknown"
	}
	buildDate := BuildDate
	if buildDate == "" {
		buildDate = "unknown"
	}
	return fmt.Sprintf(
		"%s\n  commit:     %s\n  built:      %s\n  go version: %s\n  platform:   %s/%s\n",
		Version, commit, buildDate, runtime.Version(), runtime.GOOS, runtime.GOARCH,
	)
}

var rootCmd = &cobra.Command{
	Use:           "puda",
	Short:         "PUDA CLI - Command-line interface for PUDA",
	Long:          "PUDA CLI provides commands for the platform",
	SilenceErrors: true,
	Run: func(cmd *cobra.Command, args []string) {
		// Show help when no subcommand is provided
		cmd.Help()
	},
}

// Execute runs the root command
func Execute() error {
	if err := rootCmd.Execute(); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		return err
	}
	return nil
}

// init registers all top-level commands with the root command
func init() {
	// Fill in anything that wasn't supplied via -ldflags from the embedded
	// build info (set by the Go toolchain since 1.18).
	resolvedVersion, resolvedCommit, dirty := resolveBuildInfo()
	if Version == "" || Version == "dev" {
		Version = resolvedVersion
	}
	if Commit == "" {
		Commit = resolvedCommit
		if Commit != "" && dirty {
			Commit += " (dirty)"
		}
	}

	rootCmd.Version = Version
	rootCmd.SetVersionTemplate(versionString())

	rootCmd.AddCommand(&cobra.Command{
		Use:   "version",
		Short: "Print the version information",
		Args:  cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			fmt.Print(versionString())
		},
	})

	// Register top-level commands
	rootCmd.AddCommand(protocolCmd)
	rootCmd.AddCommand(projectCmd)
	rootCmd.AddCommand(machineCmd)
	rootCmd.AddCommand(loginCmd)
	rootCmd.AddCommand(configCmd)
	rootCmd.AddCommand(logoutCmd)
	rootCmd.AddCommand(initCmd)
	rootCmd.AddCommand(dbCmd)
	rootCmd.AddCommand(profileCmd)
}
