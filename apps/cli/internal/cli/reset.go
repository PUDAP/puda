package cli

import (
	"fmt"
	"os"
	"time"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	"github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	natsio "github.com/nats-io/nats.go"
	"github.com/spf13/cobra"
)

const resetTimeoutSeconds = 5

var resetNatsServers string

// resetCmd is the top-level reset command
var resetCmd = &cobra.Command{
	Use:   "reset",
	Short: "Send reset or other immediate commands",
	Long:  `Send immediate commands such as reset to machines.`,
}

// resetMachineCmd is the subcommand for reset machine <machine>
var resetMachineCmd = &cobra.Command{
	Use:   "machine [machineID]",
	Short: "Reset a machine",
	Long:  `Send the reset immediate command to a machine (e.g. biologic, first).`,
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		return runResetMachine(args[0])(cmd, args)
	},
}

func init() {
	rootCmd.AddCommand(resetCmd)
	resetCmd.AddCommand(resetMachineCmd)
	resetMachineCmd.PersistentFlags().StringVar(&resetNatsServers, "nats-servers", "", "Comma-separated NATS server URLs (overrides puda.config)")
}

// runResetMachine returns a RunE that sends the reset immediate command to the given machineID
func runResetMachine(machineID string) func(*cobra.Command, []string) error {
	return func(cmd *cobra.Command, args []string) error {
		// Load global config for user
		globalConfig, err := puda.LoadGlobalConfig()
		if err != nil {
			return fmt.Errorf("failed to load global config (run 'puda login' first): %w", err)
		}
		userID := globalConfig.User.UserID
		username := globalConfig.User.Username
		if userID == "" || username == "" {
			return fmt.Errorf("user not logged in. Please run 'puda login' first")
		}

		// Resolve NATS servers: flag > project config
		natsServers := resetNatsServers
		if natsServers == "" {
			cfg, err := puda.LoadProjectConfig()
			if err != nil {
				return fmt.Errorf("NATS endpoint is required (set in puda.config or use --nats-servers): %w", err)
			}
			natsServers = cfg.Endpoints.NATS
		}
		if natsServers == "" {
			return fmt.Errorf("NATS endpoint is required (set in puda.config or use --nats-servers)")
		}

		store, err := db.Connect()
		if err != nil {
			store = nil
		} else {
			defer store.Disconnect()
		}

		nc, err := natsio.Connect(natsServers, natsio.MaxReconnects(3), natsio.ReconnectWait(2*time.Second))
		if err != nil {
			return fmt.Errorf("failed to connect to NATS: %w", err)
		}
		defer nc.Close()

		js, err := nc.JetStream()
		if err != nil {
			return fmt.Errorf("failed to get JetStream context: %w", err)
		}

		response, err := nats.SendResetCommand(nc, js, machineID, "", userID, username, resetTimeoutSeconds, store)
		if err != nil {
			return err
		}
		if response.Response != nil && response.Response.Status == puda.StatusError {
			msg := "unknown error"
			if response.Response.Message != nil {
				msg = *response.Response.Message
			}
			return fmt.Errorf("reset failed: %s", msg)
		}
		fmt.Fprintf(os.Stdout, "Reset command sent successfully to %s\n", machineID)
		return nil
	}
}
