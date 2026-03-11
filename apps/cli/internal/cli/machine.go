package cli

import (
	"fmt"
	"os"
	"time"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	natsio "github.com/nats-io/nats.go"
	"github.com/spf13/cobra"
)

type machineDefinition struct {
	ID        string // CLI subcommand name, e.g. "biologic"
	Short     string // one-line description shown in help
	ClassName string // Python class name in puda_drivers.machines
}

var machines = []machineDefinition{
	{ID: "first", Short: "Liquid handling robot, motion system, and camera", ClassName: "First"},
	{ID: "biologic", Short: "Electrochemical testing device", ClassName: "Biologic"},
}

var machineNatsServers string

var machineCmd = &cobra.Command{
	Use:   "machine",
	Short: "Machine operations",
	Long: `Commands for machine operations.

Subcommands:
  list              - List known machines
  status            - Show overall lab status
  <machine_id>      - Target a specific machine in list

For help: "puda machine --help"`,
	Run: func(cmd *cobra.Command, args []string) {
		cmd.Help()
	},
}

var machineListCmd = &cobra.Command{
	Use:   "list",
	Short: "List known machines",
	Long:  `List all known machine definitions.`,
	Run: func(cmd *cobra.Command, args []string) {
		for _, m := range machines {
			fmt.Printf("  %-12s %s\n", m.ID, m.Short)
		}
	},
}

var machineStatusCmd = &cobra.Command{
	Use:   "status",
	Short: "Show overall lab status",
	Long:  `Show the status of all machines in the lab by listening to heartbeats.`,
	RunE: func(cmd *cobra.Command, args []string) error {
		nc, err := connectMachineNATS()
		if err != nil {
			return err
		}
		defer nc.Close()
		return listAliveMachines(nc)
	},
}

func registerMachine(def machineDefinition) {
	id := def.ID
	className := def.ClassName

	parentCmd := &cobra.Command{
		Use:   id,
		Short: def.Short,
		Long:  fmt.Sprintf("Target the %s machine (%s).", className, def.Short),
		Run: func(cmd *cobra.Command, args []string) {
			cmd.Help()
		},
	}

	statusCmd := &cobra.Command{
		Use:   "status",
		Short: fmt.Sprintf("Get the status of the %s machine", id),
		RunE: func(cmd *cobra.Command, args []string) error {
			nc, err := connectMachineNATS()
			if err != nil {
				return err
			}
			defer nc.Close()
			return getSingleMachineStatus(nc, id)
		},
	}

	resetCmd := &cobra.Command{
		Use:   "reset",
		Short: fmt.Sprintf("Reset the %s machine", id),
		RunE: func(cmd *cobra.Command, args []string) error {
			return resetMachine(id)
		},
	}

	commandsCmd := &cobra.Command{
		Use:   "commands",
		Short: "Show available commands",
		Long:  fmt.Sprintf("Show Python help documentation for %sMachine class.", className),
		Run: func(cmd *cobra.Command, args []string) {
			if err := puda.ShowPublicMethods("puda_drivers.machines", className); err != nil {
				fmt.Fprintf(os.Stderr, "Error: %v\n", err)
				os.Exit(1)
			}
		},
	}

	parentCmd.AddCommand(statusCmd)
	parentCmd.AddCommand(resetCmd)
	parentCmd.AddCommand(commandsCmd)
	machineCmd.AddCommand(parentCmd)
}

func init() {
	machineCmd.PersistentFlags().StringVar(&machineNatsServers, "nats-servers", "", "Comma-separated NATS server URLs (overrides puda.config)")
	machineCmd.AddCommand(machineListCmd)
	machineCmd.AddCommand(machineStatusCmd)

	for _, def := range machines {
		registerMachine(def)
	}
}

// connectMachineNATS resolves NATS servers from flag or config and returns a connection.
// Used by all machine subcommands that need NATS.
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
