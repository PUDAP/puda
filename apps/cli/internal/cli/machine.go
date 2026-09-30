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
var machineYes bool
var machineCommandName string
var machineListTimeout time.Duration
var machineInfoTimeout time.Duration
var watchMachines []string
var watchTimeout int
var watchIncludeHeartbeat bool

var machineCommandHeaderRe = regexp.MustCompile(`^([A-Za-z_][A-Za-z0-9_]*)\(`)

var machineCmd = &cobra.Command{
	Use:   "machine",
	Short: "Machine operations",
	Long: `Commands for machine operations.

Output is a JSON object by default. Use --human for a text summary.
Use --yes/-y to skip safety confirmation prompts.`,
	Run: func(cmd *cobra.Command, args []string) {
		cmd.Help()
	},
}

var machineListCmd = &cobra.Command{
	Use:   "list",
	Short: "Discover responsive machines via Core NATS ping",
	Long: `Broadcast ping on puda.cmd.ping and list machines that reply with pong as JSON, including each edge's advertised description, livestream_count, and tlm_stream_count.

livestream_count is how many livestreams are registered with PUDA for that machine. Other cameras may exist on the host and not appear here. Use puda livestream list --machines <id> for registered names, hosts, and URLs.
tlm_stream_count is how many telemetry streams the edge advertises. Use puda machine info <id> for their names, subjects, and intervals.
Use --human for a text summary.`,
	RunE: func(cmd *cobra.Command, args []string) error {
		nc, err := connectMachineNATS()
		if err != nil {
			return err
		}
		defer nc.Close()

		pongs, err := pudanats.ListMachinePongs(nc, machineListTimeout)
		if err != nil {
			return err
		}
		sort.Slice(pongs, func(i, j int) bool {
			return pongs[i].MachineID < pongs[j].MachineID
		})
		byMachine, err := pudanats.LivestreamsByMachine(nc)
		if err != nil {
			return err
		}
		return writeListResults(cmd.OutOrStdout(), pongs, byMachine, machineHuman)
	},
}

var machineInfoCmd = &cobra.Command{
	Use:     "info <machine_ids>",
	Aliases: []string{"ping"},
	Short:   "Show whether machines are online and what they advertise",
	Long: `Send Core NATS ping requests to machine(s) and report pong details as JSON, including each edge's advertised description, telemetry streams (tlm_streams), and livestreams attached in the fleet registry.
Each tlm_stream lists the subject it publishes on (puda.<machine_id>.tlm.stream.<name>) and its interval in seconds.
Machine IDs can be comma-separated, e.g. puda machine info first,biologic.
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

		results := pudanats.PingMachines(nc, machineIDs, machineInfoTimeout)
		byMachine, err := pudanats.LivestreamsByMachine(nc)
		if err != nil {
			return err
		}
		if err := writeInfoResults(cmd.OutOrStdout(), results, byMachine, machineHuman); err != nil {
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

type infoResultJSON struct {
	MachineID     string                   `json:"machine_id"`
	Status        string                   `json:"status"`
	Timestamp     string                   `json:"timestamp,omitempty"`
	SDKVersion    string                   `json:"sdk_version,omitempty"`
	UptimeSeconds float64                  `json:"uptime_seconds,omitempty"`
	RunStatus     string                   `json:"run_status,omitempty"`
	Description   string                   `json:"description,omitempty"`
	LocalIP       string                   `json:"local_ip,omitempty"`
	TailscaleIP   string                   `json:"tailscale_ip,omitempty"`
	MagicDNS      string                   `json:"magicdns,omitempty"`
	LatencyMS     float64                  `json:"latency_ms,omitempty"`
	Error         string                   `json:"error,omitempty"`
	TlmStreams    []pudanats.TlmStream     `json:"tlm_streams"`
	Livestreams   []pudanats.LivestreamRef `json:"livestreams"`
}

func infoResultWithLivestreams(result pudanats.PingResult, refs []pudanats.LivestreamRef) infoResultJSON {
	if refs == nil {
		refs = []pudanats.LivestreamRef{}
	}
	tlmStreams := result.TlmStreams
	if tlmStreams == nil {
		tlmStreams = []pudanats.TlmStream{}
	}
	return infoResultJSON{
		MachineID:     result.MachineID,
		Status:        result.Status,
		Timestamp:     result.Timestamp,
		SDKVersion:    result.SDKVersion,
		UptimeSeconds: result.UptimeSeconds,
		RunStatus:     result.RunStatus,
		Description:   result.Description,
		LocalIP:       result.LocalIP,
		TailscaleIP:   result.TailscaleIP,
		MagicDNS:      result.MagicDNS,
		LatencyMS:     result.LatencyMS,
		Error:         result.Error,
		TlmStreams:    tlmStreams,
		Livestreams:   refs,
	}
}

func formatTlmStreamHuman(stream pudanats.TlmStream) string {
	line := "tlm_stream " + stream.Name
	if stream.Interval != nil {
		line += fmt.Sprintf(" every %gs", *stream.Interval)
	} else {
		line += " (no fixed interval)"
	}
	if stream.Description != "" {
		line += ": " + stream.Description
	}
	return line + "\n    subject: " + stream.Subject
}

func writeInfoResults(w io.Writer, results []pudanats.PingResult, byMachine map[string][]pudanats.LivestreamRef, human bool) error {
	if !human {
		responded := 0
		payload := make([]infoResultJSON, 0, len(results))
		for _, result := range results {
			if result.Status == "pong" {
				responded++
			}
			payload = append(payload, infoResultWithLivestreams(result, byMachine[result.MachineID]))
		}
		return writeJSON(w, struct {
			Results   []infoResultJSON `json:"results"`
			Count     int              `json:"count"`
			Responded int              `json:"responded"`
			Failed    int              `json:"failed"`
		}{payload, len(results), responded, len(results) - responded})
	}
	for _, result := range results {
		if result.Status != "pong" {
			fmt.Fprintf(w, "%s: failed: %s\n", result.MachineID, result.Error)
		} else {
			fmt.Fprintf(
				w,
				"%s: pong %.3fms status=%s sdk=%s uptime=%.3fs\n",
				result.MachineID,
				result.LatencyMS,
				result.RunStatus,
				result.SDKVersion,
				result.UptimeSeconds,
			)
			if result.Description != "" {
				fmt.Fprintf(w, "  %s\n", result.Description)
			}
		}
		for _, stream := range result.TlmStreams {
			fmt.Fprintf(w, "  %s\n", formatTlmStreamHuman(stream))
		}
		for _, stream := range pudanats.LivestreamsForMachine(byMachine, result.MachineID) {
			fmt.Fprintf(w, "  %s\n", formatLivestreamRefHuman(stream))
		}
		if line := pingNetworkLine(result); line != "" {
			fmt.Fprintf(w, "  %s\n", line)
		}
	}
	return nil
}

type listedMachine struct {
	MachineID       string `json:"machine_id"`
	Description     string `json:"description"`
	LocalIP         string `json:"local_ip,omitempty"`
	TailscaleIP     string `json:"tailscale_ip,omitempty"`
	MagicDNS        string `json:"magicdns,omitempty"`
	LivestreamCount int    `json:"livestream_count"`
	TlmStreamCount  int    `json:"tlm_stream_count"`
}

func pingNetworkLine(result pudanats.PingResult) string {
	parts := make([]string, 0, 3)
	if result.LocalIP != "" {
		parts = append(parts, "local_ip="+result.LocalIP)
	}
	if result.TailscaleIP != "" {
		parts = append(parts, "tailscale_ip="+result.TailscaleIP)
	}
	if result.MagicDNS != "" {
		parts = append(parts, "magicdns="+result.MagicDNS)
	}
	return strings.Join(parts, " ")
}

func pluralCount(n int, singular string) string {
	if n == 1 {
		return "1 " + singular
	}
	return fmt.Sprintf("%d %ss", n, singular)
}

func listedMachineLabel(pong pudanats.PingResult, livestreamCount int) string {
	label := pong.MachineID
	if pong.Description != "" {
		label += ": " + pong.Description
	}
	parts := make([]string, 0, 2)
	if livestreamCount > 0 {
		parts = append(parts, pluralCount(livestreamCount, "registered livestream"))
	}
	if n := len(pong.TlmStreams); n > 0 {
		parts = append(parts, pluralCount(n, "tlm stream"))
	}
	if len(parts) == 0 {
		return label
	}
	return label + " (" + strings.Join(parts, ", ") + ")"
}

func writeListResults(w io.Writer, pongs []pudanats.PingResult, byMachine map[string][]pudanats.LivestreamRef, human bool) error {
	if pongs == nil {
		pongs = []pudanats.PingResult{}
	}
	machines := make([]listedMachine, 0, len(pongs))
	for _, pong := range pongs {
		machines = append(machines, listedMachine{
			MachineID:       pong.MachineID,
			Description:     pong.Description,
			LocalIP:         pong.LocalIP,
			TailscaleIP:     pong.TailscaleIP,
			MagicDNS:        pong.MagicDNS,
			LivestreamCount: len(pudanats.LivestreamsForMachine(byMachine, pong.MachineID)),
			TlmStreamCount:  len(pong.TlmStreams),
		})
	}
	if !human {
		return writeJSON(w, struct {
			Machines []listedMachine `json:"machines"`
			Count    int             `json:"count"`
		}{machines, len(machines)})
	}
	if len(pongs) == 0 {
		fmt.Fprintln(w, "No machines found.")
		return nil
	}
	fmt.Fprintf(w, "%d machines found:\n", len(pongs))
	for _, pong := range pongs {
		count := len(pudanats.LivestreamsForMachine(byMachine, pong.MachineID))
		fmt.Fprintf(w, "  %s\n", listedMachineLabel(pong, count))
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
		payload, err := pudanats.GetMachineCommands(nc, args[0])
		if err != nil {
			return err
		}
		commands := payload.Commands
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
	Use:   "watch [subject...] [--machines <machine_id1,machine_id2>]",
	Short: "Stream machine traffic as NDJSON",
	Long: `Stream NATS messages to stdout as NDJSON.

Pass subjects as arguments: puda.<machine_id>.<category>.<topic>, as printed by
puda machine info. Wildcards: * matches one token, > matches the rest. Quote them in the shell.
  puda machine watch puda.balance.tlm.stream.weight
  puda machine watch 'puda.*.tlm.stream.>'

Topics:
  tlm: heartbeat, health, stream.<name>
  cmd: queue, immediate, response.queue, response.immediate
  evt: log, alert, media; update: update, update.response

With no subject arguments, watches puda.<machine_id>.> for each --machines ID,
or puda.*.> for all machines. Subject arguments and --machines cannot be combined.
Heartbeats are excluded unless --include-heartbeat is set or a subject names tlm.heartbeat.`,
	RunE: func(cmd *cobra.Command, args []string) error {
		subjects, err := pudanats.WatchSubjects(watchMachines, args)
		if err != nil {
			return err
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

		opts := pudanats.WatchOpts{IncludeHeartbeat: watchIncludeHeartbeat}
		events, err := pudanats.SubscribeMachineSubjects(ctx, nc, subjects, opts)
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
	machineCmd.PersistentFlags().BoolVarP(&machineYes, "yes", "y", false, "Skip safety confirmation prompts")
	machineListCmd.Flags().DurationVar(&machineListTimeout, "timeout", defaultPingDiscoveryTimeout, "How long to collect pong replies")
	machineInfoCmd.Flags().DurationVar(&machineInfoTimeout, "timeout", 2*time.Second, "Timeout for each ping request")
	machineCommandsCmd.Flags().StringVar(&machineCommandName, "command", "", "Show only these advertised commands (comma-separated)")
	machineWatchCmd.Flags().StringSliceVarP(&watchMachines, "machines", "m", nil, "Comma-separated list of machine IDs to watch (default: all machines)")
	machineWatchCmd.Flags().IntVar(&watchTimeout, "timeout", 0, "Auto-stop after N seconds (0 = run until interrupted)")
	machineWatchCmd.Flags().BoolVar(&watchIncludeHeartbeat, "include-heartbeat", false, "Include heartbeat messages (excluded by default)")
	machineCmd.AddCommand(machineListCmd)
	machineCmd.AddCommand(machineInfoCmd)
	machineCmd.AddCommand(machineCommandsCmd)
	machineCmd.AddCommand(machineWatchCmd)
}

func connectMachineNATS() (*natsio.Conn, error) {
	return connectNATS(machineNatsServers)
}

func resolveGatewayServers(override string) (string, error) {
	if override != "" {
		return override, nil
	}
	cfg, err := puda.LoadGlobalConfig()
	if err != nil {
		return "", nil
	}
	return cfg.GatewayServers, nil
}

func resolveNATSServers(override string) (string, error) {
	servers := override
	if servers == "" {
		cfg, err := puda.LoadGlobalConfig()
		if err != nil {
			return "", fmt.Errorf("failed to load global config (run 'puda login' first): %w", err)
		}
		servers = cfg.NATSServers
	}
	if servers == "" {
		return "", fmt.Errorf("NATS servers not configured; run 'puda config set nats_servers <url>'")
	}
	return servers, nil
}

func connectNATS(override string) (*natsio.Conn, error) {
	servers, err := resolveNATSServers(override)
	if err != nil {
		return nil, err
	}
	nc, err := natsio.Connect(servers, natsio.MaxReconnects(3), natsio.ReconnectWait(2*time.Second))
	if err != nil {
		return nil, fmt.Errorf("failed to connect to NATS: %w", err)
	}
	return nc, nil
}
