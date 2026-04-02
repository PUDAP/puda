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

	"github.com/PUDAP/puda/apps/cli/internal/db"
	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/google/uuid"
	natsio "github.com/nats-io/nats.go"
	"github.com/spf13/cobra"
)

const heartbeatTimeout = 2 * time.Second

var machineNatsServers string
var machineListJSON bool
var watchTargets []string
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

var machineHomeCmd = &cobra.Command{
	Use:   "home <machine_id> [machine_id...]",
	Short: "Send home commands to one or more machines",
	Args:  cobra.MinimumNArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		return homeMachines(args)
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
	Use:   "watch --targets <machine_id1,machine_id2> [--subjects <subject1,subject2>]",
	Short: "Stream telemetry and events from one or more machines as NDJSON",
	Long: `Subscribe to puda.<machine_id>.tlm.* and puda.<machine_id>.evt.* for each
target and stream every message to stdout as newline-delimited JSON.

If --subjects is omitted all subjects are included. Use --timeout to auto-stop
after N seconds, or Ctrl-C to stop.`,
	Args: cobra.NoArgs,
	RunE: func(cmd *cobra.Command, args []string) error {
		if len(watchTargets) == 0 {
			return fmt.Errorf("at least one target is required (use --targets)")
		}

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

		events, err := pudanats.SubscribeMachineSubjects(ctx, nc, watchTargets, opts)
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
	machineCmd.PersistentFlags().StringVar(&machineNatsServers, "nats-servers", "", "Comma-separated NATS server URLs (overrides project config.json)")
	machineListCmd.Flags().BoolVar(&machineListJSON, "json", false, "Output machine list as JSON")
	machineWatchCmd.Flags().StringSliceVar(&watchTargets, "targets", nil, "Comma-separated list of machine IDs to watch")
	machineWatchCmd.MarkFlagRequired("targets")
	machineWatchCmd.Flags().IntVar(&watchTimeout, "timeout", 0, "Auto-stop after N seconds (0 = run until interrupted)")
	machineWatchCmd.Flags().StringSliceVar(&watchSubjects, "subjects", nil, "Comma-separated list of subjects to include (e.g. pos,health,alert)")
	machineWatchCmd.Flags().BoolVar(&watchIncludeHeartbeat, "include-heartbeat", false, "Include heartbeat messages (excluded by default)")
	machineCmd.AddCommand(machineListCmd)
	machineCmd.AddCommand(machineStateCmd)
	machineCmd.AddCommand(machineResetCmd)
	machineCmd.AddCommand(machineHomeCmd)
	machineCmd.AddCommand(machineCommandsCmd)
	machineCmd.AddCommand(machineWatchCmd)
}

func homeMachines(machineIDs []string) error {
	globalConfig, err := puda.LoadGlobalConfig()
	if err != nil {
		return fmt.Errorf("failed to load global config (run 'puda login' first): %w", err)
	}
	userID := globalConfig.User.UserID
	username := globalConfig.User.Username
	if userID == "" || username == "" {
		return fmt.Errorf("user not logged in. Please run 'puda login' first")
	}

	nc, err := connectMachineNATS()
	if err != nil {
		return err
	}
	defer nc.Close()

	store, err := db.Connect()
	if err != nil {
		store = nil
	} else {
		defer store.Disconnect()
	}

	js, err := nc.JetStream()
	if err != nil {
		return fmt.Errorf("failed to get JetStream context: %w", err)
	}

	dispatcher := pudanats.NewResponseDispatcher(js, userID)
	if err := dispatcher.Start(); err != nil {
		return fmt.Errorf("failed to start response dispatcher: %w", err)
	}
	defer dispatcher.Close()

	runID := uuid.New().String()
	if store != nil {
		if err := store.InsertRun(runID, nil); err != nil {
			return fmt.Errorf("failed to create run for home command: %w", err)
		}
	}

	requests := make([]puda.CommandRequest, 0, len(machineIDs))
	for i, machineID := range machineIDs {
		requests = append(requests, puda.CommandRequest{
			Name:       "home",
			Params:     make(map[string]interface{}),
			StepNumber: i + 1,
			Version:    "1.0",
			MachineID:  machineID,
		})
	}

	if err := pudanats.SendQueueCommands(js, dispatcher, requests, runID, userID, username, store); err != nil {
		return fmt.Errorf("home command failed: %w", err)
	}

	fmt.Fprintf(os.Stdout, "Home commands sent successfully to %d machine(s)\n", len(machineIDs))
	return nil
}

func connectMachineNATS() (*natsio.Conn, error) {
	servers := machineNatsServers
	if servers == "" {
		cfg, err := puda.LoadProjectConfig()
		if err != nil {
			return nil, fmt.Errorf("NATS endpoint required (set in project config.json or use --nats-servers): %w", err)
		}
		servers = cfg.Endpoints.NATS
	}
	if servers == "" {
		return nil, fmt.Errorf("NATS endpoint required (set in project config.json or use --nats-servers)")
	}
	nc, err := natsio.Connect(servers, natsio.MaxReconnects(3), natsio.ReconnectWait(2*time.Second))
	if err != nil {
		return nil, fmt.Errorf("failed to connect to NATS: %w", err)
	}
	return nc, nil
}
