package cli

import "github.com/spf13/cobra"

var natsCmd = &cobra.Command{
	Use:   "nats",
	Short: "NATS-related commands",
	Long:  "Commands for interacting with machines via NATS",
}

func init() {
	natsCmd.AddCommand(sendCmd)
}

