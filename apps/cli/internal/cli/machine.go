package cli

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/signal"
	"sort"
	"syscall"
	"time"

	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	natsio "github.com/nats-io/nats.go"
	"github.com/spf13/cobra"
)

const heartbeatTimeout = 2 * time.Second

var machineNatsServers string
var machineListJSON bool
var watchMachines []string
var watchTimeout int
var watchSubjects []string
var watchIncludeHeartbeat bool

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

		machines, err := pudanats.ListMachines(nc, heartbeatTimeout)
		if err != nil {
			return err
		}
		sort.Strings(machines)
		if machineListJSON {
			encoded, err := json.MarshalIndent(struct {
				Machines []string `json:"machines"`
				Count    int      `json:"count"`
			}{
				Machines: machines,
				Count:    len(machines),
			}, "", "  ")
			if err != nil {
				return fmt.Errorf("failed to encode machine list: %w", err)
			}
			fmt.Println(string(encoded))
			return nil
		}
		if len(machines) == 0 {
			fmt.Println("No machines found.")
			return nil
		}
		fmt.Printf("%d machines found:\n", len(machines))
		for _, id := range machines {
			fmt.Printf("  %s\n", id)
		}
		return nil
	},
}

var machineStateCmd = &cobra.Command{
	Use:   "state <machine_id>",
	Short: "Watch the state of a machine",
	Long:  `Refresh the machine state every second until interrupted, similar to docker stats.`,
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		nc, err := connectMachineNATS()
		if err != nil {
			return err
		}
		defer nc.Close()
		return watchMachineState(nc, args[0])
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

var machineWatchCmd = &cobra.Command{
	Use:   "watch [--machines <machine_id1,machine_id2>] [--subjects <subject1,subject2>]",
	Short: "Stream machine traffic as NDJSON",
	Long: `Subscribe to puda.*.> by default, or puda.<machine_id>.> for each selected
machine, and stream messages to stdout as newline-delimited JSON.

Use --machines/-m to select machines. If omitted, all machines are included.
Use --subjects/-s to filter with category.topic prefixes. If omitted, all
subjects are included (except heartbeats).

Available subject filters:
  tlm               all telemetry
  tlm.heartbeat     heartbeat telemetry (requires --include-heartbeat)
  tlm.pos           position telemetry
  tlm.health        system-vitals telemetry
  cmd               all command messages
  cmd.queue         queued commands
  cmd.immediate     immediate commands
  cmd.response      all command responses
  cmd.response.queue
  cmd.response.immediate
  evt               all events
  evt.log           log events
  evt.alert         alert events
  evt.media         media events
  update            update messages
  update.response   update responses

Use --timeout to auto-stop after N seconds, or Ctrl-C to stop.`,
	Args: cobra.NoArgs,
	RunE: func(cmd *cobra.Command, args []string) error {
		nc, err := connectMachineNATS()
		if err != nil {
			return err
		}
		defer nc.Close()

		ctx, cancel := context.WithCancel(context.Background())
		defer cancel()

		sigCh := make(chan os.Signal, 1)
		signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
		go func() {
			<-sigCh
			cancel()
		}()

		if watchTimeout > 0 {
			var timeoutCancel context.CancelFunc
			ctx, timeoutCancel = context.WithTimeout(ctx, time.Duration(watchTimeout)*time.Second)
			defer timeoutCancel()
		}

		opts := pudanats.WatchOpts{
			IncludeHeartbeat: watchIncludeHeartbeat,
		}
		if len(watchSubjects) > 0 {
			opts.Subjects = make(map[string]struct{}, len(watchSubjects))
			for _, t := range watchSubjects {
				opts.Subjects[t] = struct{}{}
			}
		}

		events, err := pudanats.SubscribeMachineSubjects(ctx, nc, watchMachines, opts)
		if err != nil {
			return err
		}

		enc := json.NewEncoder(os.Stdout)
		for evt := range events {
			if err := enc.Encode(evt); err != nil {
				return fmt.Errorf("failed to write event: %w", err)
			}
		}
		return nil
	},
}

func init() {
	machineCmd.PersistentFlags().StringVar(&machineNatsServers, "nats-servers", "", "Comma-separated NATS server URLs (overrides active env)")
	machineListCmd.Flags().BoolVar(&machineListJSON, "json", false, "Output machine list as JSON")
	machineWatchCmd.Flags().StringSliceVarP(&watchMachines, "machines", "m", nil, "Comma-separated list of machine IDs to watch (default: all machines)")
	machineWatchCmd.Flags().StringSliceVar(&watchMachines, "targets", nil, "Deprecated alias for --machines")
	machineWatchCmd.Flags().MarkHidden("targets")
	machineWatchCmd.Flags().IntVar(&watchTimeout, "timeout", 0, "Auto-stop after N seconds (0 = run until interrupted)")
	machineWatchCmd.Flags().StringSliceVarP(&watchSubjects, "subjects", "s", nil, "Comma-separated category.topic prefixes to include (default: all subjects)")
	machineWatchCmd.Flags().BoolVar(&watchIncludeHeartbeat, "include-heartbeat", false, "Include heartbeat messages (excluded by default)")
	machineCmd.AddCommand(machineListCmd)
	machineCmd.AddCommand(machineStateCmd)
	machineCmd.AddCommand(machineResetCmd)
	machineCmd.AddCommand(machineCommandsCmd)
	machineCmd.AddCommand(machineWatchCmd)
}

func watchMachineState(nc *natsio.Conn, machineID string) error {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	defer signal.Stop(sigCh)

	go func() {
		select {
		case <-sigCh:
			cancel()
		case <-ctx.Done():
		}
	}()

	render := func() error {
		fmt.Print("\033[H\033[2J")
		fmt.Printf("Machine: %s | Updated: %s | Press Ctrl-C to stop\n\n", machineID, time.Now().Format(time.RFC3339))
		return pudanats.GetSingleMachineState(nc, machineID)
	}

	if err := render(); err != nil {
		return err
	}

	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			fmt.Println()
			return nil
		case <-ticker.C:
			if err := render(); err != nil {
				return err
			}
		}
	}
}

func connectMachineNATS() (*natsio.Conn, error) {
	servers := machineNatsServers
	if servers == "" {
		cfg, err := puda.LoadGlobalConfig()
		if err != nil {
			return nil, fmt.Errorf("failed to load global config (run 'puda login' first): %w", err)
		}
		servers = cfg.ActiveEnvNATSServers()
	}
	nc, err := natsio.Connect(servers, natsio.MaxReconnects(3), natsio.ReconnectWait(2*time.Second))
	if err != nil {
		return nil, fmt.Errorf("failed to connect to NATS: %w", err)
	}
	return nc, nil
}
