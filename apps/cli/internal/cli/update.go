package cli

import (
	"github.com/PUDAP/puda/apps/cli/internal/update"
	"github.com/spf13/cobra"
)

var (
	updateTargetVersion string
	updateYes           bool
)

var updateCmd = &cobra.Command{
	Use:   "update",
	Short: "Update the puda CLI to the latest (or a specific) release",
	Long: `Download and install a release of the puda CLI from GitHub.

Without --version, the latest release is installed. With --version, a specific
tag is installed; downgrading will print a warning and require confirmation.

The binary is replaced in place at the path reported by 'which puda'
(os.Executable). Use --yes/-y for non-interactive mode.`,
	Example: `  # Upgrade to the latest release
  puda update

  # Install a specific release (upgrade or downgrade)
  puda update --version v1.5.0

  # Non-interactive (useful in scripts)
  puda update --version v1.5.0 --yes`,
	RunE: func(cmd *cobra.Command, args []string) error {
		return update.Run(cmd, updateTargetVersion, updateYes, Version)
	},
}

func init() {
	updateCmd.Flags().StringVar(&updateTargetVersion, "version", "", "Release tag to install (e.g. v1.5.0). Defaults to the latest release.")
	updateCmd.Flags().BoolVarP(&updateYes, "yes", "y", false, "Skip confirmation prompts (non-interactive mode)")
	rootCmd.AddCommand(updateCmd)
}
