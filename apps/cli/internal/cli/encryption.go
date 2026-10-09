package cli

import (
	"fmt"
	"time"

	"github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

const e2eSetupDocs = "https://github.com/pudap/puda/blob/main/infra/nats/single-node-e2e/README.md"

var encryptionYes bool

var encryptionCmd = &cobra.Command{
	Use:   "encryption",
	Short: "Check or rotate payload encryption on an encrypted profile",
	Long: `Check which edges have the lab key, or rotate that key.

These commands require an encrypted profile (tls:// with --ca and --key).
A plaintext profile returns an error.

Setup: ` + e2eSetupDocs,
}

var encryptionStatusCmd = &cobra.Command{
	Use:   "status",
	Short: "Show which edges and CLI key files have the current lab key",
	Args:  cobra.NoArgs,
	RunE: func(cmd *cobra.Command, args []string) error {
		if err := requireEncryption(); err != nil {
			return err
		}
		nc, err := connectNATS()
		if err != nil {
			return err
		}
		defer nc.Close()
		return nats.PrintStatus(nc, 2*time.Second, cmd.OutOrStdout())
	},
}

var encryptionRotateCmd = &cobra.Command{
	Use:   "rotate",
	Short: "Install a new lab key, then optionally switch encryption to it",
	Args:  cobra.NoArgs,
	RunE: func(cmd *cobra.Command, args []string) error {
		if err := requireEncryption(); err != nil {
			return err
		}
		retire, _ := cmd.Flags().GetBool("retire")
		nc, err := connectNATS()
		if err != nil {
			return err
		}
		defer nc.Close()
		if err := nats.Rotate(nc, retire, encryptionYes, cmd.InOrStdin(), cmd.OutOrStdout()); err != nil {
			return err
		}
		return nil
	},
}

func requireEncryption() error {
	if _, err := prepareConnection(); err != nil {
		return err
	}
	if nats.Enabled() {
		return nil
	}
	cfg, err := puda.LoadGlobalConfig()
	if err == nil && cfg.ActiveProfile != "" {
		return fmt.Errorf("payload encryption is off for profile %q. Use a profile with e2ee enabled. Setup: %s", cfg.ActiveProfile, e2eSetupDocs)
	}
	return fmt.Errorf("payload encryption is off. Use a profile with e2ee enabled. Setup: %s", e2eSetupDocs)
}

func init() {
	encryptionRotateCmd.Flags().BoolVar(&encryptionYes, "yes", false, "Switch to the new key without prompting")
	encryptionRotateCmd.Flags().Bool("retire", false, "Drop the previous key after clients have switched")
	encryptionCmd.AddCommand(encryptionStatusCmd)
	encryptionCmd.AddCommand(encryptionRotateCmd)
	rootCmd.AddCommand(encryptionCmd)
}
