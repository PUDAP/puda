package cli

import (
	"fmt"
	"sort"
	"time"

	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	natsio "github.com/nats-io/nats.go"
	"github.com/spf13/cobra"
)

const heartbeatTimeout = 2 * time.Second

var machineNatsServers string

var machineCmd = &cobra.Command{
	Use:   "machine",
	Short: "Machine operations",
	Long:  `Commands for machine operations.`,
	Run: func(cmd *cobra.Command, args []string) {
		cmd.Help()
	},
}

var machineListCmd = &cobra.Command{
	Use:   "list",
	Short: "Discover machines via heartbeat",
	Long:  `Listen for heartbeat messages on puda.*.tlm.heartbeat and list machines that respond.`,
	RunE: func(cmd *cobra.Command, args []string) error {
		nc, err := connectMachineNATS()
		if err != nil {
			return err
		}
		defer nc.Close()

		machines, err := pudanats.DiscoverMachines(nc, heartbeatTimeout)
		if err != nil {
			return err
		}
		if len(machines) == 0 {
			fmt.Println("No machines found.")
			return nil
		}
		sort.Strings(machines)
		for _, id := range machines {
			fmt.Printf("  %s\n", id)
		}
		return nil
	},
}

var machineStateCmd = &cobra.Command{
	Use:   "state <machine_id>",
	Short: "Get the state of a machine",
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		nc, err := connectMachineNATS()
		if err != nil {
			return err
		}
		defer nc.Close()
		return pudanats.GetSingleMachineState(nc, args[0])
	},
}

var machineResetCmd = &cobra.Command{
	Use:   "reset <machine_id>",
	Short: "Reset a machine",
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		return resetMachine(args[0])
	},
}

var machineCommandsCmd = &cobra.Command{
	Use:   "commands <machine_id>",
	Short: "Show available commands for a machine",
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		nc, err := connectMachineNATS()
		if err != nil {
			return err
		}
		defer nc.Close()
		return pudanats.GetMachineCommands(nc, args[0])
	},
}

func init() {
	machineCmd.PersistentFlags().StringVar(&machineNatsServers, "nats-servers", "", "Comma-separated NATS server URLs (overrides puda.config)")
	machineCmd.AddCommand(machineListCmd)
	machineCmd.AddCommand(machineStateCmd)
	machineCmd.AddCommand(machineResetCmd)
	machineCmd.AddCommand(machineCommandsCmd)
}

func connectMachineNATS() (*natsio.Conn, error) {
	servers := machineNatsServers
	if servers == "" {
		cfg, err := puda.LoadProjectConfig()
		if err != nil {
			return nil, fmt.Errorf("NATS endpoint required (set in puda.config or use --nats-servers): %w", err)
		}
		servers = cfg.Endpoints.NATS
	}
	if servers == "" {
		return nil, fmt.Errorf("NATS endpoint required (set in puda.config or use --nats-servers)")
	}
	nc, err := natsio.Connect(servers, natsio.MaxReconnects(3), natsio.ReconnectWait(2*time.Second))
	if err != nil {
		return nil, fmt.Errorf("failed to connect to NATS: %w", err)
	}
	return nc, nil
}
