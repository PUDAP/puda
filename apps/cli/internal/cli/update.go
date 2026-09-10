package cli

import (
	"fmt"

	"github.com/PUDAP/puda/apps/cli/internal/update"
	"github.com/spf13/cobra"
)

var (
	updateTargetVersion string
	updateYes           bool
)

var updateCmd = &cobra.Command{
	Use:   "update [version]",
	Short: "Update the puda CLI to the latest (or a specific) release",
	Long: `Download and install a release of the puda CLI from GitHub.

Releases: https://github.com/pudap/puda/releases

Without a version, the latest release is installed. Pass a tag as [version] or
--version to install that release; downgrading will print a warning and require
confirmation unless --yes/-y is set.

The binary is replaced in place at the path reported by 'which puda'
(os.Executable). Use --yes/-y to skip confirmation prompts.`,
	Args: cobra.MaximumNArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		target, err := resolveUpdateVersion(updateTargetVersion, args)
		if err != nil {
			return err
		}
		return update.Run(cmd, target, updateYes, Version)
	},
}

func init() {
	updateCmd.Flags().StringVar(&updateTargetVersion, "version", "", "Release tag to install (e.g. v1.5.0). Defaults to the latest release.")
	updateCmd.Flags().BoolVarP(&updateYes, "yes", "y", false, "Skip confirmation prompts (non-interactive mode)")
	rootCmd.AddCommand(updateCmd)
}

func resolveUpdateVersion(flag string, args []string) (string, error) {
	if len(args) == 0 {
		return flag, nil
	}
	if flag != "" {
		return "", fmt.Errorf("provide the version as either [version] or --version, not both")
	}
	return args[0], nil
}
