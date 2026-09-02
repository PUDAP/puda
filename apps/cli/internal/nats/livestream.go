package nats

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"sort"
	"strings"

	natsio "github.com/nats-io/nats.go"
)

const (
	kvBucketLivestreams = "LIVESTREAMS"

	LivestreamPortRTSP   = 8554
	LivestreamPortRTMP   = 1935
	LivestreamPortHLS    = 8888
	LivestreamPortWebRTC = 8889
)

var livestreamNameRe = regexp.MustCompile(`^[a-z0-9]+(?:-[a-z0-9]+)*$`)

// LivestreamURLs are derived from host + name using MediaMTX's standard ports.
type LivestreamURLs struct {
	HLS    string `json:"hls"`
	WebRTC string `json:"webrtc"`
	RTSP   string `json:"rtsp"`
	RTMP   string `json:"rtmp"`
}

// Livestream is a fleet camera record. NATS stores name, host, description,
// and machine_ids. URLs are computed at read time.
type Livestream struct {
	Name        string         `json:"name"`
	Host        string         `json:"host"`
	Description string         `json:"description"`
	MachineIDs  []string       `json:"machine_ids"`
	URLs        LivestreamURLs `json:"urls"`
}

type livestreamRecord struct {
	Name        string   `json:"name"`
	Host        string   `json:"host"`
	URL         string   `json:"url,omitempty"`
	Description string   `json:"description"`
	MachineIDs  []string `json:"machine_ids"`
}

// LivestreamRef is the visual-context view joined onto machine list/ping.
type LivestreamRef struct {
	Name        string         `json:"name"`
	Host        string         `json:"host"`
	Description string         `json:"description"`
	URLs        LivestreamURLs `json:"urls"`
}

func DeriveLivestreamURLs(host, name string) LivestreamURLs {
	return LivestreamURLs{
		HLS:    fmt.Sprintf("http://%s:%d/%s/", host, LivestreamPortHLS, name),
		WebRTC: fmt.Sprintf("http://%s:%d/%s/", host, LivestreamPortWebRTC, name),
		RTSP:   fmt.Sprintf("rtsp://%s:%d/%s", host, LivestreamPortRTSP, name),
		RTMP:   fmt.Sprintf("rtmp://%s:%d/%s", host, LivestreamPortRTMP, name),
	}
}

func NormalizeLivestreamHost(host string) (string, error) {
	normalized := strings.TrimSuffix(strings.TrimSpace(host), ".")
	if normalized == "" {
		return "", fmt.Errorf("livestream host is required")
	}
	if strings.Contains(normalized, "://") {
		return "", fmt.Errorf("livestream host must be a MagicDNS name or IP, not a URL")
	}
	if strings.ContainsAny(normalized, "/\\") {
		return "", fmt.Errorf("livestream host must not include a path")
	}
	if strings.Contains(normalized, ":") && !strings.HasPrefix(normalized, "[") {
		return "", fmt.Errorf("livestream host must not include a port")
	}
	return normalized, nil
}

func NormalizeLivestreamName(name string) (string, error) {
	normalized := strings.TrimSpace(name)
	if !livestreamNameRe.MatchString(normalized) {
		return "", fmt.Errorf("livestream name %q must be lowercase letters, digits, and hyphens", name)
	}
	return normalized, nil
}

func uniqueStrings(values []string) []string {
	out := make([]string, 0, len(values))
	seen := make(map[string]struct{}, len(values))
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" {
			continue
		}
		if _, exists := seen[value]; exists {
			continue
		}
		seen[value] = struct{}{}
		out = append(out, value)
	}
	return out
}

func unionStrings(existing, added []string) []string {
	return uniqueStrings(append(append([]string{}, existing...), added...))
}

func subtractStrings(existing, removed []string) []string {
	drop := make(map[string]struct{}, len(removed))
	for _, value := range uniqueStrings(removed) {
		drop[value] = struct{}{}
	}
	out := make([]string, 0, len(existing))
	for _, value := range uniqueStrings(existing) {
		if _, skip := drop[value]; skip {
			continue
		}
		out = append(out, value)
	}
	return out
}

func hostFromLegacyURL(raw string) string {
	parsed, err := url.Parse(strings.TrimSpace(raw))
	if err != nil {
		return ""
	}
	return parsed.Hostname()
}

func livestreamFromRecord(record livestreamRecord, key string) Livestream {
	host := strings.TrimSpace(record.Host)
	if host == "" {
		host = hostFromLegacyURL(record.URL)
	}
	ids := uniqueStrings(record.MachineIDs)
	if ids == nil {
		ids = []string{}
	}
	return Livestream{
		Name:        key,
		Host:        host,
		Description: strings.TrimSpace(record.Description),
		MachineIDs:  ids,
		URLs:        DeriveLivestreamURLs(host, key),
	}
}

func parseLivestream(data []byte, key string) (Livestream, error) {
	var record livestreamRecord
	if err := json.Unmarshal(data, &record); err != nil {
		return Livestream{}, fmt.Errorf("failed to parse livestream %s: %w", key, err)
	}
	return livestreamFromRecord(record, key), nil
}

func validateLivestream(stream Livestream) (Livestream, error) {
	name, err := NormalizeLivestreamName(stream.Name)
	if err != nil {
		return Livestream{}, err
	}
	host, err := NormalizeLivestreamHost(stream.Host)
	if err != nil {
		return Livestream{}, err
	}
	description := strings.TrimSpace(stream.Description)
	if description == "" {
		return Livestream{}, fmt.Errorf("livestream description is required")
	}
	stream.Name = name
	stream.Host = host
	stream.Description = description
	stream.MachineIDs = uniqueStrings(stream.MachineIDs)
	if stream.MachineIDs == nil {
		stream.MachineIDs = []string{}
	}
	stream.URLs = DeriveLivestreamURLs(host, name)
	return stream, nil
}

func livestreamKV(nc *natsio.Conn, create bool) (natsio.KeyValue, error) {
	js, err := nc.JetStream()
	if err != nil {
		return nil, fmt.Errorf("failed to get JetStream context: %w", err)
	}
	kv, err := js.KeyValue(kvBucketLivestreams)
	if err == nil {
		return kv, nil
	}
	if !create {
		return nil, err
	}
	kv, err = js.CreateKeyValue(&natsio.KeyValueConfig{
		Bucket:  kvBucketLivestreams,
		History: 1,
	})
	if err != nil {
		kv, getErr := js.KeyValue(kvBucketLivestreams)
		if getErr == nil {
			return kv, nil
		}
		return nil, fmt.Errorf("failed to create %s KV bucket: %w", kvBucketLivestreams, err)
	}
	return kv, nil
}

func isMissingLivestreamBucket(err error) bool {
	return errors.Is(err, natsio.ErrBucketNotFound)
}

// ListLivestreams returns every fleet livestream. A missing bucket is empty.
func ListLivestreams(nc *natsio.Conn) ([]Livestream, error) {
	kv, err := livestreamKV(nc, false)
	if err != nil {
		if isMissingLivestreamBucket(err) {
			return []Livestream{}, nil
		}
		return nil, fmt.Errorf("failed to open %s KV bucket: %w", kvBucketLivestreams, err)
	}
	keys, err := kv.Keys()
	if err != nil {
		if errors.Is(err, natsio.ErrNoKeysFound) {
			return []Livestream{}, nil
		}
		return nil, fmt.Errorf("failed to list %s keys: %w", kvBucketLivestreams, err)
	}
	streams := make([]Livestream, 0, len(keys))
	for _, key := range keys {
		entry, err := kv.Get(key)
		if err != nil {
			return nil, fmt.Errorf("failed to get livestream %s: %w", key, err)
		}
		stream, err := parseLivestream(entry.Value(), key)
		if err != nil {
			return nil, err
		}
		streams = append(streams, stream)
	}
	sort.Slice(streams, func(i, j int) bool {
		if streams[i].Host != streams[j].Host {
			return streams[i].Host < streams[j].Host
		}
		return streams[i].Name < streams[j].Name
	})
	return streams, nil
}

// GetLivestream loads one registry record by name.
func GetLivestream(nc *natsio.Conn, name string) (Livestream, error) {
	normalized, err := NormalizeLivestreamName(name)
	if err != nil {
		return Livestream{}, err
	}
	kv, err := livestreamKV(nc, false)
	if err != nil {
		if isMissingLivestreamBucket(err) {
			return Livestream{}, fmt.Errorf("livestream %s not found", normalized)
		}
		return Livestream{}, fmt.Errorf("failed to open %s KV bucket: %w", kvBucketLivestreams, err)
	}
	entry, err := kv.Get(normalized)
	if err != nil {
		if errors.Is(err, natsio.ErrKeyNotFound) {
			return Livestream{}, fmt.Errorf("livestream %s not found", normalized)
		}
		return Livestream{}, fmt.Errorf("failed to get livestream %s: %w", normalized, err)
	}
	return parseLivestream(entry.Value(), normalized)
}

func putLivestreamRecord(kv natsio.KeyValue, stream Livestream) (Livestream, error) {
	stream, err := validateLivestream(stream)
	if err != nil {
		return Livestream{}, err
	}
	payload, err := json.Marshal(livestreamRecord{
		Name:        stream.Name,
		Host:        stream.Host,
		Description: stream.Description,
		MachineIDs:  stream.MachineIDs,
	})
	if err != nil {
		return Livestream{}, fmt.Errorf("failed to encode livestream %s: %w", stream.Name, err)
	}
	if _, err := kv.Put(stream.Name, payload); err != nil {
		return Livestream{}, fmt.Errorf("failed to store livestream %s: %w", stream.Name, err)
	}
	return stream, nil
}

// PutLivestream creates or updates a livestream. An existing name updates
// host/description and unions machine_ids.
func PutLivestream(nc *natsio.Conn, stream Livestream) (Livestream, error) {
	incoming, err := validateLivestream(stream)
	if err != nil {
		return Livestream{}, err
	}
	kv, err := livestreamKV(nc, true)
	if err != nil {
		return Livestream{}, err
	}
	existing, err := GetLivestream(nc, incoming.Name)
	if err == nil {
		incoming.MachineIDs = unionStrings(existing.MachineIDs, incoming.MachineIDs)
	} else if !strings.Contains(err.Error(), "not found") {
		return Livestream{}, err
	}
	return putLivestreamRecord(kv, incoming)
}

// DeleteLivestream removes a registry record.
func DeleteLivestream(nc *natsio.Conn, name string) error {
	normalized, err := NormalizeLivestreamName(name)
	if err != nil {
		return err
	}
	kv, err := livestreamKV(nc, false)
	if err != nil {
		if isMissingLivestreamBucket(err) {
			return fmt.Errorf("livestream %s not found", normalized)
		}
		return fmt.Errorf("failed to open %s KV bucket: %w", kvBucketLivestreams, err)
	}
	if _, err := kv.Get(normalized); err != nil {
		if errors.Is(err, natsio.ErrKeyNotFound) {
			return fmt.Errorf("livestream %s not found", normalized)
		}
		return fmt.Errorf("failed to get livestream %s: %w", normalized, err)
	}
	if err := kv.Delete(normalized); err != nil {
		return fmt.Errorf("failed to delete livestream %s: %w", normalized, err)
	}
	return nil
}

// AttachLivestreamMachines unions machine IDs onto an existing stream.
func AttachLivestreamMachines(nc *natsio.Conn, name string, machineIDs []string) (Livestream, error) {
	ids := uniqueStrings(machineIDs)
	if len(ids) == 0 {
		return Livestream{}, fmt.Errorf("at least one machine ID is required")
	}
	stream, err := GetLivestream(nc, name)
	if err != nil {
		return Livestream{}, err
	}
	stream.MachineIDs = unionStrings(stream.MachineIDs, ids)
	kv, err := livestreamKV(nc, false)
	if err != nil {
		return Livestream{}, fmt.Errorf("failed to open %s KV bucket: %w", kvBucketLivestreams, err)
	}
	return putLivestreamRecord(kv, stream)
}

// DetachLivestreamMachines removes machine IDs from an existing stream.
func DetachLivestreamMachines(nc *natsio.Conn, name string, machineIDs []string) (Livestream, error) {
	ids := uniqueStrings(machineIDs)
	if len(ids) == 0 {
		return Livestream{}, fmt.Errorf("at least one machine ID is required")
	}
	stream, err := GetLivestream(nc, name)
	if err != nil {
		return Livestream{}, err
	}
	stream.MachineIDs = subtractStrings(stream.MachineIDs, ids)
	kv, err := livestreamKV(nc, false)
	if err != nil {
		return Livestream{}, fmt.Errorf("failed to open %s KV bucket: %w", kvBucketLivestreams, err)
	}
	return putLivestreamRecord(kv, stream)
}

// GroupLivestreamsByMachine builds the reverse index used by list/ping.
func GroupLivestreamsByMachine(streams []Livestream) map[string][]LivestreamRef {
	byMachine := make(map[string][]LivestreamRef)
	for _, stream := range streams {
		ref := LivestreamRef{
			Name:        stream.Name,
			Host:        stream.Host,
			Description: stream.Description,
			URLs:        stream.URLs,
		}
		for _, machineID := range stream.MachineIDs {
			byMachine[machineID] = append(byMachine[machineID], ref)
		}
	}
	for machineID, refs := range byMachine {
		sort.Slice(refs, func(i, j int) bool {
			return refs[i].Name < refs[j].Name
		})
		byMachine[machineID] = refs
	}
	return byMachine
}

// GroupLivestreamsByHost groups streams as host -> name -> record.
func GroupLivestreamsByHost(streams []Livestream) map[string]map[string]Livestream {
	byHost := make(map[string]map[string]Livestream)
	for _, stream := range streams {
		if _, ok := byHost[stream.Host]; !ok {
			byHost[stream.Host] = make(map[string]Livestream)
		}
		byHost[stream.Host][stream.Name] = stream
	}
	return byHost
}

// FilterLivestreamsByHosts keeps streams whose host is in hosts. An empty
// hosts list returns streams unchanged. Hosts are normalized like --host.
func FilterLivestreamsByHosts(streams []Livestream, hosts []string) ([]Livestream, error) {
	wanted := make(map[string]struct{})
	for _, host := range hosts {
		normalized, err := NormalizeLivestreamHost(host)
		if err != nil {
			return nil, err
		}
		wanted[normalized] = struct{}{}
	}
	if len(wanted) == 0 {
		return streams, nil
	}
	filtered := make([]Livestream, 0, len(streams))
	for _, stream := range streams {
		if _, ok := wanted[stream.Host]; ok {
			filtered = append(filtered, stream)
		}
	}
	return filtered, nil
}

// FilterLivestreamsByMachines keeps streams attached to any of the given
// machine IDs. An empty list returns streams unchanged.
func FilterLivestreamsByMachines(streams []Livestream, machineIDs []string) []Livestream {
	wanted := make(map[string]struct{})
	for _, id := range uniqueStrings(machineIDs) {
		wanted[id] = struct{}{}
	}
	if len(wanted) == 0 {
		return streams
	}
	filtered := make([]Livestream, 0, len(streams))
	for _, stream := range streams {
		for _, id := range stream.MachineIDs {
			if _, ok := wanted[id]; ok {
				filtered = append(filtered, stream)
				break
			}
		}
	}
	return filtered
}

// ListLivestreamsFiltered returns registry records, optionally limited to
// MediaMTX hosts and/or attached machines. Empty filters return everything.
func ListLivestreamsFiltered(nc *natsio.Conn, hosts, machineIDs []string) ([]Livestream, error) {
	streams, err := ListLivestreams(nc)
	if err != nil {
		return nil, err
	}
	streams, err = FilterLivestreamsByHosts(streams, hosts)
	if err != nil {
		return nil, err
	}
	return FilterLivestreamsByMachines(streams, machineIDs), nil
}

// ListLivestreamsByHosts returns registry records for the given MediaMTX
// hosts. An empty hosts list returns every livestream.
func ListLivestreamsByHosts(nc *natsio.Conn, hosts []string) ([]Livestream, error) {
	return ListLivestreamsFiltered(nc, hosts, nil)
}

func SortedLivestreamHosts(byHost map[string]map[string]Livestream) []string {
	hosts := make([]string, 0, len(byHost))
	for host := range byHost {
		hosts = append(hosts, host)
	}
	sort.Strings(hosts)
	return hosts
}

func SortedLivestreamNames(byName map[string]Livestream) []string {
	names := make([]string, 0, len(byName))
	for name := range byName {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

// LivestreamsByMachine loads the registry and groups refs by machine ID.
func LivestreamsByMachine(nc *natsio.Conn) (map[string][]LivestreamRef, error) {
	streams, err := ListLivestreams(nc)
	if err != nil {
		return nil, err
	}
	return GroupLivestreamsByMachine(streams), nil
}

func LivestreamsForMachine(byMachine map[string][]LivestreamRef, machineID string) []LivestreamRef {
	refs := byMachine[machineID]
	if refs == nil {
		return []LivestreamRef{}
	}
	return refs
}
