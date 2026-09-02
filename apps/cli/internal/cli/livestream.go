package cli

import (
	"fmt"
	"io"
	"strings"

	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
	natsio "github.com/nats-io/nats.go"
	"github.com/spf13/cobra"
)

var livestreamNatsServers string
var livestreamHuman bool
var livestreamAddName string
var livestreamAddHost string
var livestreamAddDescription string
var livestreamAddMachines string
var livestreamAttachMachines string
var livestreamDetachMachines string
var livestreamListHosts string
var livestreamListMachines string

var livestreamCmd = &cobra.Command{
	Use:   "livestream",
	Short: "Manage the fleet livestream registry",
	Long: `Register camera streams and attach them to machines.

Livestreams are fleet records in NATS KV, not edge config. One stream can
serve many machines; one machine can have many streams; one host can have
many streams.

Output is a JSON object by default. Use --human for a text summary.`,
	Run: func(cmd *cobra.Command, args []string) {
		cmd.Help()
	},
}

var livestreamAddCmd = &cobra.Command{
	Use:   "add",
	Short: "Create or update a livestream",
	Long: `Create a livestream or update an existing name.

An existing name updates host and description and unions --machines.
The CLI derives RTSP, RTMP, HLS, and WebRTC URLs from host and name
using MediaMTX's standard ports.`,
	Args: cobra.NoArgs,
	RunE: func(cmd *cobra.Command, args []string) error {
		nc, err := connectLivestreamNATS()
		if err != nil {
			return err
		}
		defer nc.Close()

		stream, err := pudanats.PutLivestream(nc, pudanats.Livestream{
			Name:        livestreamAddName,
			Host:        livestreamAddHost,
			Description: livestreamAddDescription,
			MachineIDs:  parseMachineIDs([]string{livestreamAddMachines}),
		})
		if err != nil {
			return err
		}
		return writeLivestreamResult(cmd.OutOrStdout(), stream, livestreamHuman)
	},
}

var livestreamListCmd = &cobra.Command{
	Use:   "list",
	Short: "List registered livestreams",
	Long: `List fleet livestreams grouped by MediaMTX host.

With no flags, every registered stream is listed. Use --hosts to show only
those MediaMTX hosts. Use --machines to show only streams attached to those
machine IDs. Host and machine filters combine.

Examples:
  puda livestream list
  puda livestream list --hosts first
  puda livestream list --hosts first,lab
  puda livestream list --machines first
  puda livestream list --hosts first --machines first,biologic`,
	Args: cobra.NoArgs,
	RunE: func(cmd *cobra.Command, args []string) error {
		nc, err := connectLivestreamNATS()
		if err != nil {
			return err
		}
		defer nc.Close()

		hosts := parseMachineIDs([]string{livestreamListHosts})
		machines := parseMachineIDs([]string{livestreamListMachines})
		streams, err := pudanats.ListLivestreamsFiltered(nc, hosts, machines)
		if err != nil {
			return err
		}
		return writeLivestreamList(cmd.OutOrStdout(), streams, livestreamHuman)
	},
}

var livestreamRmCmd = &cobra.Command{
	Use:   "rm <name>",
	Short: "Remove a livestream",
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		nc, err := connectLivestreamNATS()
		if err != nil {
			return err
		}
		defer nc.Close()

		name, err := pudanats.NormalizeLivestreamName(args[0])
		if err != nil {
			return err
		}
		if err := pudanats.DeleteLivestream(nc, name); err != nil {
			return err
		}
		if livestreamHuman {
			fmt.Fprintf(cmd.OutOrStdout(), "removed %s\n", name)
			return nil
		}
		return writeJSON(cmd.OutOrStdout(), struct {
			Removed string `json:"removed"`
		}{name})
	},
}

var livestreamAttachCmd = &cobra.Command{
	Use:   "attach <name>",
	Short: "Attach machines to a livestream",
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		nc, err := connectLivestreamNATS()
		if err != nil {
			return err
		}
		defer nc.Close()

		stream, err := pudanats.AttachLivestreamMachines(nc, args[0], parseMachineIDs([]string{livestreamAttachMachines}))
		if err != nil {
			return err
		}
		return writeLivestreamResult(cmd.OutOrStdout(), stream, livestreamHuman)
	},
}

var livestreamDetachCmd = &cobra.Command{
	Use:   "detach <name>",
	Short: "Detach machines from a livestream",
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		nc, err := connectLivestreamNATS()
		if err != nil {
			return err
		}
		defer nc.Close()

		stream, err := pudanats.DetachLivestreamMachines(nc, args[0], parseMachineIDs([]string{livestreamDetachMachines}))
		if err != nil {
			return err
		}
		return writeLivestreamResult(cmd.OutOrStdout(), stream, livestreamHuman)
	},
}

func writeLivestreamResult(w io.Writer, stream pudanats.Livestream, human bool) error {
	if !human {
		return writeJSON(w, stream)
	}
	fmt.Fprintln(w, formatLivestreamHuman(stream))
	return nil
}

func writeLivestreamList(w io.Writer, streams []pudanats.Livestream, human bool) error {
	if streams == nil {
		streams = []pudanats.Livestream{}
	}
	byHost := pudanats.GroupLivestreamsByHost(streams)
	if !human {
		return writeJSON(w, struct {
			Livestreams map[string]map[string]livestreamListItem `json:"livestreams"`
			Count       int                                      `json:"count"`
		}{hostedLivestreamsJSON(byHost), len(streams)})
	}
	if len(streams) == 0 {
		fmt.Fprintln(w, "No livestreams registered.")
		return nil
	}
	hosts := pudanats.SortedLivestreamHosts(byHost)
	fmt.Fprintf(w, "%d livestreams on %d hosts:\n", len(streams), len(hosts))
	for _, host := range hosts {
		fmt.Fprintf(w, "  %s:\n", host)
		for _, name := range pudanats.SortedLivestreamNames(byHost[host]) {
			fmt.Fprintf(w, "    %s\n", formatLivestreamUnderHost(byHost[host][name]))
		}
	}
	return nil
}

type livestreamListItem struct {
	Description string                  `json:"description"`
	MachineIDs  []string                `json:"machine_ids"`
	URLs        pudanats.LivestreamURLs `json:"urls"`
}

func hostedLivestreamsJSON(byHost map[string]map[string]pudanats.Livestream) map[string]map[string]livestreamListItem {
	out := make(map[string]map[string]livestreamListItem, len(byHost))
	for host, byName := range byHost {
		items := make(map[string]livestreamListItem, len(byName))
		for name, stream := range byName {
			ids := stream.MachineIDs
			if ids == nil {
				ids = []string{}
			}
			items[name] = livestreamListItem{
				Description: stream.Description,
				MachineIDs:  ids,
				URLs:        stream.URLs,
			}
		}
		out[host] = items
	}
	return out
}

func formatLivestreamHuman(stream pudanats.Livestream) string {
	machines := "no machines"
	if len(stream.MachineIDs) == 1 {
		machines = stream.MachineIDs[0]
	} else if len(stream.MachineIDs) > 1 {
		machines = strings.Join(stream.MachineIDs, ", ")
	}
	return fmt.Sprintf(
		"%s: %s\n    host: %s\n    hls: %s\n    webrtc: %s\n    rtsp: %s\n    rtmp: %s\n    machines: %s",
		stream.Name,
		stream.Description,
		stream.Host,
		stream.URLs.HLS,
		stream.URLs.WebRTC,
		stream.URLs.RTSP,
		stream.URLs.RTMP,
		machines,
	)
}

func formatLivestreamUnderHost(stream pudanats.Livestream) string {
	machines := "no machines"
	if len(stream.MachineIDs) == 1 {
		machines = stream.MachineIDs[0]
	} else if len(stream.MachineIDs) > 1 {
		machines = strings.Join(stream.MachineIDs, ", ")
	}
	return fmt.Sprintf(
		"%s: %s\n      hls: %s\n      webrtc: %s\n      rtsp: %s\n      rtmp: %s\n      machines: %s",
		stream.Name,
		stream.Description,
		stream.URLs.HLS,
		stream.URLs.WebRTC,
		stream.URLs.RTSP,
		stream.URLs.RTMP,
		machines,
	)
}

func formatLivestreamRefHuman(stream pudanats.LivestreamRef) string {
	return fmt.Sprintf(
		"livestream %s: %s\n    host: %s\n    hls: %s\n    webrtc: %s\n    rtsp: %s\n    rtmp: %s",
		stream.Name,
		stream.Description,
		stream.Host,
		stream.URLs.HLS,
		stream.URLs.WebRTC,
		stream.URLs.RTSP,
		stream.URLs.RTMP,
	)
}

func connectLivestreamNATS() (*natsio.Conn, error) {
	return connectNATS(livestreamNatsServers)
}

func init() {
	livestreamCmd.PersistentFlags().StringVar(&livestreamNatsServers, "nats-servers", "", "Comma-separated NATS server URLs (overrides active env)")
	livestreamCmd.PersistentFlags().BoolVar(&livestreamHuman, "human", false, "Output as human-readable text instead of JSON")
	livestreamAddCmd.Flags().StringVar(&livestreamAddName, "name", "", "MediaMTX stream name and registry key")
	livestreamAddCmd.Flags().StringVar(&livestreamAddHost, "host", "", "Hostname or IP address")
	livestreamAddCmd.Flags().StringVar(&livestreamAddDescription, "description", "", "Short visual-context description")
	livestreamAddCmd.Flags().StringVar(&livestreamAddMachines, "machines", "", "Comma-separated machine IDs to attach")
	livestreamAddCmd.MarkFlagRequired("name")
	livestreamAddCmd.MarkFlagRequired("host")
	livestreamAddCmd.MarkFlagRequired("description")
	livestreamListCmd.Flags().StringVar(&livestreamListHosts, "hosts", "", "Comma-separated hostname or IP address")
	livestreamListCmd.Flags().StringVar(&livestreamListMachines, "machines", "", "Comma-separated machine IDs (default: all)")
	livestreamAttachCmd.Flags().StringVar(&livestreamAttachMachines, "machines", "", "Comma-separated machine IDs to attach")
	livestreamAttachCmd.MarkFlagRequired("machines")
	livestreamDetachCmd.Flags().StringVar(&livestreamDetachMachines, "machines", "", "Comma-separated machine IDs to detach")
	livestreamDetachCmd.MarkFlagRequired("machines")
	livestreamCmd.AddCommand(livestreamAddCmd)
	livestreamCmd.AddCommand(livestreamListCmd)
	livestreamCmd.AddCommand(livestreamRmCmd)
	livestreamCmd.AddCommand(livestreamAttachCmd)
	livestreamCmd.AddCommand(livestreamDetachCmd)
}
