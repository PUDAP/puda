package nats

import (
	"errors"
	"strings"
	"time"

	natsio "github.com/nats-io/nats.go"
)

// PUDA JetStream resources. The three command/response streams and the two
// machine KV buckets are required: edges create them with one replica when they
// are missing, and infra/nats/jetstream/setup_streams.sh creates them with the
// deployment's replica count. LIVESTREAMS and E2E_* are created on demand.
var pudaResourceSpecs = []struct {
	name     string
	kind     string
	required bool
}{
	{"COMMAND_QUEUE", "stream", true},
	{"RESPONSE_QUEUE", "stream", true},
	{"RESPONSE_IMMEDIATE", "stream", true},
	{"MACHINE_STATE", "kv", true},
	{"MACHINE_COMMANDS", "kv", true},
	{"LIVESTREAMS", "kv", false},
	{"E2E_KEYRING", "kv", false},
	{"E2E_KEYFILES", "kv", false},
}

// PUDA resource statuses.
const (
	ResourceOK              = "ok"
	ResourceMissing         = "missing"
	ResourceNoLeader        = "no_leader"
	ResourceNoQuorum        = "no_quorum"
	ResourceUnderReplicated = "under_replicated"
	ResourceReplicaLagging  = "replica_lagging"
	ResourceError           = "error"
)

// PUDAResource is one PUDA stream or KV bucket as seen from the local cluster.
type PUDAResource struct {
	Name     string `json:"name"`
	Kind     string `json:"kind"`
	Required bool   `json:"required"`
	Status   string `json:"status"`
	// Replicas is the configured replica count; Leader and the replica lists
	// come from the stream's cluster info and are empty on a standalone server.
	Replicas        int      `json:"replicas,omitempty"`
	Leader          string   `json:"leader,omitempty"`
	LaggingReplicas []string `json:"lagging_replicas,omitempty"`
	Consumers       int      `json:"consumers"`
	// MaxConsumers is the stream's own limit; -1 or 0 means the server/account
	// default applies (1000 per stream on NATS 2.15+ unless raised).
	MaxConsumers int    `json:"max_consumers"`
	Error        string `json:"error,omitempty"`
}

// PUDAHealth reports whether the local cluster has the JetStream resources PUDA
// needs, not just whether JetStream answers.
type PUDAHealth struct {
	Status    string         `json:"status"`
	Reason    string         `json:"reason,omitempty"`
	Resources []PUDAResource `json:"resources"`
}

// streamInfoReader is the part of a JetStream context the resource check uses.
type streamInfoReader interface {
	StreamInfo(stream string, opts ...natsio.JSOpt) (*natsio.StreamInfo, error)
}

func pudaFromConn(nc *natsio.Conn, timeout time.Duration) PUDAHealth {
	js, err := nc.JetStream(natsio.MaxWait(timeout))
	if err != nil {
		return PUDAHealth{Status: "failed", Reason: "jetstream_error", Resources: []PUDAResource{}}
	}
	return checkPUDAResources(js)
}

func checkPUDAResources(js streamInfoReader) PUDAHealth {
	resources := make([]PUDAResource, 0, len(pudaResourceSpecs))
	for _, spec := range pudaResourceSpecs {
		resource := PUDAResource{Name: spec.name, Kind: spec.kind, Required: spec.required}
		stream := spec.name
		if spec.kind == "kv" {
			stream = "KV_" + spec.name
		}
		info, err := js.StreamInfo(stream)
		switch {
		case errors.Is(err, natsio.ErrStreamNotFound):
			resource.Status = ResourceMissing
		case err != nil:
			resource.Status = ResourceError
			resource.Error = err.Error()
		default:
			describeStream(&resource, info)
		}
		resources = append(resources, resource)
	}
	return PUDAHealth{Status: "ok", Resources: resources}
}

func describeStream(resource *PUDAResource, info *natsio.StreamInfo) {
	resource.Status = ResourceOK
	resource.Replicas = info.Config.Replicas
	resource.MaxConsumers = info.Config.MaxConsumers
	resource.Consumers = info.State.Consumers
	if info.Cluster == nil {
		return
	}
	resource.Leader = info.Cluster.Leader
	current := 0
	if resource.Leader != "" {
		current = 1
	}
	for _, peer := range info.Cluster.Replicas {
		if peer == nil {
			continue
		}
		if peer.Offline || !peer.Current {
			resource.LaggingReplicas = append(resource.LaggingReplicas, peer.Name)
		} else {
			current++
		}
	}
	// A leader keeps its title for a while after losing its peers, but cannot
	// commit writes without a majority of replicas.
	switch {
	case resource.Leader == "":
		resource.Status = ResourceNoLeader
	case resource.Replicas > 1 && current < resource.Replicas/2+1:
		resource.Status = ResourceNoQuorum
	case len(resource.LaggingReplicas) > 0:
		resource.Status = ResourceReplicaLagging
	}
}

// finishPUDAHealth applies cluster context and derives the overall PUDA status.
// clustered is true when the local servers report a cluster name: there a
// single-replica stream (typically created by an edge before provisioning)
// does not survive losing its node.
func finishPUDAHealth(puda PUDAHealth, clustered bool) PUDAHealth {
	if puda.Status == "" || puda.Status == "not_checked" {
		return puda
	}
	failed, degraded := false, false
	for i := range puda.Resources {
		resource := &puda.Resources[i]
		if clustered && resource.Status == ResourceOK && resource.Replicas == 1 {
			resource.Status = ResourceUnderReplicated
		}
		if !resource.Required {
			continue
		}
		switch resource.Status {
		case ResourceMissing, ResourceNoLeader, ResourceNoQuorum, ResourceError:
			failed = true
		case ResourceUnderReplicated, ResourceReplicaLagging:
			degraded = true
		}
	}
	switch {
	case failed:
		puda.Status, puda.Reason = "failed", "resources_unavailable"
	case degraded:
		puda.Status, puda.Reason = "degraded", "resources_degraded"
	default:
		puda.Status, puda.Reason = "ok", ""
	}
	return puda
}

// jetStreamNoQuorum recognises the JetStream API error returned while a
// cluster has lost its metadata leader.
func jetStreamNoQuorum(message string) bool {
	message = strings.ToLower(message)
	return strings.Contains(message, "temporarily unavailable") || strings.Contains(message, "no metadata leader")
}
