package cli

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
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

const (
	heartbeatTimeout            = 1500 * time.Millisecond
	defaultPingDiscoveryTimeout = 1 * time.Second
)

var machineNatsServers string
var machineListJSON bool
var machineListTimeout time.Duration
var machinePingTimeout time.Duration
var machinePingJSON bool
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
	Short: "Discover responsive machines via Core NATS ping",
	Long:  `Broadcast ping on puda.cmd.ping and list machines that reply with pong.`,
	RunE: func(cmd *cobra.Command, args []string) error {
		nc, err := connectMachineNATS()
		if err != nil {
			return err
		}
		defer nc.Close()

		machines, err := pudanats.ListMachines(nc, machineListTimeout)
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

var machinePingCmd = &cobra.Command{
	Use:   "ping <machine_ids>",
	Short: "Check if machines are online",
	Long: `Send Core NATS ping requests to machine(s) and report pong details.
Machine IDs can be comma-separated, e.g. puda machine ping first,biologic.`,
	Args: cobra.MinimumNArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		machineIDs := parseMachineIDs(args)
		if len(machineIDs) == 0 {
			return fmt.Errorf("at least one machine ID is required")
		}
		nc, err := connectMachineNATS()
		if err != nil {
			return err
		}
		defer nc.Close()

		results := pudanats.PingMachines(nc, machineIDs, machinePingTimeout)
		if err := writePingResults(cmd.OutOrStdout(), results, machinePingJSON); err != nil {
			return err
		}
		failed := 0
		for _, result := range results {
			if result.Status != "pong" {
				failed++
			}
		}
		if failed > 0 {
			return fmt.Errorf("%d machine(s) failed to respond", failed)
		}
		return nil
	},
}

func writePingResults(w io.Writer, results []pudanats.PingResult, jsonOutput bool) error {
	if jsonOutput {
		responded := 0
		for _, result := range results {
			if result.Status == "pong" {
				responded++
			}
		}
		payload := struct {
			Results   []pudanats.PingResult `json:"results"`
			Count     int                   `json:"count"`
			Responded int                   `json:"responded"`
			Failed    int                   `json:"failed"`
		}{results, len(results), responded, len(results) - responded}
		encoded, err := json.MarshalIndent(payload, "", "  ")
		if err != nil {
			return fmt.Errorf("failed to encode ping results: %w", err)
		}
		_, err = fmt.Fprintln(w, string(encoded))
		return err
	}
	for _, result := range results {
		if result.Status != "pong" {
			fmt.Fprintf(w, "%s: failed: %s\n", result.MachineID, result.Error)
			continue
		}
		fmt.Fprintf(
			w,
			"%s: pong %.3fms sdk=%s uptime=%.3fs\n",
			result.MachineID,
			result.LatencyMS,
			result.SDKVersion,
			result.UptimeSeconds,
		)
	}
	return nil
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
	machineListCmd.Flags().DurationVar(&machineListTimeout, "timeout", defaultPingDiscoveryTimeout, "How long to collect pong replies")
	machinePingCmd.Flags().DurationVar(&machinePingTimeout, "timeout", 2*time.Second, "Timeout for each ping request")
	machinePingCmd.Flags().BoolVar(&machinePingJSON, "json", false, "Output ping results as JSON")
	machineWatchCmd.Flags().StringSliceVarP(&watchMachines, "machines", "m", nil, "Comma-separated list of machine IDs to watch (default: all machines)")
	machineWatchCmd.Flags().StringSliceVar(&watchMachines, "targets", nil, "Deprecated alias for --machines")
	machineWatchCmd.Flags().MarkHidden("targets")
	machineWatchCmd.Flags().IntVar(&watchTimeout, "timeout", 0, "Auto-stop after N seconds (0 = run until interrupted)")
	machineWatchCmd.Flags().StringSliceVarP(&watchSubjects, "subjects", "s", nil, "Comma-separated category.topic prefixes to include (default: all subjects)")
	machineWatchCmd.Flags().BoolVar(&watchIncludeHeartbeat, "include-heartbeat", false, "Include heartbeat messages (excluded by default)")
	machineCmd.AddCommand(machineListCmd)
	machineCmd.AddCommand(machinePingCmd)
	machineCmd.AddCommand(machineCommandsCmd)
	machineCmd.AddCommand(machineWatchCmd)
}

func connectMachineNATS() (*natsio.Conn, error) {
	servers := machineNatsServers
	if servers == "" {
		cfg, err := puda.LoadGlobalConfig()
		if err != nil {
			return nil, fmt.Errorf("failed to load global config (run 'puda login' first): %w", err)
		}
		servers = cfg.NATSServers
	}
	if servers == "" {
		return nil, fmt.Errorf("NATS servers not configured; run 'puda config set nats_servers <url>'")
	}
	nc, err := natsio.Connect(servers, natsio.MaxReconnects(3), natsio.ReconnectWait(2*time.Second))
	if err != nil {
		return nil, fmt.Errorf("failed to connect to NATS: %w", err)
	}
	return nc, nil
}
