package cli

import (
	"time"

	"github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/spf13/cobra"
)

var encryptionYes bool

var encryptionCmd = &cobra.Command{
	Use:   "encryption",
	Short: "Inspect or rotate optional NATS payload encryption",
}

var encryptionStatusCmd = &cobra.Command{
	Use:   "status",
	Short: "Show which edges and CLI key files have the current lab key",
	Args:  cobra.NoArgs,
	RunE: func(cmd *cobra.Command, args []string) error {
		nc, err := connectNATS("")
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
		retire, _ := cmd.Flags().GetBool("retire")
		nc, err := connectNATS("")
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

func init() {
	encryptionRotateCmd.Flags().BoolVar(&encryptionYes, "yes", false, "Switch to the new key without prompting")
	encryptionRotateCmd.Flags().Bool("retire", false, "Drop the previous key after clients have switched")
	encryptionCmd.AddCommand(encryptionStatusCmd)
	encryptionCmd.AddCommand(encryptionRotateCmd)
	rootCmd.AddCommand(encryptionCmd)
}
