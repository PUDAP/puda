package cli

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/signal"
	"regexp"
	"sort"
	"strings"
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
var machineHuman bool
var machineCommandName string
var machineListTimeout time.Duration
var machinePingTimeout time.Duration
var watchMachines []string
var watchTimeout int
var watchSubjects []string
var watchIncludeHeartbeat bool

var machineCommandHeaderRe = regexp.MustCompile(`^([A-Za-z_][A-Za-z0-9_]*)\(`)

var machineCmd = &cobra.Command{
	Use:   "machine",
	Short: "Machine operations",
	Long: `Commands for machine operations.

Output is a JSON object by default. Use --human for a text summary.`,
	Run: func(cmd *cobra.Command, args []string) {
		cmd.Help()
	},
}

var machineListCmd = &cobra.Command{
	Use:   "list",
	Short: "Discover responsive machines via Core NATS ping",
	Long:  `Broadcast ping on puda.cmd.ping and list machines that reply with pong as JSON.`,
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
		return writeListResults(cmd.OutOrStdout(), machines, machineHuman)
	},
}

var machinePingCmd = &cobra.Command{
	Use:   "ping <machine_ids>",
	Short: "Check if machines are online",
	Long: `Send Core NATS ping requests to machine(s) and report pong details as JSON.
Machine IDs can be comma-separated, e.g. puda machine ping first,biologic.
Use --human for a text summary.`,
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
		if err := writePingResults(cmd.OutOrStdout(), results, machineHuman); err != nil {
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

func writePingResults(w io.Writer, results []pudanats.PingResult, human bool) error {
	if !human {
		responded := 0
		for _, result := range results {
			if result.Status == "pong" {
				responded++
			}
		}
		return writeJSON(w, struct {
			Results   []pudanats.PingResult `json:"results"`
			Count     int                   `json:"count"`
			Responded int                   `json:"responded"`
			Failed    int                   `json:"failed"`
		}{results, len(results), responded, len(results) - responded})
	}
	for _, result := range results {
		if result.Status != "pong" {
			fmt.Fprintf(w, "%s: failed: %s\n", result.MachineID, result.Error)
			continue
		}
		fmt.Fprintf(
			w,
			"%s: pong %.3fms status=%s sdk=%s uptime=%.3fs\n",
			result.MachineID,
			result.LatencyMS,
			result.RunStatus,
			result.SDKVersion,
			result.UptimeSeconds,
		)
	}
	return nil
}

func writeListResults(w io.Writer, machines []string, human bool) error {
	if machines == nil {
		machines = []string{}
	}
	if !human {
		return writeJSON(w, struct {
			Machines []string `json:"machines"`
			Count    int      `json:"count"`
		}{machines, len(machines)})
	}
	if len(machines) == 0 {
		fmt.Fprintln(w, "No machines found.")
		return nil
	}
	fmt.Fprintf(w, "%d machines found:\n", len(machines))
	for _, id := range machines {
		fmt.Fprintf(w, "  %s\n", id)
	}
	return nil
}

func writeJSON(w io.Writer, v any) error {
	encoded, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to encode JSON: %w", err)
	}
	_, err = fmt.Fprintln(w, string(encoded))
	return err
}

type machineCommandBlock struct {
	Name string
	Text string
}

func parseCommandNames(value string) []string {
	parts := strings.Split(value, ",")
	names := make([]string, 0, len(parts))
	seen := make(map[string]struct{}, len(parts))
	for _, part := range parts {
		name := strings.TrimSpace(part)
		if name == "" {
			continue
		}
		if _, exists := seen[name]; exists {
			continue
		}
		seen[name] = struct{}{}
		names = append(names, name)
	}
	return names
}

func extractMachineCommandText(commands, namesSpec string) (string, error) {
	requested := parseCommandNames(namesSpec)
	if len(requested) == 0 {
		return "", fmt.Errorf("at least one command name is required")
	}

	blocks := splitMachineCommandBlocks(commands)
	available := make([]string, 0, len(blocks))
	byName := make(map[string]string, len(blocks))
	for _, block := range blocks {
		available = append(available, block.Name)
		byName[block.Name] = block.Text
	}

	selected := make([]string, 0, len(requested))
	missing := make([]string, 0)
	for _, name := range requested {
		text, ok := byName[name]
		if !ok {
			missing = append(missing, name)
			continue
		}
		selected = append(selected, text)
	}
	if len(missing) > 0 {
		label := "command"
		if len(missing) > 1 {
			label = "commands"
		}
		quoted := make([]string, len(missing))
		for i, name := range missing {
			quoted[i] = fmt.Sprintf("%q", name)
		}
		if len(available) == 0 {
			return "", fmt.Errorf("%s %s not found", label, strings.Join(quoted, ", "))
		}
		return "", fmt.Errorf("%s %s not found; available: %s", label, strings.Join(quoted, ", "), strings.Join(available, ", "))
	}
	return strings.Join(selected, "\n\n"), nil
}

func splitMachineCommandBlocks(commands string) []machineCommandBlock {
	normalized := strings.ReplaceAll(commands, "\r\n", "\n")
	lines := strings.Split(strings.TrimSuffix(normalized, "\n"), "\n")
	if len(lines) == 1 && lines[0] == "" {
		return nil
	}

	var blocks []machineCommandBlock
	var currentName string
	var currentLines []string
	flush := func() {
		if currentName == "" {
			return
		}
		for len(currentLines) > 0 && strings.TrimSpace(currentLines[len(currentLines)-1]) == "" {
			currentLines = currentLines[:len(currentLines)-1]
		}
		blocks = append(blocks, machineCommandBlock{
			Name: currentName,
			Text: strings.Join(currentLines, "\n"),
		})
		currentName = ""
		currentLines = nil
	}

	for _, line := range lines {
		if matches := machineCommandHeaderRe.FindStringSubmatch(line); matches != nil {
			flush()
			currentName = matches[1]
			currentLines = []string{line}
			continue
		}
		if currentName != "" {
			currentLines = append(currentLines, line)
		}
	}
	flush()
	return blocks
}

var machineCommandsCmd = &cobra.Command{
	Use:   "commands <machine_id>",
	Short: "Show available commands for a machine",
	Long: `Show advertised commands for a machine.

Use --command to show one or more commands by name. Command names can be
comma-separated, e.g. puda machine commands first --command home,move_to

Examples:
  puda machine commands first
  puda machine commands first --command move_to
  puda machine commands first --command home,move_to`,
	Args: cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		nc, err := connectMachineNATS()
		if err != nil {
			return err
		}
		defer nc.Close()
		commands, err := pudanats.GetMachineCommands(nc, args[0])
		if err != nil {
			return err
		}
		if name := strings.TrimSpace(machineCommandName); name != "" {
			commands, err = extractMachineCommandText(commands, name)
			if err != nil {
				return err
			}
		}
		if machineHuman {
			fmt.Fprintln(cmd.OutOrStdout(), commands)
			return nil
		}
		return writeJSON(cmd.OutOrStdout(), struct {
			MachineID string `json:"machine_id"`
			Commands  string `json:"commands"`
		}{args[0], commands})
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

Use --timeout to auto-stop after N seconds, or Ctrl-C to stop.
Use --human for a text line per event instead of NDJSON.`,
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
			if machineHuman {
				fmt.Fprintf(
					os.Stdout,
					"%s %s %s.%s %s\n",
					evt.Timestamp.UTC().Format(time.RFC3339Nano),
					evt.MachineID,
					evt.Category,
					evt.Topic,
					string(evt.Data),
				)
				continue
			}
			if err := enc.Encode(evt); err != nil {
				return fmt.Errorf("failed to write event: %w", err)
			}
		}
		return nil
	},
}

func init() {
	machineCmd.PersistentFlags().StringVar(&machineNatsServers, "nats-servers", "", "Comma-separated NATS server URLs (overrides active env)")
	machineCmd.PersistentFlags().BoolVar(&machineHuman, "human", false, "Output as human-readable text instead of JSON")
	machineListCmd.Flags().DurationVar(&machineListTimeout, "timeout", defaultPingDiscoveryTimeout, "How long to collect pong replies")
	machinePingCmd.Flags().DurationVar(&machinePingTimeout, "timeout", 2*time.Second, "Timeout for each ping request")
	machineCommandsCmd.Flags().StringVar(&machineCommandName, "command", "", "Show only these advertised commands (comma-separated)")
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
